"""Магазин косметики за фішки: сорочки карт, столи, смайлики, заставки, анімації перемоги.

Усі дизайни оригінальні й малюються на клієнті (CSS/анімації) за id предмета.
Покупка — атомарний переказ фішок гравця на рахунок `shop` (ledger.transfer).
"""
from __future__ import annotations

import json
import time

from .db import DB
from .ledger import SHOP, Ledger, LedgerError, acc

SLOTS = ("back", "table", "intro", "victory")

CATALOG: list[dict] = [
    # ---- сорочки карт ----
    {"id": "back_classic", "type": "back", "name": "Класична", "price": 0},
    {"id": "back_navy", "type": "back", "name": "Морська", "price": 100},
    {"id": "back_carbon", "type": "back", "name": "Карбон", "price": 250},
    {"id": "back_emerald", "type": "back", "name": "Смарагдова решітка", "price": 150},
    {"id": "back_sunflower", "type": "back", "name": "Соняшники", "price": 350},
    {"id": "back_blackgold", "type": "back", "name": "Чорне золото", "price": 300},
    {"id": "back_neon", "type": "back", "name": "Неон", "price": 400},
    {"id": "back_vyshyvanka", "type": "back", "name": "Вишиванка", "price": 500},
    {"id": "back_galaxy", "type": "back", "name": "Галактика", "price": 600},
    {"id": "back_dragon", "type": "back", "name": "Луска дракона", "price": 800},
    # нагороди за рівень (не продаються)
    {"id": "back_bronze", "type": "back", "name": "Бронзова", "price": 0, "level": 5},
    {"id": "back_silver", "type": "back", "name": "Срібна", "price": 0, "level": 10},
    {"id": "back_gold", "type": "back", "name": "Золота", "price": 0, "level": 20},
    # ---- столи ----
    {"id": "table_green", "type": "table", "name": "Зелене сукно", "price": 0},
    {"id": "table_blue", "type": "table", "name": "Синє сукно", "price": 150},
    {"id": "table_burgundy", "type": "table", "name": "Бордо", "price": 150},
    {"id": "table_oak", "type": "table", "name": "Дубовий стіл", "price": 300},
    {"id": "table_sunset", "type": "table", "name": "Захід сонця", "price": 350},
    {"id": "table_night", "type": "table", "name": "Нічне місто", "price": 400},
    {"id": "table_marble", "type": "table", "name": "Мармур", "price": 500},
    {"id": "table_space", "type": "table", "name": "Космос", "price": 700},
    # ---- смайлики ----
    {"id": "emoji_basic", "type": "emoji", "name": "Базові", "price": 0,
     "emojis": ["👍", "😂", "😡", "🤔", "😎", "😭", "👏", "🙈"]},
    {"id": "emoji_cards", "type": "emoji", "name": "Картярські", "price": 200,
     "emojis": ["🃏", "♠️", "♥️", "🔥", "💀", "🤡", "🎯", "🥶"]},
    {"id": "emoji_animals", "type": "emoji", "name": "Звірята", "price": 250,
     "emojis": ["🐸", "🦊", "🐻", "🐷", "🐔", "🐍", "🦁", "🐢"]},
    {"id": "emoji_kozak", "type": "emoji", "name": "Козацькі", "price": 300,
     "emojis": ["🇺🇦", "🌻", "⚔️", "🏆", "💪", "🥟", "👑", "🐎"]},
    {"id": "emoji_troll", "type": "emoji", "name": "Тролінг", "price": 400,
     "emojis": ["🥱", "💤", "🫠", "🤌", "🫵", "😈", "🙃", "🧂"]},
    # ---- заставки (при запуску) ----
    {"id": "intro_classic", "type": "intro", "name": "Класична", "price": 0},
    {"id": "intro_fan", "type": "intro", "name": "Віяло карт", "price": 200},
    {"id": "intro_lightning", "type": "intro", "name": "Блискавка", "price": 300},
    {"id": "intro_ace", "type": "intro", "name": "Золотий туз", "price": 500},
    # ---- анімація перемоги ----
    {"id": "victory_stars", "type": "victory", "name": "Зірочки", "price": 0},
    {"id": "victory_confetti", "type": "victory", "name": "Конфеті", "price": 200},
    {"id": "victory_fireworks", "type": "victory", "name": "Феєрверк", "price": 400},
    {"id": "victory_goldrain", "type": "victory", "name": "Золотий дощ", "price": 500},
    {"id": "victory_crown", "type": "victory", "name": "Корона", "price": 700},
]
BY_ID = {i["id"]: i for i in CATALOG}
DEFAULTS = {"back": "back_classic", "table": "table_green", "intro": "intro_classic", "victory": "victory_stars"}


class ShopError(Exception):
    """Повідомлення-ключ для перекладу + параметри ({0}, {1}…)."""

    def __init__(self, key: str, *args):
        super().__init__(key.format(*args) if args else key)
        self.key, self.args_ = key, args


class Shop:
    def __init__(self, db: DB, ledger: Ledger):
        self.db = db
        self.ledger = ledger

    def owned(self, uid: int) -> set[str]:
        from .levels import level_of

        u = self.db.user(uid)
        lvl = level_of(int(u.get("xp") or 0)) if u else 1
        free = {i["id"] for i in CATALOG if i["price"] == 0 and lvl >= i.get("level", 0)}
        rows = self.db.q("SELECT item_id FROM inventory WHERE user_id=?", (uid,))
        return free | {r["item_id"] for r in rows}

    def equipped(self, uid: int) -> dict:
        u = self.db.user(uid)
        eq = dict(DEFAULTS)
        if u:
            try:
                eq.update({k: v for k, v in json.loads(u.get("cosmetics") or "{}").items() if k in SLOTS})
            except json.JSONDecodeError:
                pass
        return eq

    def emojis(self, uid: int) -> list[str]:
        own = self.owned(uid)
        return [e for i in CATALOG if i["type"] == "emoji" and i["id"] in own for e in i["emojis"]]

    def buy(self, uid: int, item_id: str) -> None:
        item = BY_ID.get(item_id)
        if not item:
            raise ShopError("Предмет не знайдено")
        if item_id in self.owned(uid):
            raise ShopError("Вже придбано")
        if item.get("level"):
            raise ShopError("Відкривається на рівні {0}", item["level"])
        try:
            ok = self.ledger.transfer(acc(uid), SHOP, item["price"], "shop_purchase", ref=item_id,
                                      reason=item["name"], idem=f"shop:{uid}:{item_id}")
        except LedgerError as e:
            raise ShopError(str(e))
        if not ok:
            raise ShopError("Вже придбано")
        self.db.ex("INSERT OR IGNORE INTO inventory(user_id,item_id,created_at) VALUES(?,?,?)",
                   (uid, item_id, int(time.time())))
        if item["type"] in SLOTS:
            self.equip(uid, item_id)

    def equip(self, uid: int, item_id: str) -> dict:
        item = BY_ID.get(item_id)
        if not item or item["type"] not in SLOTS:
            raise ShopError("Цей предмет не можна встановити")
        if item_id not in self.owned(uid):
            raise ShopError("Спершу придбайте предмет")
        eq = self.equipped(uid)
        eq[item["type"]] = item_id
        self.db.ex("UPDATE users SET cosmetics=? WHERE id=?", (json.dumps(eq), uid))
        return eq
