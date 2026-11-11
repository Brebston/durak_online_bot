"""Друзі, пошук гравців і особисті повідомлення."""
from __future__ import annotations

import time

from .db import DB

MAX_FRIENDS = 300
MAX_MSG = 500


class SocialError(Exception):
    pass


def clean_text(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise SocialError("Порожнє повідомлення")
    return text[:limit]


class Social:
    def __init__(self, db: DB):
        self.db = db

    def _user(self, uid: int) -> dict:
        u = self.db.user(uid)
        if not u:
            raise SocialError("Гравця не знайдено")
        return u

    def public_user(self, u: dict, online: set[int]) -> dict:
        from .levels import level_of

        return {"id": u["id"], "name": u["name"], "username": u["username"], "online": u["id"] in online,
                "lvl": level_of(int(u.get("xp") or 0))}

    def search(self, uid: int, q: str, online: set[int]) -> list[dict]:
        q = (q or "").strip().lstrip("@")
        if len(q) < 2:
            return []
        like = f"%{q}%"
        rows = self.db.q(
            "SELECT * FROM users WHERE id<>? AND banned=0 AND discoverable=1 AND "
            "(name LIKE ? OR username LIKE ? OR CAST(id AS TEXT)=?) ORDER BY last_seen DESC LIMIT 30",
            (uid, like, like, q),
        )
        friends = self.friend_ids(uid)
        out = []
        for r in rows:
            d = self.public_user(r, online)
            d["friend"] = r["id"] in friends
            d["requested"] = bool(self.db.one("SELECT 1 FROM friend_requests WHERE from_id=? AND to_id=?", (uid, r["id"])))
            out.append(d)
        return out

    def friend_ids(self, uid: int) -> set[int]:
        return {r["friend_id"] for r in self.db.q("SELECT friend_id FROM friendships WHERE user_id=?", (uid,))}

    def are_friends(self, a: int, b: int) -> bool:
        return bool(self.db.one("SELECT 1 FROM friendships WHERE user_id=? AND friend_id=?", (a, b)))

    def request(self, uid: int, to: int) -> str:
        if uid == to:
            raise SocialError("Не можна додати себе")
        target = self._user(to)
        if target["banned"]:
            raise SocialError("Гравця заблоковано")
        if self.are_friends(uid, to):
            return "friends"
        if len(self.friend_ids(uid)) >= MAX_FRIENDS:
            raise SocialError("Забагато друзів")
        # зустрічна заявка — одразу дружба
        if self.db.one("SELECT 1 FROM friend_requests WHERE from_id=? AND to_id=?", (to, uid)):
            self._make_friends(uid, to)
            return "friends"
        if self.db.one("SELECT COUNT(*) n FROM friend_requests WHERE from_id=?", (uid,))["n"] >= 50:
            raise SocialError("Забагато непідтверджених заявок")
        self.db.ex("INSERT OR IGNORE INTO friend_requests(from_id,to_id,created_at) VALUES(?,?,?)",
                   (uid, to, int(time.time())))
        return "requested"

    def _make_friends(self, a: int, b: int) -> None:
        now = int(time.time())
        with self.db.tx() as c:
            c.execute("DELETE FROM friend_requests WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)", (a, b, b, a))
            c.execute("INSERT OR IGNORE INTO friendships(user_id,friend_id,created_at) VALUES(?,?,?)", (a, b, now))
            c.execute("INSERT OR IGNORE INTO friendships(user_id,friend_id,created_at) VALUES(?,?,?)", (b, a, now))

    def respond(self, uid: int, from_id: int, accept: bool) -> None:
        if not self.db.one("SELECT 1 FROM friend_requests WHERE from_id=? AND to_id=?", (from_id, uid)):
            raise SocialError("Заявку не знайдено")
        if accept:
            self._make_friends(uid, from_id)
        else:
            self.db.ex("DELETE FROM friend_requests WHERE from_id=? AND to_id=?", (from_id, uid))

    def remove(self, uid: int, other: int) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM friendships WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)",
                      (uid, other, other, uid))
            c.execute("DELETE FROM friend_requests WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?)",
                      (uid, other, other, uid))

    def overview(self, uid: int, online: set[int]) -> dict:
        friends = self.db.q(
            "SELECT u.* FROM friendships f JOIN users u ON u.id=f.friend_id WHERE f.user_id=? ORDER BY u.name", (uid,))
        incoming = self.db.q(
            "SELECT u.* FROM friend_requests r JOIN users u ON u.id=r.from_id WHERE r.to_id=? ORDER BY r.created_at DESC", (uid,))
        outgoing = self.db.q(
            "SELECT u.* FROM friend_requests r JOIN users u ON u.id=r.to_id WHERE r.from_id=? ORDER BY r.created_at DESC", (uid,))
        unread = {r["from_id"]: r["n"] for r in self.db.q(
            "SELECT from_id, COUNT(*) n FROM messages WHERE to_id=? AND read=0 GROUP BY from_id", (uid,))}
        fl = []
        for f in friends:
            d = self.public_user(f, online)
            d["unread"] = unread.get(f["id"], 0)
            fl.append(d)
        fl.sort(key=lambda d: (not d["online"], -d["unread"], d["name"].lower()))
        return {
            "friends": fl,
            "incoming": [self.public_user(u, online) for u in incoming],
            "outgoing": [self.public_user(u, online) for u in outgoing],
        }

    # ---------- особисті повідомлення (лише між друзями) ----------
    def send_message(self, uid: int, to: int, text: str) -> dict:
        if not self.are_friends(uid, to):
            raise SocialError("Писати можна лише друзям")
        text = clean_text(text, MAX_MSG)
        now = int(time.time())
        mid = self.db.ex("INSERT INTO messages(from_id,to_id,text,created_at) VALUES(?,?,?,?)", (uid, to, text, now))
        return {"id": mid, "from_id": uid, "to_id": to, "text": text, "created_at": now}

    def conversation(self, uid: int, other: int, limit: int = 100) -> list[dict]:
        if not self.are_friends(uid, other):
            raise SocialError("Писати можна лише друзям")
        rows = self.db.q(
            "SELECT id,from_id,to_id,text,created_at FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) "
            "ORDER BY id DESC LIMIT ?", (uid, other, other, uid, limit))
        self.db.ex("UPDATE messages SET read=1 WHERE from_id=? AND to_id=? AND read=0", (other, uid))
        return list(reversed(rows))
