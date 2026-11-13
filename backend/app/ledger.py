"""Бухгалтерія фішок. Баланс = сума незмінних транзакцій; доступно = баланс − активні резерви.

Рахунки: u:<telegram_id> — гравець, bank — банк гри (з нього грають боти), fee — комісія.
"""
from __future__ import annotations

import json
import sqlite3
import time

from .db import DB

BANK = "bank"
FEE = "fee"
SHOP = "shop"


class LedgerError(Exception):
    pass


def acc(uid: int) -> str:
    return f"u:{uid}"


class Ledger:
    def __init__(self, db: DB):
        self.db = db
        self.watch = None   # callable(account, amount, kind, src) — нагляд за підозрілими операціями

    # ---------- читання ----------
    def balance(self, account: str, conn=None) -> int:
        c = conn or self.db.conn
        with self.db.lock:
            r = c.execute("SELECT COALESCE(SUM(amount),0) FROM transactions WHERE account=?", (account,)).fetchone()
        return int(r[0])

    def held(self, account: str, conn=None) -> int:
        c = conn or self.db.conn
        with self.db.lock:
            r = c.execute(
                "SELECT COALESCE(SUM(amount),0) FROM holds WHERE account=? AND status='active'", (account,)
            ).fetchone()
        return int(r[0])

    def available(self, account: str, conn=None) -> int:
        return self.balance(account, conn) - self.held(account, conn)

    # ---------- запис ----------
    def _insert(self, conn, account: str, amount: int, kind: str, ref=None, reason=None, admin_id=None, idem=None):
        conn.execute(
            "INSERT INTO transactions(account,amount,kind,ref,reason,admin_id,idem,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (account, int(amount), kind, ref, reason, admin_id, idem, int(time.time())),
        )

    def post(self, account: str, amount: int, kind: str, *, ref=None, reason=None, admin_id=None,
             idem: str | None = None, allow_negative: bool = False) -> bool:
        """Проводить транзакцію. Повертає False, якщо ключ idem уже використано (повтор)."""
        if amount == 0:
            raise LedgerError("Нульова сума")
        try:
            with self.db.tx() as conn:
                if amount < 0 and not allow_negative and self.available(account, conn) + amount < 0:
                    raise LedgerError("Недостатньо коштів")
                self._insert(conn, account, amount, kind, ref, reason, admin_id, idem)
        except sqlite3.IntegrityError:
            return False  # повторний запит з тим самим ключем — не зараховуємо двічі
        self._watch(account, amount, kind, None)
        return True

    def transfer(self, src: str, dst: str, amount: int, kind: str, *, ref=None, reason=None,
                 idem: str | None = None) -> bool:
        """Атомарний переказ між рахунками (наприклад, покупка в магазині: гравець → shop)."""
        if amount <= 0:
            raise LedgerError("Сума має бути додатною")
        try:
            with self.db.tx() as conn:
                if self.available(src, conn) < amount:
                    raise LedgerError("Недостатньо фішок")
                self._insert(conn, src, -amount, kind, ref, reason, None, f"{idem}:out" if idem else None)
                self._insert(conn, dst, amount, kind, ref, reason, None, f"{idem}:in" if idem else None)
        except sqlite3.IntegrityError:
            return False
        self._watch(dst, amount, kind, src)
        return True

    def _watch(self, account: str, amount: int, kind: str, src: str | None) -> None:
        """Сповіщення про підозрілі операції (великі суми тощо) — див. ops.Ops.on_tx."""
        if self.watch:
            try:
                self.watch(account, amount, kind, src)
            except Exception:  # noqa: BLE001
                pass

    def admin_adjust(self, admin_id: int, account: str, amount: int, reason: str) -> None:
        reason = (reason or "").strip()
        if len(reason) < 3:
            raise LedgerError("Вкажіть причину")
        kind = "admin_credit" if amount > 0 else "admin_debit"
        if account == BANK:
            kind = "bank_topup" if amount > 0 else "bank_withdraw"
        self.post(account, amount, kind, reason=reason, admin_id=admin_id)
        self.db.audit(admin_id, kind, account, {"amount": amount, "reason": reason})

    # ---------- резерви ставок ----------
    def hold(self, account: str, amount: int, room_id: str) -> int:
        with self.db.tx() as conn:
            if self.available(account, conn) < amount:
                raise LedgerError("Недостатньо фішок для ставки" if account != BANK else "У банку гри недостатньо фішок")
            cur = conn.execute(
                "INSERT INTO holds(account,amount,room_id,status,created_at) VALUES(?,?,?,'active',?)",
                (account, amount, room_id, int(time.time())),
            )
            return cur.lastrowid

    def release(self, hold_id: int) -> None:
        self.db.ex("UPDATE holds SET status='released' WHERE id=? AND status='active'", (hold_id,))

    def release_room(self, room_id: str) -> None:
        self.db.ex("UPDATE holds SET status='released' WHERE room_id=? AND status='active'", (room_id,))

    def create_withdrawal_request(self, uid: int, chips: int, stars: int, eur_estimate: float | None) -> int:
        """Create a pending Stars payout request and reserve chips atomically."""
        if chips <= 0 or stars <= 0:
            raise LedgerError("Сума має бути додатною")
        account = acc(uid)
        with self.db.tx() as conn:
            if self.available(account, conn) < chips:
                raise LedgerError("Недостатньо доступних фішок")
            active = conn.execute(
                "SELECT 1 FROM withdrawal_requests WHERE user_id=? AND status IN ('pending','approved') LIMIT 1",
                (uid,),
            ).fetchone()
            if active:
                raise LedgerError("У вас уже є активна заявка на виведення")
            now = int(time.time())
            cur = conn.execute(
                "INSERT INTO withdrawal_requests(user_id,chips,stars,eur_estimate,status,created_at) "
                "VALUES(?,?,?,?, 'pending',?)",
                (uid, chips, stars, eur_estimate, now),
            )
            request_id = cur.lastrowid
            conn.execute(
                "INSERT INTO holds(account,amount,room_id,status,created_at) VALUES(?,?,?,'active',?)",
                (account, chips, f"withdrawal:{request_id}", now),
            )
            conn.execute(
                "INSERT INTO audit(ts,admin_id,action,target,data) VALUES(?,NULL,?,?,?)",
                (now, "withdrawal_requested", str(request_id),
                 json.dumps({"user_id": uid, "chips": chips, "stars": stars, "eur_estimate": eur_estimate}, ensure_ascii=False)),
            )
            return request_id

    def complete_withdrawal(self, conn, request: dict, admin_id: int, payout_reference: str) -> None:
        """Debit the reserved chips exactly once and settle their hold."""
        rid = request["id"]
        hold = conn.execute(
            "SELECT id,amount FROM holds WHERE account=? AND room_id=? AND status='active'",
            (acc(request["user_id"]), f"withdrawal:{rid}"),
        ).fetchone()
        if not hold or hold["amount"] != request["chips"]:
            raise LedgerError("Резерв заявки не знайдено або його сума не збігається")
        inserted = conn.execute(
            "INSERT OR IGNORE INTO transactions(account,amount,kind,ref,reason,admin_id,idem,created_at) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (acc(request["user_id"]), -request["chips"], "withdrawal", str(rid),
             f"Виплата {request['stars']} Stars; {payout_reference}", admin_id,
             f"withdrawal:{rid}", int(time.time())),
        )
        if inserted.rowcount != 1:
            raise LedgerError("Списання за цією заявкою вже проведене")
        conn.execute("UPDATE holds SET status='settled' WHERE id=? AND status='active'", (hold["id"],))

    def settle(self, room_id: str, match_id: str, stake: int, loser: str | None,
               winners: list[str], commission_percent: float) -> dict:
        """Розрахунок: «дурень» віддає ставку, решта ділять її порівну (мінус комісія).
        Нічия — резерви просто повертаються. Ідемпотентно за match_id."""
        out: dict[str, int] = {}
        with self.db.tx() as conn:
            done = conn.execute("SELECT 1 FROM transactions WHERE idem=?", (f"settle:{match_id}:loss",)).fetchone()
            conn.execute("UPDATE holds SET status='settled' WHERE room_id=? AND status='active'", (room_id,))
            if done or loser is None or stake <= 0 or not winners:
                return out
            fee = int(stake * commission_percent / 100)
            share, rem = divmod(stake - fee, len(winners))
            fee += rem
            self._insert(conn, loser, -stake, "stake_loss", ref=match_id, idem=f"settle:{match_id}:loss")
            out[loser] = -stake
            for i, w in enumerate(winners):
                if share:
                    self._insert(conn, w, share, "stake_win", ref=match_id, idem=f"settle:{match_id}:win:{i}")
                out[w] = share
            if fee:
                self._insert(conn, BANK, fee, "fee", ref=match_id, idem=f"settle:{match_id}:fee")  # комісія — у банк гри
        return out

    def sweep_to_bank(self) -> int:
        """Переносить у банк гри залишки старих рахунків «комісія» і «магазин» (до того, як усе йшло в банк)."""
        moved = 0
        with self.db.tx() as conn:
            for account, kind in ((FEE, "fee_to_bank"), (SHOP, "shop_to_bank")):
                bal = self.balance(account, conn)
                if bal > 0:
                    self._insert(conn, account, -bal, kind, reason="Перенесено в банк гри")
                    self._insert(conn, BANK, bal, kind, reason="Перенесено в банк гри")
                    moved += bal
        return moved

    def bank_report(self, since: int | None, tz_minutes: int = 0, days: int = 14) -> dict:
        """Звіт банку гри: скільки виграли/програли боти банку, комісія, магазин, поповнення."""
        where = "account=?" + (" AND created_at>=?" if since else "")
        args: tuple = (BANK, since) if since else (BANK,)
        by_kind = {r["kind"]: r["s"] for r in self.db.q(
            f"SELECT kind, COALESCE(SUM(amount),0) s FROM transactions WHERE {where} GROUP BY kind", args)}
        # результат по матчах (бот проти бота в одному матчі взаємно гаситься)
        per_match = self.db.q(
            f"SELECT ref, SUM(amount) net FROM transactions WHERE {where} AND kind IN ('stake_win','stake_loss') "
            "GROUP BY ref", args)
        won = sum(r["net"] for r in per_match if r["net"] > 0)
        lost = -sum(r["net"] for r in per_match if r["net"] < 0)
        shift = int(tz_minutes) * 60
        daily = self.db.q(
            "SELECT date(created_at + ?, 'unixepoch') d, "
            "SUM(CASE WHEN kind IN ('stake_win','stake_loss') THEN amount ELSE 0 END) game, "
            "SUM(CASE WHEN kind='fee' THEN amount ELSE 0 END) fee, "
            "SUM(CASE WHEN kind='shop_purchase' THEN amount ELSE 0 END) shop "
            "FROM transactions WHERE account=? AND created_at >= ? GROUP BY d ORDER BY d DESC",
            (shift, BANK, int(time.time()) - days * 86400))
        return {
            "won": won, "lost": lost, "game_net": won - lost,
            "matches_won": sum(1 for r in per_match if r["net"] > 0),
            "matches_lost": sum(1 for r in per_match if r["net"] < 0),
            "fee": by_kind.get("fee", 0),
            "shop": by_kind.get("shop_purchase", 0),
            "topups": by_kind.get("bank_topup", 0) + by_kind.get("fee_to_bank", 0) + by_kind.get("shop_to_bank", 0),
            "withdrawn": -by_kind.get("bank_withdraw", 0),
            "total": sum(by_kind.values()),
            "daily": daily,
        }

    def history(self, account: str, limit: int = 50) -> list[dict]:
        return self.db.q(
            "SELECT id,amount,kind,ref,reason,created_at FROM transactions WHERE account=? ORDER BY id DESC LIMIT ?",
            (account, limit),
        )
