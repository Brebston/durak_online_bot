"""Кімнати, матчмейкінг, таймери, боти та розрахунок результатів."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .config import settings
from .crypto import DealCipher
from .db import DB
from .game.bot_ai import LEVELS, catch_decision, choose_action
from .game.engine import Game, IllegalMove, Rules
from .ledger import BANK, Ledger, LedgerError, acc
from .levels import level_of, match_xp
from .personas import TEXTS, pick_reaction, random_look, random_nick
from .shop import BY_ID

log = logging.getLogger("rooms")

BOT_NAMES = {"easy": "легкий", "medium": "середній", "hard": "сильний"}


MAX_TIMEOUTS = 3


class RoomError(Exception):
    """Текст помилки — це ключ перекладу (українською) з параметрами {0}, {1}…"""

    def __init__(self, key: str, *args):
        super().__init__(key.format(*args) if args else key)
        self.key, self.args_ = key, [str(a) for a in args]


@dataclass
class Seat:
    pid: str
    name: str
    user_id: int | None = None
    bot: bool = False
    level: str | None = None
    hold_id: int | None = None
    timeouts: int = 0
    back: str = "back_classic"
    emojis: list[str] = field(default_factory=list)  # смайлики бота
    chatty: float = 0.0                               # наскільки бот емоційний
    last_emote: float = 0.0
    seen: set = field(default_factory=set)            # карти, які бот уже «перевірив» на мухлювання
    lvl: int = 1                                       # рівень гравця (для відображення)

    @property
    def account(self) -> str:
        return BANK if self.bot else acc(self.user_id)

    def public(self, me: int | None, hide_bot: bool = False) -> dict:
        bot = self.bot and not hide_bot
        return {"pid": self.pid, "name": self.name, "bot": bot, "level": self.level if bot else None,
                "you": me is not None and self.user_id == me, "back": self.back, "lvl": self.lvl}


@dataclass
class Room:
    id: str
    mode: str                 # free | stake
    stake: int
    size: int
    rules: Rules
    private: bool             # True — власна кімната (за запрошенням / зі списку), без автоботів
    owner: int
    name: str = ""
    listed: bool = False      # показувати власну кімнату в списку кімнат
    seats: list[Seat] = field(default_factory=list)
    fill_at: float = 0        # коли автоматично додати ботів (0 — ніколи)
    fill_task: asyncio.Task | None = None
    chat: list[dict] = field(default_factory=list)
    last: dict | None = None  # останній хід (для анімації на клієнті)
    last_ts: float = 0
    idle_since: float = 0
    moves: int = 0
    status: str = "waiting"   # waiting | playing | finished | cancelled
    game: Game | None = None
    match_id: str | None = None
    deadline: float = 0
    seq: int = 0
    result: dict | None = None
    created: float = field(default_factory=time.time)
    bot_task: asyncio.Task | None = None
    timer_task: asyncio.Task | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def key(self) -> tuple:
        return (self.mode, self.stake, self.size, json.dumps(self.rules.to_dict(), sort_keys=True))

    def seat_of(self, uid: int) -> Seat | None:
        return next((s for s in self.seats if s.user_id == uid), None)

    def seat_by_pid(self, pid: str) -> Seat | None:
        return next((s for s in self.seats if s.pid == pid), None)

    def humans(self) -> list[Seat]:
        return [s for s in self.seats if not s.bot]


Sender = Callable[[int, dict], Awaitable[None]]


class RoomManager:
    def __init__(self, db: DB, ledger: Ledger, cipher: DealCipher, sender: Sender, bot_username: str = "",
                 shop=None, social=None):
        self.shop = shop
        self.social = social
        # викликається, якщо запрошений друг не в мережі: (uid, text, room_id) -> None
        self.notify_offline: Callable[[int, str, int, str], Awaitable[None]] | None = None
        self.online: Callable[[int], bool] = lambda uid: False
        self.db = db
        self.ledger = ledger
        self.cipher = cipher
        self.send = sender
        self.bot_username = bot_username
        self.rooms: dict[str, Room] = {}
        self.user_room: dict[int, str] = {}
        self.rng = random.SystemRandom()

    # ---------- налаштування режимів (змінює адмін) ----------
    def modes(self) -> dict:
        raw = self.db.kv_get("modes")
        base = {"free": True, "stake": True, "bots": True, "stakes": settings.stakes,
                "commission_percent": settings.commission_percent,
                "free_games_per_day": settings.free_games_per_day,
                "bot_fill_seconds": settings.bot_fill_seconds, "bot_level": "mixed"}
        if raw:
            base.update(json.loads(raw))
        return base

    def is_admin(self, uid: int) -> bool:
        return uid in settings.admin_ids

    # ---------- представлення ----------
    def invite_link(self, room: Room) -> str:
        if self.bot_username:
            return f"https://t.me/{self.bot_username}?start=room_{room.id}"
        return f"{settings.webapp_url}?room={room.id}"

    def terms(self, room: Room) -> dict:
        m = self.modes()
        if room.mode != "stake":
            return {"stake": 0, "commission_percent": 0, "max_loss": 0, "win_share": 0}
        fee = int(room.stake * m["commission_percent"] / 100)
        share = (room.stake - fee) // max(1, room.size - 1)
        return {"stake": room.stake, "commission_percent": m["commission_percent"],
                "max_loss": room.stake, "win_share": share, "commission": fee}

    def payload(self, room: Room, uid: int) -> dict:
        seat = room.seat_of(uid)
        data: dict[str, Any] = {
            "type": "room",
            "room": {
                "id": room.id, "mode": room.mode, "stake": room.stake, "size": room.size,
                "rules": room.rules.to_dict(), "private": room.private, "status": room.status,
                "name": room.name, "listed": room.listed, "fill_at": room.fill_at,
                "owner": room.owner == uid,
                # у безкоштовному режимі боти виглядають як звичайні гравці;
                # у грі на фішки позначка бота лишається (гравці платять Stars)
                "seats": [s.public(uid, hide_bot=room.mode == "free") for s in room.seats],
                "deadline": room.deadline, "now": time.time(),
                "terms": self.terms(room), "invite": self.invite_link(room),
                "match_id": room.match_id,
                "chat": room.chat[-40:],
            },
            "last": room.last,
            "game": room.game.view(seat.pid if seat else None) if room.game else None,
            "result": room.result,
        }
        return data

    async def broadcast(self, room: Room) -> None:
        for s in room.humans():
            try:
                await self.send(s.user_id, self.payload(room, s.user_id))
            except Exception:  # noqa: BLE001
                log.exception("send failed")

    def current(self, uid: int) -> Room | None:
        rid = self.user_room.get(uid)
        return self.rooms.get(rid) if rid else None

    def _remember(self, room: Room, ev: dict) -> None:
        room.moves += 1
        room.last = {**ev, "n": room.moves}
        room.last_ts = time.time()
        self._react(room, ev)

    # ---------- реакції ботів (смайлики) ----------
    def _react(self, room: Room, ev: dict) -> None:
        if ev.get("bout_end") == "take":
            taker = ev.get("defender")
            for s in room.seats:
                if s.bot:
                    self._bot_emote(room, s, "i_took" if s.pid == taker else "they_took", 1.0 if s.pid == taker else 0.5)
        elif ev.get("type") == "catch" and ev.get("caught"):
            for s in room.seats:
                if s.bot and s.pid == ev.get("cheater"):
                    self._bot_emote(room, s, "i_took", 1.2)
                elif s.bot and s.pid == ev.get("player"):
                    self._bot_emote(room, s, "i_transferred", 1.2)
        elif ev.get("type") == "transfer":
            s = room.seat_by_pid(ev.get("player"))
            if s and s.bot:
                self._bot_emote(room, s, "i_transferred", 0.8)

    def _bot_emote(self, room: Room, seat: Seat, kind: str, scale: float = 1.0, text_chance: float = 0.0) -> None:
        now = time.time()
        if not seat.bot or now - seat.last_emote < 12 or self.rng.random() > seat.chatty * scale:
            return
        text = None
        if text_chance and self.rng.random() < text_chance and kind in TEXTS:
            text = self.rng.choice(TEXTS[kind])
        emoji = None if text else pick_reaction(self.rng, kind, seat.emojis)
        if not text and not emoji:
            return
        seat.last_emote = now

        async def later():
            await asyncio.sleep(self.rng.uniform(0.8, 2.6))
            if room.id in self.rooms:
                await self._post_chat(room, seat, text=text, emoji=emoji)

        try:
            asyncio.get_running_loop().create_task(later())
        except RuntimeError:
            pass

    async def _post_chat(self, room: Room, seat: Seat, text: str | None = None, emoji: str | None = None) -> None:
        msg: dict[str, Any] = {"pid": seat.pid, "name": seat.name, "ts": time.time()}
        if emoji:
            msg["emoji"] = emoji
        else:
            msg["text"] = text
        room.chat.append(msg)
        del room.chat[:-100]
        self.log_event(room, seat.pid, "chat", {**msg, "bot": seat.bot})
        for s in room.humans():
            await self.send(s.user_id, {"type": "chat", "room": room.id, "msg": msg})

    # ---------- журнал ----------
    def log_event(self, room: Room, actor: str | None, type_: str, data: dict | None = None) -> None:
        if not room.match_id:
            return
        room.seq += 1
        self.db.ex(
            "INSERT INTO match_events(match_id,seq,ts,actor,type,data) VALUES(?,?,?,?,?,?)",
            (room.match_id, room.seq, time.time(), actor, type_, json.dumps(data or {}, ensure_ascii=False)),
        )

    # ---------- створення / вхід ----------
    def _validate_params(self, uid: int, mode: str, size: int, stake: int, rules: dict | None) -> Rules:
        m = self.modes()
        if mode not in ("free", "stake"):
            raise RoomError("Невідомий режим")
        if not m.get(mode):
            raise RoomError("Цей режим зараз вимкнено")
        if size not in (2, 3, 4):
            raise RoomError("Гравців може бути 2, 3 або 4")
        if mode == "stake" and stake not in m["stakes"]:
            raise RoomError("Недоступна ставка")
        try:
            r = Rules.from_dict(rules)
        except (ValueError, TypeError):
            raise RoomError("Невірні правила")
        if size * r.hand_size > r.deck_size:
            raise RoomError("Замало карт у колоді для такої кількості гравців")
        return r

    def _check_user(self, user: dict) -> None:
        u = self.db.user(user["id"])
        if u and u["banned"]:
            raise RoomError("Обліковий запис заблоковано")

    def _check_free_limit(self, uid: int) -> None:
        limit = int(self.modes().get("free_games_per_day") or 0)
        if not limit or self.is_admin(uid):
            return
        u = self.db.user(uid)
        today = time.strftime("%Y-%m-%d")
        if u and u["free_day"] == today and u["free_count"] >= limit:
            raise RoomError("Безкоштовна гра доступна {0} раз(и) на день. Спробуйте завтра або зіграйте на фішки.", limit)

    async def find_match(self, user: dict, mode: str, size: int, stake: int, rules: dict | None) -> Room:
        r = self._validate_params(user["id"], mode, size, stake, rules)
        stake = stake if mode == "stake" else 0
        probe = Room("", mode, stake, size, r, False, user["id"])
        for room in self.rooms.values():
            if (room.status == "waiting" and not room.private and room.key() == probe.key()
                    and len(room.seats) < room.size and not room.seat_of(user["id"])):
                await self.join(user, room.id)
                return room
        return await self.create(user, mode, size, stake, rules, private=False)

    async def create(self, user: dict, mode: str, size: int, stake: int, rules: dict | None, private: bool,
                     name: str = "", listed: bool = False) -> Room:
        r = self._validate_params(user["id"], mode, size, stake, rules)
        name = " ".join((name or "").split())[:40]
        room = Room(secrets.token_hex(6), mode, stake if mode == "stake" else 0, size, r, private, user["id"],
                    name=name or f"Кімната {user.get('name', '')}".strip(), listed=bool(private and listed))
        self.rooms[room.id] = room
        try:
            await self.join(user, room.id)
        except Exception:
            self.rooms.pop(room.id, None)
            raise
        if not private and room.status == "waiting":
            m = self.modes()
            if m.get("bots"):
                room.fill_at = time.time() + max(0, int(m.get("bot_fill_seconds", 8)))
                room.fill_task = asyncio.create_task(self._auto_fill(room))
                await self.broadcast(room)
        return room

    async def _auto_fill(self, room: Room) -> None:
        """«Знайти гру»: якщо за bot_fill_seconds живі суперники не знайшлися — сідають боти."""
        try:
            while room.status == "waiting":
                await asyncio.sleep(max(0.0, room.fill_at - time.time()))
                if room.status != "waiting" or len(room.seats) >= room.size:
                    return
                try:
                    await self._fill_bots(room, self.modes().get("bot_level", "mixed"))
                    return
                except RoomError as e:
                    # напр. порожній банк гри: продовжуємо чекати людей, повторимо пізніше
                    for s in room.humans():
                        await self.send(s.user_id, {"type": "error", "message": f"{e}. Чекаємо живих гравців…",
                                                    "key": "{0}. Чекаємо живих гравців…", "args": [str(e)]})
                    room.fill_at = time.time() + 30
                    await self.broadcast(room)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("auto fill crashed")

    async def join(self, user: dict, room_id: str) -> Room:
        uid = user["id"]
        self._check_user(user)
        room = self.rooms.get(room_id)
        if not room or room.status not in ("waiting",):
            if room and room.seat_of(uid):
                return room
            raise RoomError("Кімнату не знайдено або гра вже почалась")
        if room.seat_of(uid):
            return room
        cur = self.current(uid)
        if cur and cur.id != room.id:
            if cur.status == "playing":
                raise RoomError("Спершу завершіть поточний матч")
            await self.leave(uid)
        if room.mode == "free":
            self._check_free_limit(uid)
        async with room.lock:
            if len(room.seats) >= room.size:
                raise RoomError("Кімната заповнена")
            seat = Seat(pid=f"u{uid}", name=user.get("name") or str(uid), user_id=uid)
            if self.shop:
                seat.back = self.shop.equipped(uid)["back"]
            u = self.db.user(uid)
            seat.lvl = level_of(int(u["xp"] or 0)) if u else 1
            if room.mode == "stake":
                try:
                    seat.hold_id = self.ledger.hold(acc(uid), room.stake, room.id)
                except LedgerError as e:
                    raise RoomError(str(e))
            room.seats.append(seat)
            self.user_room[uid] = room.id
        await self._maybe_start(room)
        await self.broadcast(room)
        return room

    async def add_bots(self, uid: int, room_id: str, level: str) -> None:
        """Ручне додавання ботів — лише у власній кімнаті (у «Знайти гру» боти сідають автоматично)."""
        room = self.rooms.get(room_id)
        if not room or not room.seat_of(uid) or room.status != "waiting":
            raise RoomError("Кімнату не знайдено")
        if not room.private:
            raise RoomError("У швидкій грі суперники підбираються автоматично")
        await self._fill_bots(room, level)

    async def _fill_bots(self, room: Room, level: str) -> None:
        if not self.modes().get("bots"):
            raise RoomError("Боти вимкнені адміністратором")
        if level not in (*LEVELS, "mixed"):
            raise RoomError("Невідома складність")
        async with room.lock:
            while len(room.seats) < room.size:
                lv = level if level != "mixed" else self.rng.choices(LEVELS, weights=(1, 3, 3))[0]
                pids = {s.pid for s in room.seats}
                pid = f"u{self.rng.randint(5_000_000_000, 8_999_999_999)}"
                while pid in pids:
                    pid = f"u{self.rng.randint(5_000_000_000, 8_999_999_999)}"
                name = random_nick(self.rng, {s.name for s in room.seats})
                look = random_look(self.rng)
                seat = Seat(pid=pid, name=name, bot=True, level=lv, back=look["back"],
                            emojis=look["emojis"], chatty=look["chatty"])
                # правдоподібний рівень (не менший, ніж потрібно для «нагородної» сорочки)
                need = BY_ID.get(seat.back, {}).get("level", 1)
                seat.lvl = max(need, min(40, int(self.rng.triangular(1, 35, 6))))
                if room.mode == "stake":
                    try:
                        seat.hold_id = self.ledger.hold(BANK, room.stake, room.id)
                    except LedgerError as e:
                        raise RoomError(str(e))
                room.seats.append(seat)
        await self._maybe_start(room)
        await self.broadcast(room)

    async def leave(self, uid: int) -> None:
        room = self.current(uid)
        if not room:
            return
        seat = room.seat_of(uid)
        if room.status == "playing" and seat:
            await self.surrender(uid)
            self.user_room.pop(uid, None)
            return
        self.user_room.pop(uid, None)
        if room.status != "waiting" or not seat:
            return
        async with room.lock:
            if seat.hold_id:
                self.ledger.release(seat.hold_id)
            room.seats.remove(seat)
            if not room.humans():
                for s in room.seats:
                    if s.hold_id:
                        self.ledger.release(s.hold_id)
                room.status = "cancelled"
                if room.fill_task:
                    room.fill_task.cancel()
                self.rooms.pop(room.id, None)
                return
            if room.owner == uid:
                room.owner = room.humans()[0].user_id
        await self.broadcast(room)

    # ---------- старт ----------
    async def _maybe_start(self, room: Room) -> None:
        if room.status != "waiting" or len(room.seats) < room.size:
            return
        room.status = "playing"
        room.fill_at = 0
        if room.fill_task and room.fill_task is not asyncio.current_task():
            room.fill_task.cancel()
        self.rng.shuffle(room.seats)
        room.game = Game([s.pid for s in room.seats], room.rules)
        room.match_id = f"{time.strftime('%y%m%d')}-{secrets.token_hex(4)}"
        g = room.game
        players = [{"pid": s.pid, "name": s.name, "user_id": s.user_id, "bot": s.bot, "level": s.level}
                   for s in room.seats]
        deal = {"hands": g.initial_deal, "deck": g.initial_deck, "trump_card": g.trump_card}
        self.db.ex(
            "INSERT INTO matches(id,created_at,mode,stake,rules,players,status,deal_enc) VALUES(?,?,?,?,?,?,?,?)",
            (room.match_id, int(time.time()), room.mode, room.stake, json.dumps(room.rules.to_dict()),
             json.dumps(players, ensure_ascii=False), "playing", self.cipher.encrypt(deal)),
        )
        today = time.strftime("%Y-%m-%d")
        for s in room.humans():
            self.db.ex("INSERT OR IGNORE INTO match_players(match_id,user_id) VALUES(?,?)", (room.match_id, s.user_id))
            if room.mode == "free":
                self.db.ex(
                    "UPDATE users SET free_count = CASE WHEN free_day=? THEN free_count+1 ELSE 1 END, free_day=? WHERE id=?",
                    (today, today, s.user_id),
                )
        self.log_event(room, None, "start", {"players": players, "trump": g.trump_card,
                                             "attacker": g.attacker, "rules": room.rules.to_dict(),
                                             "stake": room.stake, "mode": room.mode})
        self._reset_deadline(room)
        room.timer_task = asyncio.create_task(self._timer_loop(room))
        self._kick_bots(room)

    def _reset_deadline(self, room: Room) -> None:
        room.deadline = time.time() + room.rules.turn_seconds

    # ---------- ходи ----------
    async def action(self, uid: int, room_id: str, action: dict, version: int | None) -> None:
        room = self.rooms.get(room_id)
        if not room or room.status != "playing":
            raise RoomError("Матч не активний")
        seat = room.seat_of(uid)
        if not seat:
            raise RoomError("Ви не в цьому матчі")
        async with room.lock:
            if version is not None and version != room.game.version:
                raise RoomError("stale")  # повторний/застарілий запит — відхиляємо
            act = {k: action.get(k) for k in ("type", "card", "target") if action.get(k) is not None}
            if not isinstance(act.get("type"), str) or not isinstance(act.get("card", ""), str) \
                    or not isinstance(act.get("target", 0), int) or isinstance(act.get("target"), bool):
                raise RoomError("Недозволений хід")
            is_cheat = any(la.get("cheat") and {k: v for k, v in la.items() if k != "cheat"} == act
                           for la in room.game.legal_actions(seat.pid))
            try:
                ev = room.game.apply(seat.pid, act)
            except IllegalMove as e:
                raise RoomError(str(e))
            seat.timeouts = 0
            # у журнал (бачить лише адмін після матчу) — чи був хід мухлюванням
            self.log_event(room, seat.pid, "move", {**ev, "cheat": is_cheat})
            self._remember(room, ev)
        await self._after_change(room)

    async def surrender(self, uid: int) -> None:
        room = self.current(uid)
        if not room or room.status != "playing":
            raise RoomError("Матч не активний")
        seat = room.seat_of(uid)
        async with room.lock:
            room.game.surrender(seat.pid)
            self.log_event(room, seat.pid, "surrender", {})
        await self._after_change(room)

    async def _after_change(self, room: Room) -> None:
        if room.game.status == "finished" and room.status == "playing":
            await self._finish(room)
            return
        self._reset_deadline(room)
        await self.broadcast(room)
        self._kick_bots(room)

    # ---------- боти ----------
    def _kick_bots(self, room: Room) -> None:
        if room.status != "playing":
            return
        if room.bot_task and not room.bot_task.done():
            return
        if any(s.bot for s in room.seats):
            room.bot_task = asyncio.create_task(self._bot_loop(room))

    async def _bot_loop(self, room: Room) -> None:
        loop = asyncio.get_running_loop()
        try:
            while room.status == "playing":
                g = room.game
                # після відбою даємо людям роздивитися стіл, перш ніж бот піде далі
                if room.last and room.last.get("bout_end"):
                    pause = 1.3 - (time.time() - room.last_ts)
                    if pause > 0:
                        await asyncio.sleep(pause)
                        continue
                version = g.version
                # «Шулер»: боти стежать за столом і інколи ловлять мухлювання
                if room.rules.cheating:
                    catcher = None
                    for s in room.seats:
                        if s.bot and g.is_active(s.pid):
                            c = catch_decision(g.view(s.pid), s.level, self.rng, s.seen)
                            if c:
                                catcher = (s, c)
                                break
                    if catcher:
                        await asyncio.sleep(self.rng.uniform(0.9, 2.4))
                        s, c = catcher
                        async with room.lock:
                            if room.status != "playing" or c not in g.legal_actions(s.pid):
                                continue
                            ev = g.apply(s.pid, c)
                            self.log_event(room, s.pid, "move", {**ev, "bot": True})
                            self._remember(room, ev)
                        if g.status == "finished":
                            await self._finish(room)
                            return
                        self._reset_deadline(room)
                        await self.broadcast(room)
                        continue
                awaited = set(g.awaited())
                bots = [s for s in room.seats if s.bot and s.pid in awaited]
                if not bots:
                    return
                seat = bots[0]
                await asyncio.sleep(self.rng.uniform(0.7, 1.6))
                if room.status != "playing" or g.version != version:
                    continue
                view = g.view(seat.pid)  # бот бачить лише те, що бачив би гравець
                rng = random.Random(self.rng.random())
                act = await loop.run_in_executor(None, choose_action, view, seat.level, rng)
                if not act:
                    continue
                async with room.lock:
                    if g.version != version or room.status != "playing":
                        continue
                    try:
                        ev = g.apply(seat.pid, act)
                    except IllegalMove:
                        log.warning("bot illegal move %s", act)
                        continue
                    self.log_event(room, seat.pid, "move", {**ev, "bot": True, "cheat": bool(act.get("cheat"))})
                    self._remember(room, ev)
                if g.status == "finished":
                    await self._finish(room)
                    return
                self._reset_deadline(room)
                await self.broadcast(room)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("bot loop crashed")

    # ---------- таймер ----------
    async def _timer_loop(self, room: Room) -> None:
        try:
            while room.status == "playing":
                await asyncio.sleep(0.5)
                if room.status != "playing" or time.time() < room.deadline:
                    continue
                changed = False
                async with room.lock:
                    g = room.game
                    v0 = g.version
                    for pid in list(g.awaited()):
                        seat = room.seat_by_pid(pid)
                        if seat.bot and room.bot_task and not room.bot_task.done():
                            continue
                        act = g.timeout_action(pid)
                        if not act:
                            continue
                        if not seat.bot:
                            seat.timeouts += 1
                            if seat.timeouts >= MAX_TIMEOUTS:
                                g.surrender(pid)
                                self.log_event(room, pid, "afk_surrender", {})
                                break
                        try:
                            ev = g.apply(pid, act)
                            self.log_event(room, pid, "timeout", ev)
                            self._remember(room, ev)
                        except IllegalMove:
                            pass
                        if g.status != "playing":
                            break
                    changed = g.version != v0 or g.status != "playing"
                if changed:
                    await self._after_change(room)
                else:
                    self._reset_deadline(room)
        except asyncio.CancelledError:
            pass
        except Exception:  # noqa: BLE001
            log.exception("timer loop crashed")

    # ---------- завершення ----------
    async def _finish(self, room: Room) -> None:
        if room.status != "playing":
            return
        room.status = "finished"
        g = room.game
        loser_seat = room.seat_by_pid(g.loser) if g.loser else None
        winners = [s for s in room.seats if not loser_seat or s.pid != loser_seat.pid]
        payouts: dict[str, int] = {}
        if room.mode == "stake" and loser_seat and not g.draw:
            res = self.ledger.settle(
                room.id, room.match_id, room.stake, loser_seat.account, [s.account for s in winners],
                self.modes()["commission_percent"],
            )
            # перерахунок у pid для відображення
            payouts[loser_seat.pid] = -room.stake
            share = next((v for k, v in res.items() if v > 0), 0)
            for s in winners:
                payouts[s.pid] = share
        else:
            self.ledger.release_room(room.id)
        room.result = {
            "loser": g.loser, "draw": g.draw, "surrendered": g.surrendered,
            "out_order": list(g.out), "payouts": payouts,
        }
        self.db.ex("UPDATE matches SET status='finished', finished_at=?, result=? WHERE id=?",
                   (int(time.time()), json.dumps(room.result), room.match_id))
        self.log_event(room, None, "finish", room.result)
        await self._award_xp(room)
        if not g.draw:
            for s in room.seats:
                if s.bot:
                    self._bot_emote(room, s, "i_lost" if s.pid == g.loser else "i_won", 1.5, text_chance=0.35)
        await self.broadcast(room)
        for s in room.humans():
            if self.user_room.get(s.user_id) == room.id:
                self.user_room.pop(s.user_id, None)
        for t in (room.timer_task, room.bot_task):
            if t and t is not asyncio.current_task():
                t.cancel()
        asyncio.get_running_loop().call_later(300, lambda: self.rooms.pop(room.id, None))

    async def _award_xp(self, room: Room) -> None:
        g = room.game
        opponents = len(room.seats) - 1
        for s in room.humans():
            if g.draw:
                outcome = "draw"
            elif g.loser == s.pid:
                outcome = "loss"
            else:
                outcome = "win"
            gain = match_xp(outcome, opponents, g.surrendered == s.pid)
            if not gain:
                continue
            u = self.db.user(s.user_id)
            before = level_of(int(u["xp"] or 0)) if u else 1
            self.db.ex("UPDATE users SET xp = xp + ? WHERE id=?", (gain, s.user_id))
            after = level_of(int(u["xp"] or 0) + gain) if u else 1
            await self.send(s.user_id, {"type": "xp", "gain": gain, "level": after, "levelup": after > before})

    async def admin_cancel(self, admin_id: int, room_id: str, reason: str) -> None:
        room = self.rooms.get(room_id)
        if not room or room.status not in ("waiting", "playing"):
            raise RoomError("Кімната не активна")
        room.status = "cancelled"
        if room.fill_task:
            room.fill_task.cancel()
        self.ledger.release_room(room.id)
        room.result = {"cancelled": True, "reason": reason}
        if room.match_id:
            self.db.ex("UPDATE matches SET status='cancelled', finished_at=?, result=? WHERE id=?",
                       (int(time.time()), json.dumps(room.result, ensure_ascii=False), room.match_id))
            self.log_event(room, None, "cancel", {"admin": admin_id, "reason": reason})
        self.db.audit(admin_id, "cancel_match", room.match_id or room.id, {"reason": reason})
        await self.broadcast(room)
        for s in room.humans():
            self.user_room.pop(s.user_id, None)
        for t in (room.timer_task, room.bot_task):
            if t:
                t.cancel()
        self.rooms.pop(room.id, None)

    async def cleanup_loop(self) -> None:
        """Кімнати очікування, де вже кілька хвилин немає жодного гравця онлайн, закриваються,
        а зарезервовані ставки повертаються (щоб фішки не «зависали»)."""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                for room in list(self.rooms.values()):
                    if room.status != "waiting":
                        continue
                    if any(self.online(s.user_id) for s in room.humans()):
                        room.idle_since = 0
                        continue
                    room.idle_since = room.idle_since or now
                    if now - room.idle_since > 300:
                        room.status = "cancelled"
                        if room.fill_task:
                            room.fill_task.cancel()
                        self.ledger.release_room(room.id)
                        for s in room.humans():
                            if self.user_room.get(s.user_id) == room.id:
                                self.user_room.pop(s.user_id, None)
                        self.rooms.pop(room.id, None)
                        log.info("closed idle room %s", room.id)
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                log.exception("cleanup failed")

    def list_waiting(self) -> list[dict]:
        """Список кімнат, до яких можна приєднатися: власні відкриті кімнати + швидкі ігри в очікуванні."""
        out = []
        for r in self.rooms.values():
            if r.status != "waiting" or len(r.seats) >= r.size or (r.private and not r.listed):
                continue
            out.append({"id": r.id, "name": r.name, "custom": r.private, "mode": r.mode, "stake": r.stake,
                        "size": r.size, "players": len(r.seats), "variant": r.rules.variant, "cheating": r.rules.cheating,
                        "deck": r.rules.deck_size, "turn": r.rules.turn_seconds,
                        "host": next((s.name for s in r.seats if s.user_id == r.owner), "")})
        out.sort(key=lambda x: (not x["custom"], -x["players"]))
        return out

    # ---------- чат і смайлики ----------
    async def chat(self, uid: int, text: str | None = None, emoji: str | None = None) -> None:
        room = self.current(uid)
        if not room:
            raise RoomError("Ви не в кімнаті")
        seat = room.seat_of(uid)
        if not seat:
            raise RoomError("Ви не в кімнаті")
        if emoji:
            allowed = self.shop.emojis(uid) if self.shop else []
            if emoji not in allowed:
                raise RoomError("Цей смайлик ще не придбано")
            await self._post_chat(room, seat, emoji=emoji)
            # хтось із ботів може відповісти смайликом
            bots = [s for s in room.seats if s.bot]
            if bots:
                self._bot_emote(room, self.rng.choice(bots), "reply", 0.6)
        else:
            text = " ".join((text or "").split())[:200]
            if not text:
                raise RoomError("Порожнє повідомлення")
            await self._post_chat(room, seat, text=text)

    async def invite(self, uid: int, friend_id: int) -> None:
        room = self.current(uid)
        if not room or room.status != "waiting":
            raise RoomError("Спершу створіть кімнату або почніть пошук гри")
        if not self.social or not self.social.are_friends(uid, friend_id):
            raise RoomError("Запрошувати можна лише друзів")
        if len(room.seats) >= room.size:
            raise RoomError("Кімната вже заповнена")
        seat = room.seat_of(uid)
        payload = {"type": "invite", "room": room.id, "from": seat.name if seat else str(uid),
                   "mode": room.mode, "stake": room.stake, "size": room.size, "variant": room.rules.variant}
        if self.online(friend_id):
            await self.send(friend_id, payload)
        elif self.notify_offline:
            await self.notify_offline(friend_id, payload["from"], room.stake, room.id)
        # поки чекаємо друга — не підсаджуємо ботів одразу
        if room.fill_at:
            room.fill_at = max(room.fill_at, time.time() + 30)
            await self.broadcast(room)
