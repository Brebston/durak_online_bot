"""Безкоштовні турніри на 8 або 16 гравців із сіткою на вибування.

- Завжди відкрита реєстрація в один турнір на 8 і один на 16 (якщо адмін не вимкнув).
- Після першої реєстрації людини йде відлік; коли місця заповнені або час минув — вільні місця займають боти.
- Матчі 1 на 1: з людьми — звичайний стіл; бот проти бота — симуляція на сервері.
- Нічия — переграють. Переможець отримує титул «Чемпіон турніру», чемпіонську сорочку й досвід.
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from collections.abc import Awaitable, Callable

from .db import DB
from .game.bot_ai import choose_action
from .game.engine import Game, Rules
from .personas import random_look, random_nick
from .rooms import Room, RoomError, RoomManager

log = logging.getLogger("tournaments")

SIZES = (8, 16)
DEFAULT_RULES = {"variant": "podkidnoy", "deck_size": 36, "turn_seconds": 30}
NEXT_ROUND_DELAY = 6


def simulate(rules: dict, levels: tuple[str, str], seed: int) -> int:
    """Партія бот проти бота. Повертає 0, якщо виграв перший, 1 — другий."""
    rng = random.Random(seed)
    for _ in range(3):
        g = Game(["a", "b"], Rules.from_dict(rules), seed=rng.randint(0, 10**9))
        steps = 0
        while g.status == "playing" and steps < 3000:
            steps += 1
            for i, p in enumerate(("a", "b")):
                act = choose_action(g.view(p), levels[i], rng)
                if act:
                    g.apply(p, act)
                    break
        if not g.draw and g.loser:
            return 1 if g.loser == "a" else 0
    return rng.randint(0, 1)


class Tournaments:
    def __init__(self, db: DB, rooms: RoomManager, progress, sender: Callable[[int, dict], Awaitable[None]]):
        self.db = db
        self.rooms = rooms
        self.progress = progress
        self.send = sender
        self.notify_offline: Callable[[int, str], Awaitable[None]] | None = None
        self.is_online: Callable[[int], bool] = lambda uid: True
        self.rng = random.SystemRandom()
        self.speed = 1.0
        rooms.on_finish.append(self.on_room_finish)
        rooms.busy = self.busy

    # ---------- налаштування ----------
    def settings(self) -> dict:
        m = self.rooms.modes()
        return {"enabled": m.get("tournaments", True), "wait": int(m.get("tournament_wait", 180))}

    # ---------- запити ----------
    def _players(self, tid: int) -> list[dict]:
        return self.db.q("SELECT * FROM tournament_players WHERE tid=? ORDER BY slot", (tid,))

    def busy(self, uid: int) -> str | None:
        r = self.db.one(
            "SELECT t.id FROM tournament_players p JOIN tournaments t ON t.id=p.tid "
            "WHERE p.user_id=? AND p.out_round IS NULL AND t.status IN ('registering','running')", (uid,))
        return "Ви берете участь у турнірі — дочекайтеся свого матчу" if r else None

    def view(self, tid: int, uid: int | None = None) -> dict:
        t = self.db.one("SELECT * FROM tournaments WHERE id=?", (tid,))
        players = self._players(tid)
        by_slot = {p["slot"]: p for p in players}
        matches = self.db.q("SELECT * FROM tournament_matches WHERE tid=? ORDER BY round, idx", (tid,))
        rounds: dict[int, list] = {}
        for m in matches:
            a, b = by_slot.get(m["a_slot"]), by_slot.get(m["b_slot"])
            rounds.setdefault(m["round"], []).append({
                "a": a["name"] if a else "?", "b": b["name"] if b else "?",
                "winner": None if m["winner_slot"] is None else (0 if m["winner_slot"] == m["a_slot"] else 1),
                "status": m["status"],
                "me": uid is not None and uid in (a and a["user_id"], b and b["user_id"]),
            })
        me = next((p for p in players if uid and p["user_id"] == uid), None)
        winner = by_slot.get(t["winner_slot"]) if t["winner_slot"] is not None else None
        return {
            "id": t["id"], "name": t["name"], "size": t["size"], "status": t["status"], "round": t["round"],
            "rules": json.loads(t["rules"]), "starts_at": t["starts_at"], "now": time.time(),
            "registered": len(players), "players": [p["name"] for p in players],
            "joined": bool(me), "out": bool(me and me["out_round"]),
            "rounds": [rounds[k] for k in sorted(rounds)], "winner": winner["name"] if winner else None,
        }

    def listing(self, uid: int) -> list[dict]:
        rows = self.db.q("SELECT id FROM tournaments WHERE status IN ('registering','running') "
                         "OR (status='finished' AND finished_at > ?) ORDER BY status='finished', size, id DESC LIMIT 8",
                         (int(time.time()) - 6 * 3600,))
        return [self.view(r["id"], uid) for r in rows]

    # ---------- створення / реєстрація ----------
    def create(self, size: int, rules: dict | None = None, auto: bool = True) -> int:
        if size not in SIZES:
            raise RoomError("Турнір може бути на 8 або 16 гравців")
        r = Rules.from_dict({**DEFAULT_RULES, **(rules or {})})
        n = (self.db.one("SELECT COUNT(*) n FROM tournaments")["n"] or 0) + 1
        return self.db.ex("INSERT INTO tournaments(name,size,rules,status,created_at,auto) VALUES(?,?,?,?,?,?)",
                          (f"Турнір #{n} · {size}", size, json.dumps(r.to_dict()), "registering", int(time.time()), int(auto)))

    def ensure_open(self) -> None:
        if not self.settings()["enabled"]:
            return
        for size in SIZES:
            if not self.db.one("SELECT 1 FROM tournaments WHERE status='registering' AND size=? AND auto=1", (size,)):
                self.create(size)

    async def register(self, user: dict, tid: int) -> None:
        uid = user["id"]
        if self.busy(uid):
            raise RoomError("Ви вже берете участь у турнірі")
        cur = self.rooms.current(uid)
        if cur and cur.status == "playing":
            raise RoomError("Спершу завершіть поточний матч")
        t = self.db.one("SELECT * FROM tournaments WHERE id=?", (tid,))
        if not t or t["status"] != "registering":
            raise RoomError("Реєстрацію закрито")
        players = self._players(tid)
        if len(players) >= t["size"]:
            raise RoomError("Турнір заповнений")
        if cur and cur.status == "waiting":
            await self.rooms.leave(uid)
        u = self.db.user(uid)
        slot = len(players)
        self.db.ex("INSERT INTO tournament_players(tid,slot,user_id,name,lvl) VALUES(?,?,?,?,?)",
                   (tid, slot, uid, u["name"], 1))
        if not t["starts_at"]:
            self.db.ex("UPDATE tournaments SET starts_at=? WHERE id=?", (int(time.time()) + self.settings()["wait"], tid))
        if slot + 1 >= t["size"]:
            await self.start(tid)

    def unregister(self, uid: int, tid: int) -> None:
        t = self.db.one("SELECT * FROM tournaments WHERE id=?", (tid,))
        if not t or t["status"] != "registering":
            raise RoomError("Реєстрацію закрито")
        self.db.ex("DELETE FROM tournament_players WHERE tid=? AND user_id=?", (tid, uid))
        # переставляємо слоти без дірок
        for i, p in enumerate(self._players(tid)):
            self.db.ex("UPDATE tournament_players SET slot=? WHERE tid=? AND slot=?", (i, tid, p["slot"]))
        if not self._players(tid):
            self.db.ex("UPDATE tournaments SET starts_at=NULL WHERE id=?", (tid,))

    # ---------- хід турніру ----------
    async def start(self, tid: int) -> None:
        t = self.db.one("SELECT * FROM tournaments WHERE id=?", (tid,))
        if not t or t["status"] != "registering":
            return
        self.db.ex("UPDATE tournaments SET status='running', round=1, starts_at=? WHERE id=?", (int(time.time()), tid))
        players = self._players(tid)
        humans = [p for p in players if p["user_id"]]
        taken = {p["name"] for p in players}
        entries = [dict(p) for p in humans]
        while len(entries) < t["size"]:
            look = random_look(self.rng)
            name = random_nick(self.rng, taken)
            taken.add(name)
            entries.append({"user_id": None, "name": name, "level": self.rng.choice(("hard", "hard", "medium")),
                            "back": look["back"], "lvl": max(1, int(self.rng.triangular(1, 35, 8)))})
        self.rng.shuffle(entries)
        self.db.ex("DELETE FROM tournament_players WHERE tid=?", (tid,))
        for slot, e in enumerate(entries):
            self.db.ex("INSERT INTO tournament_players(tid,slot,user_id,name,level,back,lvl) VALUES(?,?,?,?,?,?,?)",
                       (tid, slot, e["user_id"], e["name"], e.get("level"), e.get("back"), e.get("lvl") or 1))
        for i in range(t["size"] // 2):
            self.db.ex("INSERT INTO tournament_matches(tid,round,idx,a_slot,b_slot) VALUES(?,?,?,?,?)",
                       (tid, 1, i, 2 * i, 2 * i + 1))
        self.ensure_open()
        for p in humans:
            await self.send(p["user_id"], {"type": "tournament", "event": "started", "id": tid})
        await self.launch_round(tid, 1)

    async def launch_round(self, tid: int, rnd: int) -> None:
        t = self.db.one("SELECT * FROM tournaments WHERE id=?", (tid,))
        rules = Rules.from_dict(json.loads(t["rules"]))
        by_slot = {p["slot"]: p for p in self._players(tid)}
        for m in self.db.q("SELECT * FROM tournament_matches WHERE tid=? AND round=? AND status='pending'", (tid, rnd)):
            a, b = by_slot[m["a_slot"]], by_slot[m["b_slot"]]
            if not a["user_id"] and not b["user_id"]:
                self.db.ex("UPDATE tournament_matches SET status='playing' WHERE tid=? AND round=? AND idx=?",
                           (tid, rnd, m["idx"]))
                asyncio.create_task(self._bot_match(tid, m, a, b, rules.to_dict()))
            else:
                await self._live_match(tid, m, a, b, rules)

    def _player_spec(self, p: dict) -> dict:
        if p["user_id"]:
            return {"user_id": p["user_id"]}
        return {"bot": {"name": p["name"], "level": p["level"] or "hard", "back": p["back"], "lvl": p["lvl"]}}

    async def _live_match(self, tid: int, m: dict, a: dict, b: dict, rules: Rules) -> None:
        try:
            room = await self.rooms.create_fixed(
                [self._player_spec(a), self._player_spec(b)], "free", 0, rules,
                meta={"tournament": tid, "tmatch": [m["round"], m["idx"]], "slots": [a["slot"], b["slot"]]},
                name=f"Турнір #{tid} · раунд {m['round']}")
        except RoomError:
            log.exception("cannot start tournament match")
            return
        self.db.ex("UPDATE tournament_matches SET status='playing', match_id=? WHERE tid=? AND round=? AND idx=?",
                   (room.match_id, tid, m["round"], m["idx"]))
        for p in (a, b):
            if p["user_id"] and not self.is_online(p["user_id"]) and self.notify_offline:
                await self.notify_offline(p["user_id"], "tournament_match")

    async def _bot_match(self, tid: int, m: dict, a: dict, b: dict, rules: dict) -> None:
        loop = asyncio.get_running_loop()
        try:
            await asyncio.sleep(self.rng.uniform(25, 70) * self.speed)   # «грають» як люди
            winner = await loop.run_in_executor(
                None, simulate, rules, (a["level"] or "hard", b["level"] or "hard"), self.rng.randint(0, 10**9))
            await self._report(tid, m["round"], m["idx"], a["slot"] if winner == 0 else b["slot"])
        except Exception:  # noqa: BLE001
            log.exception("bot match failed")

    async def on_room_finish(self, room: Room) -> None:
        tid = room.meta.get("tournament")
        if not tid:
            return
        rnd, idx = room.meta["tmatch"]
        a_slot, b_slot = room.meta["slots"]
        g = room.game
        if g.draw:
            # нічия — переграють тим самим складом
            m = self.db.one("SELECT * FROM tournament_matches WHERE tid=? AND round=? AND idx=?", (tid, rnd, idx))
            by_slot = {p["slot"]: p for p in self._players(tid)}
            t = self.db.one("SELECT rules FROM tournaments WHERE id=?", (tid,))
            await asyncio.sleep(3 * self.speed)
            await self._live_match(tid, m, by_slot[a_slot], by_slot[b_slot], Rules.from_dict(json.loads(t["rules"])))
            return
        # місця за столом можуть бути перемішані — визначаємо слот сітки за гравцем
        seat = room.seat_by_pid(g.loser)
        pa = self.db.one("SELECT * FROM tournament_players WHERE tid=? AND slot=?", (tid, a_slot))
        loser_slot = a_slot if seat and ((pa["user_id"] and seat.user_id == pa["user_id"])
                                         or (not pa["user_id"] and seat.bot and seat.name == pa["name"])) else b_slot
        await self._report(tid, rnd, idx, b_slot if loser_slot == a_slot else a_slot)

    async def _report(self, tid: int, rnd: int, idx: int, winner_slot: int) -> None:
        m = self.db.one("SELECT * FROM tournament_matches WHERE tid=? AND round=? AND idx=?", (tid, rnd, idx))
        if not m or m["status"] == "done":
            return
        loser_slot = m["b_slot"] if winner_slot == m["a_slot"] else m["a_slot"]
        self.db.ex("UPDATE tournament_matches SET status='done', winner_slot=? WHERE tid=? AND round=? AND idx=?",
                   (winner_slot, tid, rnd, idx))
        self.db.ex("UPDATE tournament_players SET out_round=? WHERE tid=? AND slot=?", (rnd, tid, loser_slot))
        loser = self.db.one("SELECT * FROM tournament_players WHERE tid=? AND slot=?", (tid, loser_slot))
        if loser["user_id"]:
            await self.send(loser["user_id"], {"type": "tournament", "event": "out", "id": tid, "round": rnd})
        left = self.db.one("SELECT COUNT(*) n FROM tournament_matches WHERE tid=? AND round=? AND status<>'done'",
                           (tid, rnd))["n"]
        if left:
            return
        winners = [r["winner_slot"] for r in self.db.q(
            "SELECT winner_slot FROM tournament_matches WHERE tid=? AND round=? ORDER BY idx", (tid, rnd))]
        if len(winners) == 1:
            await self._finish(tid, winners[0], loser_slot)
            return
        nxt = rnd + 1
        self.db.ex("UPDATE tournaments SET round=? WHERE id=?", (nxt, tid))
        for i in range(len(winners) // 2):
            self.db.ex("INSERT INTO tournament_matches(tid,round,idx,a_slot,b_slot) VALUES(?,?,?,?,?)",
                       (tid, nxt, i, winners[2 * i], winners[2 * i + 1]))
        await asyncio.sleep(NEXT_ROUND_DELAY * self.speed)   # щоб гравці побачили результат
        await self.launch_round(tid, nxt)

    async def _finish(self, tid: int, winner_slot: int, runner_up_slot: int) -> None:
        self.db.ex("UPDATE tournaments SET status='finished', winner_slot=?, finished_at=? WHERE id=?",
                   (winner_slot, int(time.time()), tid))
        w = self.db.one("SELECT * FROM tournament_players WHERE tid=? AND slot=?", (tid, winner_slot))
        r = self.db.one("SELECT * FROM tournament_players WHERE tid=? AND slot=?", (tid, runner_up_slot))
        if r and r["user_id"]:
            self.db.ex("UPDATE users SET xp = xp + 120 WHERE id=?", (r["user_id"],))
        if w["user_id"] and self.progress:
            ach = self.progress.tournament_won(w["user_id"], w["name"], tid)
            await self.send(w["user_id"], {"type": "tournament", "event": "won", "id": tid, "achievements": ach})
        for p in self._players(tid):
            if p["user_id"] and p["slot"] != winner_slot:
                await self.send(p["user_id"], {"type": "tournament", "event": "finished", "id": tid,
                                               "winner": w["name"]})
        self.ensure_open()

    async def loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(2)
                self.ensure_open()
                now = time.time()
                for t in self.db.q("SELECT id, starts_at FROM tournaments WHERE status='registering' AND starts_at IS NOT NULL"):
                    if t["starts_at"] <= now:
                        await self.start(t["id"])
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                log.exception("tournament loop failed")

    def recover(self) -> None:
        """Після перезапуску сервера турніри, що йшли, скасовуються (столи були в памʼяті)."""
        for t in self.db.q("SELECT id FROM tournaments WHERE status='running'"):
            self.db.ex("UPDATE tournaments SET status='cancelled', finished_at=? WHERE id=?", (int(time.time()), t["id"]))
