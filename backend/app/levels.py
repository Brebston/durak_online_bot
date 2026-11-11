"""Рівні гравців. Рівень L потребує 50·L·(L−1) досвіду: 2 → 100, 3 → 300, 5 → 1000, 10 → 4500."""
from __future__ import annotations

XP_WIN = 30
XP_DRAW = 15
XP_LOSS = 10
XP_PER_OPPONENT = 5
MAX_LEVEL = 100


def xp_for(level: int) -> int:
    return 50 * level * (level - 1)


def level_of(xp: int) -> int:
    lvl = 1
    while lvl < MAX_LEVEL and xp >= xp_for(lvl + 1):
        lvl += 1
    return lvl


def progress(xp: int) -> dict:
    lvl = level_of(xp)
    lo, hi = xp_for(lvl), xp_for(lvl + 1)
    return {"level": lvl, "xp": xp, "level_xp": xp - lo, "next_xp": hi - lo}


def match_xp(outcome: str, opponents: int, surrendered: bool) -> int:
    if surrendered:
        return 0
    base = {"win": XP_WIN, "draw": XP_DRAW, "loss": XP_LOSS}[outcome]
    return base + XP_PER_OPPONENT * max(0, opponents - 1)
