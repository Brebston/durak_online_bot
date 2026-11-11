"""Бухгалтерія фішок. Баланс = сума незмінних транзакцій; доступно = баланс − активні резерви.

Рахунки: u:<telegram_id> — гравець, bank — банк гри (з нього грають боти), fee — комісія.
"""
from __future__ import annotations

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
        return True

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
                self._insert(conn, FEE, fee, "fee", ref=match_id, idem=f"settle:{match_id}:fee")
        return out

    def history(self, account: str, limit: int = 50) -> list[dict]:
        return self.db.q(
            "SELECT id,amount,kind,ref,reason,created_at FROM transactions WHERE account=? ORDER BY id DESC LIMIT ?",
            (account, limit),
        )
