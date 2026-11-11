"""«Характер» ботів: реалістичні імена, оформлення та реакції смайликами.

Боти поводяться як звичайні гравці: мають власну сорочку карт і набір смайликів,
інколи реагують на події за столом. Рішення в грі — як і раніше, лише на основі
відкритої інформації (див. game/bot_ai.py).
"""
from __future__ import annotations

import random

from .shop import CATALOG

_M = ["Андрій", "Олександр", "Дмитро", "Сергій", "Максим", "Іван", "Віталій", "Олег", "Тарас", "Богдан", "Назар",
      "Роман", "Артем", "Владислав", "Юрій", "Ігор", "Микола", "Павло", "Денис", "Євген", "Василь", "Ярослав"]
_F = ["Олена", "Ірина", "Наталія", "Марина", "Юлія", "Катерина", "Анна", "Оксана", "Світлана", "Тетяна", "Вікторія",
      "Дарина", "Софія", "Христина", "Людмила", "Аліна"]
_M_LAT = ["Andrii", "Oleksandr", "Dima", "Serhii", "Max", "Ivan", "Vitalii", "Oleg", "Taras", "Bohdan", "Roman",
          "Artem", "Vlad", "Yurii", "Igor", "Pavlo", "Denys", "Zhenya", "Kolya", "Sasha"]
_F_LAT = ["Olena", "Iryna", "Natalia", "Marina", "Yulia", "Kate", "Anna", "Oksana", "Sveta", "Tanya", "Vika",
          "Daryna", "Sofia", "Kristina", "Alina"]
_SUR = ["Коваль", "Бондар", "Шевчук", "Мельник", "Ткачук", "Кравець", "Олійник", "Лисенко", "Бойко", "Гончар",
        "Савчук", "Руденко", "Марченко", "Поліщук", "Левченко", "Кузьмич"]
_SUR_LAT = ["Koval", "Bondar", "Shevchuk", "Melnyk", "Tkachuk", "Kravets", "Boyko", "Lysenko", "Savchuk", "Rudenko"]
_SHORT = {"Олександр": "Саша", "Дмитро": "Діма", "Сергій": "Сєрьожа", "Віталій": "Віталік", "Євген": "Женя",
          "Владислав": "Влад", "Катерина": "Катя", "Наталія": "Наташа", "Світлана": "Світа", "Вікторія": "Віка",
          "Микола": "Коля", "Ярослав": "Ярик", "Христина": "Христя"}
_CITIES = ["kyiv", "lviv", "odesa", "dnipro", "kharkiv", "ua", "pl", "krk", "wro"]
_EMOJI_TAIL = [" 🇺🇦", " ⚡", " 🔥", " 🌻", " 😎", " ♠️"]


def random_nick(rng: random.Random, taken: set[str]) -> str:
    """Імена, як у звичайних акаунтах Telegram: «Андрій Коваль», «Віка», «Olena K.», «dima_kyiv»."""
    for _ in range(60):
        female = rng.random() < 0.38
        first = rng.choice(_F if female else _M)
        lat = rng.choice(_F_LAT if female else _M_LAT)
        r = rng.random()
        if r < 0.25:
            nick = f"{first} {rng.choice(_SUR)}"
        elif r < 0.40:
            nick = _SHORT.get(first, first)
        elif r < 0.55:
            nick = f"{lat} {rng.choice(_SUR_LAT)[0]}."
        elif r < 0.68:
            nick = f"{lat.lower()}_{rng.choice(_CITIES)}"
        elif r < 0.80:
            nick = f"{lat.lower()}{rng.choice(['', '_', '.'])}{rng.choice([rng.randint(80, 99), rng.randint(2000, 2010), rng.randint(1, 30)])}"
        elif r < 0.90:
            nick = f"{lat} {rng.choice(_SUR_LAT)}"
        else:
            nick = first
        if rng.random() < 0.12:
            nick += rng.choice(_EMOJI_TAIL)
        if nick not in taken:
            return nick
    return f"{rng.choice(_M_LAT)}{rng.randint(100, 999)}"


_BACKS = [i["id"] for i in CATALOG if i["type"] == "back"]
_PACKS = {i["id"]: i["emojis"] for i in CATALOG if i["type"] == "emoji"}


def random_look(rng: random.Random) -> dict:
    """Оформлення бота: половина — стандартне, решта — «куплене»."""
    back = "back_classic" if rng.random() < 0.5 else rng.choice(_BACKS[1:])
    packs = ["emoji_basic"] + rng.sample([p for p in _PACKS if p != "emoji_basic"], k=rng.choice([0, 0, 1, 1, 2]))
    emojis = [e for p in packs for e in _PACKS[p]]
    # характер: як часто бот реагує (дехто мовчун, дехто емоційний)
    chatty = rng.choice([0.0, 0.15, 0.3, 0.3, 0.5])
    return {"back": back, "emojis": emojis, "chatty": chatty}


# Реакції за подіями: кандидати смайликів (беремо лише ті, що є в наборах бота)
REACTIONS = {
    "i_took": ["😭", "😡", "🙈", "🤔", "💀", "🥶", "🐷", "🫠"],
    "they_took": ["😂", "😎", "🤡", "👏", "🔥", "🐸", "🫵", "🙃"],
    "i_transferred": ["😎", "🔥", "😈", "🎯", "🤌"],
    "i_won": ["😎", "👏", "🏆", "🔥", "👑", "💪"],
    "i_lost": ["😭", "😡", "🤡", "💀", "🙈", "🫠"],
    "reply": ["😂", "👍", "🤔", "😎", "🙃", "🫵"],
}
TEXTS = {
    "i_won": ["gg", "гг", "ez 😎", "дякую за гру", "ну нарешті"],
    "i_lost": ["gg", "та ну...", "не пощастило", "реванш?", "капець"],
}


def pick_reaction(rng: random.Random, kind: str, emojis: list[str]) -> str | None:
    options = [e for e in REACTIONS.get(kind, []) if e in emojis]
    return rng.choice(options) if options else None
