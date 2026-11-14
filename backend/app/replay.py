"""Відтворення завершеного матчу з журналу подій.

Правила тут НЕ дублюються: збережені ходи перегравáються справжнім рушієм
(`game.engine.Game`), а кадром служить `Game.view(None)` — той самий
«журнальний» вигляд без чужих карт, який рушій уже віддає глядачеві.

Початкова роздача береться із зашифрованого `matches.deal_enc`, решта стану
(склад, правила, перший атакувальник) — з події `start`. Добори з колоди в
журнал не пишуться, тому рушій відтворює їх сам — для цього й потрібна
точна початкова колода.
"""
from __future__ import annotations

from typing import Any

from .game.engine import Game, IllegalMove, Rules, suit_of

# Події, що змінюють стан гри. `timeout` — це теж хід: таймер застосовує
# його через той самий `Game.apply` (див. rooms._timer_loop).
MOVE_TYPES = ("move", "timeout")
SURRENDER_TYPES = ("surrender", "afk_surrender")
ACTION_KEYS = ("type", "card", "target")


class ReplayError(Exception):
    """Журналу не вистачає, щоб відтворити матч."""


def _restore(start: dict, deal: dict) -> Game:
    """Рушій у стані перед першим ходом."""
    pids = [p["pid"] for p in (start.get("players") or []) if p.get("pid")]
    if len(pids) < 2:
        raise ReplayError("У журналі немає складу гравців")
    hands = deal.get("hands") or {}
    if set(hands) != set(pids):
        raise ReplayError("Роздача не збігається зі складом гравців")
    trump_card = deal.get("trump_card") or start.get("trump")
    if not trump_card:
        raise ReplayError("У журналі немає козирної карти")

    g = Game(players=pids, rules=Rules.from_dict(start.get("rules")))
    # Рушій у конструкторі тасує свою колоду — підміняємо її збереженою роздачею.
    g.hands = {p: list(hands[p]) for p in pids}
    g.deck = list(deal.get("deck") or [])
    g.trump_card = trump_card
    g.trump = suit_of(trump_card)
    g.initial_deal = {p: list(h) for p, h in g.hands.items()}
    g.initial_deck = list(g.deck)

    attacker = start.get("attacker")
    if attacker not in pids:
        raise ReplayError("У журналі немає першого атакувальника")
    g.attacker = attacker
    g.defender = g._next_active(attacker)  # noqa: SLF001 — свій пакет, іншого шляху немає
    return g


def _frame(g: Game, label: str, *, actor: str | None = None,
           action: dict | None = None, reveal: bool = False) -> dict[str, Any]:
    """Кадр реплею. `view(None)` ніколи не містить чужих карт."""
    frame: dict[str, Any] = {"label": label, "actor": actor, "action": action, "view": g.view(None)}
    if reveal:
        frame["hands"] = {p: g.sort_hand(g.hands[p]) for p in g.players}
    return frame


def build_replay(events: list[dict], deal: dict | None, *, reveal: bool = False) -> dict[str, Any]:
    """Кадри матчу з журналу подій.

    `reveal` додає в кожен кадр руки всіх гравців; без нього реплей показує
    рівно те саме, що гравець бачив за столом.
    """
    start = next((e for e in events if e.get("type") == "start"), None)
    if not start:
        raise ReplayError("Для цього матчу немає журналу подій")
    if not deal:
        raise ReplayError("Для цього матчу не збереглася роздача")

    g = _restore(start.get("data") or {}, deal)
    frames = [_frame(g, "start", reveal=reveal)]
    chat: list[dict] = []
    truncated_at: int | None = None

    for e in events:
        etype, actor = e.get("type"), e.get("actor")
        data = e.get("data") or {}
        if etype == "chat":
            # прапорець бота лишається прихованим так само, як за столом
            chat.append({"seq": e.get("seq"), "actor": actor,
                         "msg": {k: v for k, v in data.items() if k != "bot"}})
        elif etype in MOVE_TYPES:
            action = {k: data[k] for k in ACTION_KEYS if data.get(k) is not None}
            if not action.get("type") or not actor:
                continue
            try:
                g.apply(actor, action)
            except (IllegalMove, KeyError, ValueError, IndexError):
                truncated_at = e.get("seq")
                break
            frames.append(_frame(g, etype, actor=actor, action=action, reveal=reveal))
        elif etype in SURRENDER_TYPES:
            try:
                g.surrender(actor)
            except (IllegalMove, KeyError):
                truncated_at = e.get("seq")
                break
            frames.append(_frame(g, etype, actor=actor, reveal=reveal))

    return {"frames": frames, "chat": chat, "truncated_at": truncated_at}
