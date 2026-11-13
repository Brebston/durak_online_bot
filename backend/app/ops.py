"""Службові речі для адміністратора: аналітика, розсилка, автобекап, сповіщення про підозріле."""
from __future__ import annotations

import asyncio
import gzip
import logging
import sqlite3
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import DB

log = logging.getLogger("ops")

WATCH_KINDS = {"deposit", "player_transfer", "refund", "admin_credit", "admin_debit"}
REPORTS_ALERT = 3          # скарг від різних гравців за добу
SENDERS_ALERT = 5          # різних відправників переказів одному гравцю за добу
BROADCAST_RATE = 25        # повідомлень на секунду (ліміт Telegram ~30)


def day_of(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


class Ops:
    def __init__(self, db: DB, admin_ids: set[int] | list[int], threshold: Callable[[], int]):
        self.db = db
        self.admin_ids = list(admin_ids)
        self.threshold = threshold
        self.tg = None                     # TgBot, коли бот запущено
        self.progress = None
        self.broadcast_state: dict = {"running": False}
        self._tasks: set[asyncio.Task] = set()

    # ---------- сповіщення ----------
    def alert(self, kind: str, target: str | None, text: str, dedupe: str | None = None) -> bool:
        try:
            self.db.ex("INSERT INTO alerts(kind,target,text,dedupe,created_at) VALUES(?,?,?,?,?)",
                       (kind, target, text, dedupe, int(time.time())))
        except sqlite3.IntegrityError:
            return False                   # про це вже сповіщали
        self._spawn(self._push_admins("⚠️ " + text))
        return True

    def _spawn(self, coro) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            coro.close()
            return
        t = loop.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def _push_admins(self, text: str) -> None:
        if not self.tg:
            return
        for a in self.admin_ids:
            try:
                await self.tg.bot.send_message(a, text)
            except Exception:  # noqa: BLE001
                log.info("cannot notify admin %s", a)

    def on_tx(self, account: str, amount: int, kind: str, src: str | None) -> None:
        if kind not in WATCH_KINDS or not account.startswith("u:"):
            return
        limit = int(self.threshold() or 0)
        if limit and abs(amount) >= limit:
            who = f"{src} → {account}" if src else account
            self.alert("amount", account, f"Велика операція {kind}: {amount} фішок ({who})")
        if kind == "player_transfer":
            since = int(time.time()) - 86400
            n = self.db.one(
                "SELECT COUNT(DISTINCT t2.account) n FROM transactions t1 JOIN transactions t2 "
                "ON t2.ref=t1.ref AND t2.kind='player_transfer' AND t2.amount<0 "
                "WHERE t1.account=? AND t1.kind='player_transfer' AND t1.amount>0 AND t1.created_at>=?",
                (account, since))["n"]
            if n >= SENDERS_ALERT:
                self.alert("senders", account, f"{account} отримав перекази від {n} різних гравців за добу",
                           dedupe=f"senders:{account}:{day_of(time.time())}")

    def report(self, from_id: int, target_id: int, reason: str, match_id: str | None) -> None:
        now = int(time.time())
        if self.db.one("SELECT 1 FROM reports WHERE from_id=? AND target_id=? AND created_at>=?",
                       (from_id, target_id, now - 86400)):
            return                          # одна скарга на гравця на добу
        self.db.ex("INSERT INTO reports(from_id,target_id,reason,match_id,created_at) VALUES(?,?,?,?,?)",
                   (from_id, target_id, reason[:300], match_id, now))
        n = self.db.one("SELECT COUNT(DISTINCT from_id) n FROM reports WHERE target_id=? AND created_at>=?",
                        (target_id, now - 86400))["n"]
        if n >= REPORTS_ALERT:
            u = self.db.user(target_id)
            self.alert("reports", f"u:{target_id}",
                       f"На гравця {u['name'] if u else target_id} ({target_id}) {n} скарг за добу",
                       dedupe=f"reports:{target_id}:{day_of(now)}")

    # ---------- аналітика ----------
    def analytics(self, days: int = 14, online: int = 0) -> dict:
        days = max(1, min(days, 90))
        now = time.time()
        start = int(now) - days * 86400
        dau = {r["d"]: r["n"] for r in self.db.q(
            "SELECT date(ts,'unixepoch') d, COUNT(DISTINCT user_id) n FROM auth_log WHERE ok=1 AND ts>=? GROUP BY d",
            (start,))}
        new = {r["d"]: r["n"] for r in self.db.q(
            "SELECT date(created_at,'unixepoch') d, COUNT(*) n FROM users WHERE created_at>=? GROUP BY d", (start,))}
        games = {r["d"]: r["n"] for r in self.db.q(
            "SELECT date(created_at,'unixepoch') d, COUNT(*) n FROM matches WHERE created_at>=? GROUP BY d", (start,))}
        stars = {r["d"]: r["n"] for r in self.db.q(
            "SELECT date(created_at,'unixepoch') d, SUM(amount) n FROM transactions "
            "WHERE kind='deposit' AND created_at>=? GROUP BY d", (start,))}
        # D1: хто зареєструвався в день X і зайшов у день X+1
        d1 = {}
        for r in self.db.q(
                "SELECT date(u.created_at,'unixepoch') d, COUNT(*) total, "
                "SUM(EXISTS(SELECT 1 FROM auth_log a WHERE a.user_id=u.id AND a.ok=1 "
                "AND date(a.ts,'unixepoch')=date(u.created_at,'unixepoch','+1 day'))) back "
                "FROM users u WHERE u.created_at>=? GROUP BY d", (start - 86400,)):
            d1[r["d"]] = round(100 * (r["back"] or 0) / r["total"]) if r["total"] else None
        series = []
        for i in range(days - 1, -1, -1):
            d = (datetime.fromtimestamp(now, timezone.utc) - timedelta(days=i)).strftime("%Y-%m-%d")
            series.append({"day": d, "dau": dau.get(d, 0), "new": new.get(d, 0), "games": games.get(d, 0),
                           "d1": d1.get(d) if i > 0 else None, "chips_bought": stars.get(d, 0) or 0})
        modes = self.db.q(
            "SELECT mode, COALESCE(kind,'quick') kind, json_array_length(players) size, "
            "json_extract(rules,'$.variant') variant, COUNT(*) n FROM matches WHERE created_at>=? "
            "GROUP BY 1,2,3,4 ORDER BY n DESC LIMIT 20", (start,))
        week = int(now) - 7 * 86400
        return {
            "series": series, "modes": modes, "online": online,
            "totals": {
                "users": self.db.one("SELECT COUNT(*) n FROM users")["n"],
                "wau": self.db.one("SELECT COUNT(DISTINCT user_id) n FROM auth_log WHERE ok=1 AND ts>=?", (week,))["n"],
                "games_week": self.db.one("SELECT COUNT(*) n FROM matches WHERE created_at>=?", (week,))["n"],
            },
        }

    # ---------- розсилка ----------
    def recipients(self) -> list[int]:
        return [r["id"] for r in self.db.q("SELECT id FROM users WHERE notify=1 AND banned=0 ORDER BY id")]

    async def broadcast(self, text: str, button: str, admin_id: int, test: bool = False) -> dict:
        if not self.tg:
            raise RuntimeError("Бот не запущений")
        if test:
            await self.tg.bot.send_message(admin_id, text, reply_markup=self.tg.webapp_button(button))
            return {"sent": 1, "test": True}
        if self.broadcast_state.get("running"):
            raise RuntimeError("Розсилка вже йде")
        ids = self.recipients()
        self.broadcast_state = {"running": True, "total": len(ids), "sent": 0, "failed": 0,
                                "started": int(time.time()), "by": admin_id}
        self.db.audit(admin_id, "broadcast", None, {"text": text[:500], "total": len(ids)})
        self._spawn(self._run_broadcast(ids, text, button))
        return dict(self.broadcast_state)

    async def _run_broadcast(self, ids: list[int], text: str, button: str) -> None:
        st = self.broadcast_state
        markup = self.tg.webapp_button(button)
        try:
            for uid in ids:
                try:
                    await self.tg.bot.send_message(uid, text, reply_markup=markup)
                    st["sent"] += 1
                except Exception as e:  # noqa: BLE001
                    retry = getattr(e, "retry_after", None)
                    if retry:
                        await asyncio.sleep(float(retry))
                        try:
                            await self.tg.bot.send_message(uid, text, reply_markup=markup)
                            st["sent"] += 1
                            continue
                        except Exception:  # noqa: BLE001
                            pass
                    st["failed"] += 1
                await asyncio.sleep(1 / BROADCAST_RATE)
        finally:
            st["running"] = False
            st["finished"] = int(time.time())

    # ---------- бекап ----------
    def make_backup(self) -> tuple[str, bytes]:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "durak.db"
            dst = sqlite3.connect(path)
            with self.db.lock:
                self.db.conn.backup(dst)
            dst.close()
            data = gzip.compress(path.read_bytes(), compresslevel=6)
        name = f"durak-backup-{datetime.now(timezone.utc).strftime('%Y-%m-%d_%H%M')}.db.gz"
        return name, data

    async def send_backup(self, reason: str = "auto") -> dict:
        name, data = await asyncio.get_running_loop().run_in_executor(None, self.make_backup)
        sent = 0
        if self.tg:
            from aiogram.types import BufferedInputFile

            for a in self.admin_ids:
                try:
                    await self.tg.bot.send_document(
                        a, BufferedInputFile(data, filename=name),
                        caption=f"💾 Бекап бази ({'щоденний' if reason == 'auto' else 'вручну'}), {len(data) // 1024} КБ")
                    sent += 1
                except Exception:  # noqa: BLE001
                    log.exception("backup send failed")
        self.db.kv_set("last_backup", str(int(time.time())))
        return {"name": name, "size": len(data), "sent": sent}

    async def loop(self) -> None:
        """Раз на добу — бекап у Telegram; щогодини — нагороди за минулі сезони."""
        while True:
            try:
                await asyncio.sleep(60)
                now = time.time()
                if self.progress:
                    self.progress.award_finished_seasons(now)
                today = day_of(now)
                if self.tg and self.admin_ids and self.db.kv_get("backup_day") != today:
                    self.db.kv_set("backup_day", today)
                    await self.send_backup("auto")
            except asyncio.CancelledError:
                return
            except Exception:  # noqa: BLE001
                log.exception("ops loop failed")
