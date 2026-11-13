"""Прогрес гравця: статистика, щоденні завдання, серія днів, досягнення, титули, очки сезону/тижня, рейтинг Elo."""
from __future__ import annotations

import datetime as dt
import random
import time

from .db import DB
from .levels import level_of

# ---------------- щоденні завдання ----------------
# kind: (опис-ключ перекладу з {0}, варіанти цілі, нагорода XP)
QUEST_KINDS: dict[str, tuple[str, tuple[int, ...], int]] = {
    "win": ("Виграй партії", (2, 3), 60),
    "play": ("Зіграй партії", (3, 5), 40),
    "defend_trump": ("Відбийся козирем", (3, 5), 50),
    "throw_in": ("Підкинь карти", (8, 12), 40),
    "transfer": ("Переведи атаку", (2, 3), 60),
    "win_no_take": ("Виграй, жодного разу не взявши карти", (1,), 80),
    "win_multi": ("Виграй гру на 3–4 гравців", (1,), 70),
    "catch": ("Спіймай мухляра в режимі «Шулер»", (1,), 70),
}
QUESTS_PER_DAY = 3

# ---------------- досягнення ----------------
# id: (назва, опис, поле статистики, поріг)
ACHIEVEMENTS: dict[str, tuple[str, str, str, int]] = {
    "first_win": ("Перша перемога", "Виграй першу партію", "wins", 1),
    "wins_10": ("Досвідчений", "10 перемог", "wins", 10),
    "wins_100": ("Ветеран", "100 перемог", "wins", 100),
    "first_transfer": ("Перший перевід", "Переведи атаку на іншого гравця", "transfers", 1),
    "catcher_10": ("Мисливець на шулерів", "Спіймай 10 мухлярів", "catches", 10),
    "no_take_win": ("Чистий виграш", "Виграй без жодного взяття", "no_take_wins", 1),
    "trump_50": ("Козирний туз", "Відбийся козирем 50 разів", "trump_defends", 50),
    "win_streak_5": ("На хвилі", "5 перемог поспіль", "best_win_streak", 5),
    "four_win": ("Король столу", "Виграй за столом на 3–4 гравців", "four_wins", 1),
    "ranked_10": ("Рейтинговий боєць", "10 перемог у рейтингових матчах", "ranked_wins", 10),
    "tournament_win": ("Чемпіон", "Виграй турнір", "tournament_wins", 1),
    "streak_7": ("Тиждень поспіль", "Заходь у гру 7 днів поспіль", "best_streak", 7),
    "level_10": ("Десятка", "Досягни 10 рівня", "level", 10),
}

# ---------------- серія днів ----------------
STREAK_XP = 20            # × номер дня (до 7)
STREAK_ITEM_DAY = 7       # на 7-й день — нагородна сорочка
STREAK_ITEM = "back_streak"

ELO_START = 1000


def today(now: float | None = None) -> str:
    return dt.datetime.fromtimestamp(now or time.time(), dt.UTC).strftime("%Y-%m-%d")


def season_id(now: float | None = None) -> str:
    return dt.datetime.fromtimestamp(now or time.time(), dt.UTC).strftime("%Y-%m")


def season_bounds(sid: str) -> tuple[int, int]:
    y, m = map(int, sid.split("-"))
    start = dt.datetime(y, m, 1, tzinfo=dt.UTC)
    end = dt.datetime(y + (m == 12), m % 12 + 1, 1, tzinfo=dt.UTC)
    return int(start.timestamp()), int(end.timestamp())


def elo_delta(rating: int, opp: int, score: float, games: int) -> int:
    k = 40 if games < 20 else 24
    expected = 1 / (1 + 10 ** ((opp - rating) / 400))
    return round(k * (score - expected))


class Progress:
    def __init__(self, db: DB):
        self.db = db

    # ---------- статистика ----------
    def stats(self, uid: int) -> dict:
        self.db.ex("INSERT OR IGNORE INTO user_stats(user_id) VALUES(?)", (uid,))
        return self.db.one("SELECT * FROM user_stats WHERE user_id=?", (uid,))

    # ---------- щоденні завдання ----------
    def quests(self, uid: int, now: float | None = None) -> list[dict]:
        day = today(now)
        rows = self.db.q("SELECT * FROM quests WHERE user_id=? AND day=? ORDER BY rowid", (uid, day))
        if not rows:
            rng = random.Random(f"{uid}:{day}")
            for kind in rng.sample(sorted(QUEST_KINDS), QUESTS_PER_DAY):
                _, targets, reward = QUEST_KINDS[kind]
                target = rng.choice(targets)
                self.db.ex("INSERT OR IGNORE INTO quests(user_id,day,qid,target,reward) VALUES(?,?,?,?,?)",
                           (uid, day, kind, target, reward + 10 * (target - targets[0])))
            rows = self.db.q("SELECT * FROM quests WHERE user_id=? AND day=? ORDER BY rowid", (uid, day))
        return [{**r, "text": QUEST_KINDS[r["qid"]][0], "done": bool(r["done_at"])} for r in rows]

    def _bump_quests(self, uid: int, deltas: dict[str, int]) -> list[dict]:
        done = []
        for q in self.quests(uid):
            add = deltas.get(q["qid"], 0)
            if not add or q["done"]:
                continue
            prog = min(q["target"], q["progress"] + add)
            fin = prog >= q["target"]
            self.db.ex("UPDATE quests SET progress=?, done_at=? WHERE user_id=? AND day=? AND qid=?",
                       (prog, int(time.time()) if fin else None, uid, q["day"], q["qid"]))
            if fin:
                self.db.ex("UPDATE users SET xp = xp + ? WHERE id=?", (q["reward"], uid))
                done.append({"text": q["text"], "target": q["target"], "reward": q["reward"]})
        return done

    # ---------- серія днів ----------
    def daily_login(self, uid: int, now: float | None = None) -> dict | None:
        """Перший вхід за день: продовжуємо або скидаємо серію, видаємо нагороду. None — сьогодні вже було."""
        u = self.db.user(uid)
        if not u:
            return None
        d = today(now)
        if u["streak_day"] == d:
            return None
        yesterday = today((now or time.time()) - 86400)
        streak = (u["streak"] or 0) + 1 if u["streak_day"] == yesterday else 1
        best = max(streak, u["best_streak"] or 0)
        xp = STREAK_XP * min(streak, 7)
        self.db.ex("UPDATE users SET streak=?, best_streak=?, streak_day=?, xp = xp + ? WHERE id=?",
                   (streak, best, d, xp, uid))
        reward = {"streak": streak, "xp": xp, "item": None}
        if streak >= STREAK_ITEM_DAY and not self.db.one(
                "SELECT 1 FROM inventory WHERE user_id=? AND item_id=?", (uid, STREAK_ITEM)):
            self.db.ex("INSERT OR IGNORE INTO inventory(user_id,item_id,created_at) VALUES(?,?,?)",
                       (uid, STREAK_ITEM, int(time.time())))
            reward["item"] = STREAK_ITEM
        reward["achievements"] = self._check_achievements(uid)
        return reward

    # ---------- досягнення й титули ----------
    def achievements(self, uid: int) -> list[dict]:
        have = {r["ach_id"]: r["created_at"] for r in self.db.q(
            "SELECT ach_id, created_at FROM user_achievements WHERE user_id=?", (uid,))}
        st = self.stats(uid)
        u = self.db.user(uid) or {}
        vals = {**st, "best_streak": u.get("best_streak") or 0, "level": level_of(int(u.get("xp") or 0))}
        return [{"id": k, "name": n, "desc": d, "unlocked": k in have, "at": have.get(k),
                 "progress": min(vals.get(f, 0), thr), "target": thr}
                for k, (n, d, f, thr) in ACHIEVEMENTS.items()]

    def _check_achievements(self, uid: int) -> list[dict]:
        new = []
        for a in self.achievements(uid):
            if not a["unlocked"] and a["progress"] >= a["target"]:
                self.db.ex("INSERT OR IGNORE INTO user_achievements(user_id,ach_id,created_at) VALUES(?,?,?)",
                           (uid, a["id"], int(time.time())))
                new.append({"id": a["id"], "name": a["name"]})
        return new

    def grant_title(self, uid: int, title_id: str, label: str) -> None:
        self.db.ex("INSERT OR IGNORE INTO user_titles(user_id,title_id,label,created_at) VALUES(?,?,?,?)",
                   (uid, title_id, label, int(time.time())))
        self.db.ex("UPDATE users SET title=? WHERE id=?", (label, uid))

    def titles(self, uid: int) -> list[dict]:
        return self.db.q("SELECT title_id, label, created_at FROM user_titles WHERE user_id=? ORDER BY created_at DESC",
                         (uid,))

    # ---------- підсумок матчу ----------
    def record_match(self, uid: int, *, outcome: str, size: int, ranked: bool, cheating: bool,
                     counters: dict, surrendered: bool) -> dict:
        """Оновлює статистику, завдання, очки та досягнення. Повертає, що нового відкрилося."""
        win = outcome == "win"
        self.stats(uid)
        took = counters.get("takes", 0)
        self.db.ex(
            "UPDATE user_stats SET games=games+1, wins=wins+?, losses=losses+?, draws=draws+?, "
            "transfers=transfers+?, catches=catches+?, trump_defends=trump_defends+?, throw_ins=throw_ins+?, "
            "no_take_wins=no_take_wins+?, four_wins=four_wins+?, ranked_wins=ranked_wins+?, "
            "win_streak=CASE WHEN ? THEN win_streak+1 ELSE 0 END, "
            "best_win_streak=MAX(best_win_streak, CASE WHEN ? THEN win_streak+1 ELSE 0 END) WHERE user_id=?",
            (int(win), int(outcome == "loss"), int(outcome == "draw"), counters.get("transfers", 0),
             counters.get("catches", 0), counters.get("trump_defends", 0), counters.get("throw_ins", 0),
             int(win and took == 0), int(win and size >= 3), int(win and ranked), int(win), int(win), uid))
        points = 0 if surrendered else {"win": 3, "draw": 1, "loss": 0}[outcome] + (size - 2 if win else 0)
        if points:
            self.db.ex("INSERT INTO match_points(user_id,points,created_at) VALUES(?,?,?)",
                       (uid, points, int(time.time())))
        quests = self._bump_quests(uid, {
            "play": 0 if surrendered else 1, "win": int(win),
            "defend_trump": counters.get("trump_defends", 0), "throw_in": counters.get("throw_ins", 0),
            "transfer": counters.get("transfers", 0), "win_no_take": int(win and took == 0),
            "win_multi": int(win and size >= 3), "catch": counters.get("catches", 0) if cheating else 0,
        })
        return {"quests": quests, "achievements": self._check_achievements(uid), "points": points}

    def tournament_won(self, uid: int, name: str, tid: int) -> list[dict]:
        self.stats(uid)
        self.db.ex("UPDATE user_stats SET tournament_wins=tournament_wins+1 WHERE user_id=?", (uid,))
        self.grant_title(uid, f"tournament:{tid}", "🏆 Чемпіон турніру")
        self.db.ex("INSERT OR IGNORE INTO inventory(user_id,item_id,created_at) VALUES(?,?,?)",
                   (uid, "back_champion", int(time.time())))
        self.db.ex("UPDATE users SET xp = xp + 300 WHERE id=?", (uid,))
        return self._check_achievements(uid)

    # ---------- рейтинг ----------
    def apply_elo(self, uid: int, opp_rating: int, score: float) -> tuple[int, int]:
        u = self.db.user(uid)
        r, games = int(u["rating"] or ELO_START), int(u["ranked_games"] or 0)
        d = elo_delta(r, opp_rating, score, games)
        self.db.ex("UPDATE users SET rating=?, ranked_games=ranked_games+1 WHERE id=?", (max(100, r + d), uid))
        return max(100, r + d), d

    # ---------- таблиці лідерів ----------
    def leaderboard(self, kind: str, scope_ids: list[int] | None, me: int, limit: int = 50) -> dict:
        now = time.time()
        if kind == "rating":
            base = "SELECT id user_id, name, rating score FROM users WHERE banned=0 AND ranked_games>0"
            args: tuple = ()
        else:
            if kind == "week":
                since, until = int(now - 7 * 86400), int(now) + 1
            else:
                since, until = season_bounds(season_id(now))
            base = ("SELECT u.id user_id, u.name, SUM(p.points) score FROM match_points p JOIN users u ON u.id=p.user_id "
                    "WHERE u.banned=0 AND p.created_at>=? AND p.created_at<? GROUP BY u.id")
            args = (since, until)
        rows = self.db.q(f"SELECT * FROM ({base}) ORDER BY score DESC, user_id", args)
        if scope_ids is not None:
            allowed = set(scope_ids) | {me}
            rows = [r for r in rows if r["user_id"] in allowed]
        for i, r in enumerate(rows):
            r["place"] = i + 1
        mine = next((r for r in rows if r["user_id"] == me), None)
        return {"rows": rows[:limit], "me": mine}

    def season_top(self, sid: str, n: int = 10) -> list[dict]:
        a, b = season_bounds(sid)
        return self.db.q("SELECT user_id, SUM(points) score FROM match_points WHERE created_at>=? AND created_at<? "
                         "GROUP BY user_id ORDER BY score DESC, user_id LIMIT ?", (a, b, n))

    def award_finished_seasons(self, now: float | None = None) -> list[str]:
        """Після завершення місяця топ-10 сезону отримують сорочку й титул (один раз)."""
        cur = season_id(now)
        last = self.db.kv_get("season_awarded")
        prev_end = season_bounds(cur)[0] - 1
        prev = season_id(prev_end)
        if last and last >= prev:
            return []
        if not last:
            # перший запуск: позначаємо попередній сезон як уже оброблений, нагороджуємо з наступного
            self.db.kv_set("season_awarded", prev)
            return []
        awarded = []
        for row in self.season_top(prev):
            uid = row["user_id"]
            self.grant_title(uid, f"season:{prev}", f"⭐ Топ-10 сезону {prev}")
            self.db.ex("INSERT OR IGNORE INTO inventory(user_id,item_id,created_at) VALUES(?,?,?)",
                       (uid, "back_season", int(time.time())))
            awarded.append(str(uid))
        self.db.kv_set("season_awarded", prev)
        return awarded
