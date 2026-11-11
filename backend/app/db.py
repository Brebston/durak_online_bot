"""SQLite-сховище. Усі зміни балансу — лише через ledger.py (незмінні транзакції)."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,           -- Telegram user id
    name TEXT NOT NULL,
    username TEXT,
    created_at INTEGER NOT NULL,
    last_seen INTEGER,
    banned INTEGER NOT NULL DEFAULT 0,
    ban_reason TEXT,
    sound INTEGER NOT NULL DEFAULT 1,
    notify INTEGER NOT NULL DEFAULT 1,
    free_day TEXT,
    free_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,            -- u:<id> | bank | fee
    amount INTEGER NOT NULL,          -- +зарахування / -списання (фішки)
    kind TEXT NOT NULL,               -- deposit | admin_credit | admin_debit | stake_win | stake_loss | fee | bank_topup | refund
    ref TEXT,                         -- match id / charge id
    reason TEXT,
    admin_id INTEGER,
    idem TEXT UNIQUE,                 -- ключ ідемпотентності
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS tx_account ON transactions(account);
CREATE TABLE IF NOT EXISTS withdrawal_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    chips INTEGER NOT NULL CHECK(chips > 0),
    stars INTEGER NOT NULL CHECK(stars > 0),
    eur_estimate REAL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','approved','completed','rejected')),
    created_at INTEGER NOT NULL,
    decided_at INTEGER,
    decided_by INTEGER,
    completed_at INTEGER,
    completed_by INTEGER,
    decision_note TEXT,
    payout_reference TEXT
);
CREATE INDEX IF NOT EXISTS withdrawal_status ON withdrawal_requests(status, id DESC);
CREATE INDEX IF NOT EXISTS withdrawal_user ON withdrawal_requests(user_id, id DESC);
CREATE TRIGGER IF NOT EXISTS tx_no_update BEFORE UPDATE ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS tx_no_delete BEFORE DELETE ON transactions
BEGIN SELECT RAISE(ABORT, 'transactions are immutable'); END;
CREATE TABLE IF NOT EXISTS holds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account TEXT NOT NULL,
    amount INTEGER NOT NULL,
    room_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',   -- active | released | settled
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS holds_acc ON holds(account, status);
CREATE TABLE IF NOT EXISTS matches (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    finished_at INTEGER,
    mode TEXT NOT NULL,
    stake INTEGER NOT NULL DEFAULT 0,
    rules TEXT NOT NULL,
    players TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    deal_enc TEXT
);
CREATE TABLE IF NOT EXISTS match_players (
    match_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    PRIMARY KEY (match_id, user_id)
);
CREATE TABLE IF NOT EXISTS match_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    ts REAL NOT NULL,
    actor TEXT,
    type TEXT NOT NULL,
    data TEXT
);
CREATE INDEX IF NOT EXISTS ev_match ON match_events(match_id, seq);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    admin_id INTEGER,
    action TEXT NOT NULL,
    target TEXT,
    data TEXT
);
CREATE TABLE IF NOT EXISTS auth_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    user_id INTEGER,
    ok INTEGER NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    match_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    answer TEXT,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS friend_requests (
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (from_id, to_id)
);
CREATE TABLE IF NOT EXISTS friendships (
    user_id INTEGER NOT NULL,
    friend_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, friend_id)
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_id INTEGER NOT NULL,
    to_id INTEGER NOT NULL,
    text TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    read INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS msg_pair ON messages(from_id, to_id, id);
CREATE TABLE IF NOT EXISTS inventory (
    user_id INTEGER NOT NULL,
    item_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY (user_id, item_id)
);
CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class DB:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)
        self.lock = threading.RLock()
        self._migrate()

    def _migrate(self) -> None:
        """Додає нові колонки до існуючої бази без втрати даних."""
        cols = {r["name"] for r in self.q("PRAGMA table_info(users)")}
        for name, ddl in (
            ("cosmetics", "TEXT NOT NULL DEFAULT '{}'"),
            ("discoverable", "INTEGER NOT NULL DEFAULT 1"),
        ):
            if name not in cols:
                self.conn.execute(f"ALTER TABLE users ADD COLUMN {name} {ddl}")

    @contextmanager
    def tx(self):
        """Атомарна транзакція (BEGIN IMMEDIATE)."""
        with self.lock:
            self.conn.execute("BEGIN IMMEDIATE")
            try:
                yield self.conn
                self.conn.execute("COMMIT")
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise

    def q(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        r = self.q(sql, args)
        return r[0] if r else None

    def ex(self, sql: str, args: tuple = ()) -> int:
        with self.lock:
            cur = self.conn.execute(sql, args)
            return cur.lastrowid

    # ---------- користувачі ----------
    def upsert_user(self, uid: int, name: str, username: str | None) -> dict:
        now = int(time.time())
        self.ex(
            "INSERT INTO users(id,name,username,created_at,last_seen) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, username=excluded.username, last_seen=excluded.last_seen",
            (uid, name, username, now, now),
        )
        return self.one("SELECT * FROM users WHERE id=?", (uid,))

    def user(self, uid: int) -> dict | None:
        return self.one("SELECT * FROM users WHERE id=?", (uid,))

    def audit(self, admin_id: int | None, action: str, target: str | None, data: dict | None = None) -> None:
        self.ex(
            "INSERT INTO audit(ts,admin_id,action,target,data) VALUES(?,?,?,?,?)",
            (int(time.time()), admin_id, action, target, json.dumps(data or {}, ensure_ascii=False)),
        )

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        r = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return r["value"] if r else default

    def kv_set(self, key: str, value: str) -> None:
        self.ex("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
