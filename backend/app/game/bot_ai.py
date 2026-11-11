"""Боти. Отримують ЛИШЕ view(pid) — ті самі дані, що й людина на своєму місці:
власні карти, стіл, козир, кількість карт у суперників і публічно відомі карти
(ті, що суперник забрав зі столу на очах у всіх). Доступу до об'єкта Game немає.
"""
from __future__ import annotations

import random

from .engine import make_deck, rank_of, suit_of

LEVELS = ("easy", "medium", "hard")


def _value(card: str, trump: str) -> int:
    return rank_of(card) + (100 if suit_of(card) == trump else 0)


CHEAT_RATE = {"easy": 0.3, "medium": 0.22, "hard": 0.15}
CATCH_RATE = {"easy": 0.35, "medium": 0.6, "hard": 0.85}


def choose_action(view: dict, level: str = "medium", rng: random.Random | None = None) -> dict | None:
    rng = rng or random.Random()
    all_actions = view["actions"]
    # чесні ходи окремо від мухлювання й «спіймати»
    actions = [a for a in all_actions if not a.get("cheat") and a["type"] != "catch"]
    if not actions:
        return None
    if level == "easy":
        act = _easy(view, actions, rng)
    elif level == "hard":
        act = _monte_carlo(view, actions, rng)
    else:
        act = _smart(view, actions, rng, hard=False)
    if view["rules"].get("cheating"):
        act = _maybe_cheat(view, all_actions, act, level, rng)
    return act


def _maybe_cheat(view: dict, actions: list[dict], honest: dict, level: str, rng: random.Random) -> dict:
    """У режимі «Шулер» бот інколи мухлює — як людина: коли інакше довелося б брати карти,
    або підкидає «не ту» дрібну карту, коли в захисника мало карт."""
    trump = view["trump"]
    rate = CHEAT_RATE.get(level, 0.2)
    cheats = [a for a in actions if a.get("cheat")]
    if not cheats or rng.random() > rate:
        return honest
    if honest["type"] == "take":
        defends = [a for a in cheats if a["type"] == "defend"]
        # найправдоподібніше: та сама масть, але молодша (або дрібна некозирна)
        def plausibility(a):
            att = view["table"][a["target"]][0]
            same = suit_of(a["card"]) == suit_of(att)
            return (not same, suit_of(a["card"]) == trump, rank_of(a["card"]))
        if defends:
            return min(defends, key=plausibility)
    if honest["type"] == "pass" and not view["taking"]:
        defender = next(p for p in view["players"] if p["id"] == view["defender"])
        throws = [a for a in cheats if a["type"] == "attack" and suit_of(a["card"]) != trump and rank_of(a["card"]) <= 10]
        if throws and defender["cards"] <= 3:
            return min(throws, key=lambda a: rank_of(a["card"]))
    return honest


def suspicious_cards(view: dict) -> list[str]:
    """Карти на столі, які видно що покладені не за правилами (бачить кожен уважний гравець)."""
    trump = view["trump"]
    mine = set(view.get("mine_on_table") or [])
    out = []
    seen_ranks: set[int] = set()
    for i, (a, d) in enumerate(view["table"]):
        if i > 0 and rank_of(a) not in seen_ranks and a not in mine:
            out.append(a)                      # підкинули ранг, якого не було на столі
        seen_ranks.add(rank_of(a))
        if d:
            if not _beats(a, d, trump) and d not in mine:
                out.append(d)                  # «побили» карту, яка її не бʼє
            seen_ranks.add(rank_of(d))
    return out


def catch_decision(view: dict, level: str, rng: random.Random, already: set[str]) -> dict | None:
    """Чи помітив бот мухлювання. Кожну підозрілу карту бот «оцінює» один раз (already)."""
    if not view["rules"].get("cheating"):
        return None
    catchable = {a["card"] for a in view["actions"] if a["type"] == "catch"}
    for c in suspicious_cards(view):
        if c in already or c not in catchable:
            continue
        already.add(c)
        if rng.random() < CATCH_RATE.get(level, 0.5):
            return {"type": "catch", "card": c}
    return None


# ---------- сильний бот: Монте-Карло по невідомих картах ----------
def _determinize(view: dict, rng: random.Random):
    """Будує правдоподібну гру з точки зору бота: невідомі карти суперників
    і колоди розкладаються випадково. Справжні чужі карти бот не знає."""
    from .engine import Game, Rules

    me = view["me"]
    trump_card = view["trump_card_shown"]
    unseen = list(_unseen(view))
    hands: dict[str, list[str]] = {}
    for p in view["players"]:
        if p["id"] == me:
            hands[me] = list(view["hand"])
        else:
            hands[p["id"]] = list(p["known"])
    known_all = {c for p in view["players"] if p["id"] != me for c in p["known"]}
    pool = [c for c in unseen if c not in known_all]
    deck_n = view["deck_count"]
    if deck_n and trump_card in pool:
        pool.remove(trump_card)
    rng.shuffle(pool)
    for p in view["players"]:
        if p["id"] == me:
            continue
        need = p["cards"] - len(hands[p["id"]])
        hands[p["id"]] += [pool.pop() for _ in range(max(0, need))]
    deck = ([trump_card] if deck_n else []) + pool[: max(0, deck_n - 1)]

    g = Game.__new__(Game)
    g.players = [p["id"] for p in view["players"]]
    g.rules = Rules.from_dict(view["rules"])
    g.seed = None
    g.rng = rng
    g.deck = deck
    g.trump_card = trump_card
    g.trump = view["trump"]
    g.hands = hands
    g.table = [list(x) for x in view["table"]]
    g.discard = list(view["discard"])
    g.out = [p["id"] for p in sorted(view["players"], key=lambda p: p["place"] or 0) if p["out"]]
    g.known = {p["id"]: set(p["known"]) for p in view["players"]}
    g.passed = {p["id"] for p in view["players"] if p["passed"]}
    g.taking = view["taking"]
    g.bout = view["bout"]
    g.version = 0
    g.status = "playing"
    g.loser = None
    g.draw = False
    g.surrendered = None
    g.owner, g.cheats, g.catch_fail, g.last_bout = {}, {}, set(), None
    g.rules.cheating = False   # у симуляціях — лише чесна гра
    g.attacker = view["attacker"]
    g.defender = view["defender"]
    return g


def _fast_policy(g, p: str, actions: list[dict]) -> dict:
    """Швидка евристика для симуляцій усередині уявного світу бота."""
    t = g.trump
    val = lambda c: _value(c, t)  # noqa: E731
    if p == g.defender:
        tr = [a for a in actions if a["type"] == "transfer" and suit_of(a["card"]) != t]
        if tr:
            return tr[0]
        dfs = [a for a in actions if a["type"] == "defend"]
        if dfs:
            return min(dfs, key=lambda a: val(a["card"]))
        return actions[-1]
    atk = [a for a in actions if a["type"] == "attack"]
    if not g.table:
        return min(atk, key=lambda a: val(a["card"]))
    cheap = [a for a in atk if suit_of(a["card"]) != t and rank_of(a["card"]) <= 11] if g.deck else atk
    if cheap:
        return min(cheap, key=lambda a: val(a["card"]))
    for a in actions:
        if a["type"] == "pass":
            return a
    return actions[0]


def _rollout(g, me: str, rng: random.Random, max_steps: int = 400) -> float:
    steps = 0
    while g.status == "playing" and steps < max_steps:
        steps += 1
        waiting = g.awaited() or g.players
        moved = False
        for p in waiting:
            acts = g.legal_actions(p)
            if acts:
                g.apply(p, _fast_policy(g, p, acts))
                moved = True
                break
        if not moved:
            break
    if g.status != "finished":
        return 0.5
    if g.draw:
        return 0.6
    return 0.0 if g.loser == me else 1.0


def _candidates(view: dict, actions: list[dict], rng: random.Random, limit: int = 7) -> list[dict]:
    trump = view["trump"]
    base = _smart(view, actions, rng, hard=False)
    cands = [base]
    rest = sorted(
        (a for a in actions if a != base),
        key=lambda a: (a["type"] in ("take", "pass"), _value(a["card"], trump) if "card" in a else 0),
    )
    special = [a for a in rest if a["type"] in ("take", "pass", "transfer")]
    for a in special + rest:
        if a not in cands:
            cands.append(a)
        if len(cands) >= limit:
            break
    return cands


def _monte_carlo(view: dict, actions: list[dict], rng: random.Random, samples: int = 10) -> dict:
    cands = _candidates(view, actions, rng)
    if len(cands) == 1:
        return cands[0]
    me = view["me"]
    scores = [0.0] * len(cands)
    for _ in range(samples):
        world = _determinize(view, rng)
        snapshot = _snapshot(world)
        for i, a in enumerate(cands):
            g = _restore(world, snapshot)
            try:
                g.apply(me, a)
            except Exception:
                scores[i] -= 1
                continue
            scores[i] += _rollout(g, me, rng)
    best = max(range(len(cands)), key=lambda i: (scores[i], i == 0))
    return cands[best]


def _snapshot(g):
    return (
        {p: list(h) for p, h in g.hands.items()}, list(g.deck), [list(x) for x in g.table],
        list(g.discard), list(g.out), {p: set(k) for p, k in g.known.items()}, set(g.passed),
        g.taking, g.bout, g.attacker, g.defender,
    )


def _restore(g, s):
    import copy
    h = copy.copy(g)
    (hands, deck, table, discard, out, known, passed, taking, bout, att, de) = s
    h.hands = {p: list(x) for p, x in hands.items()}
    h.deck = list(deck)
    h.table = [list(x) for x in table]
    h.discard = list(discard)
    h.out = list(out)
    h.known = {p: set(k) for p, k in known.items()}
    h.passed = set(passed)
    h.taking, h.bout, h.attacker, h.defender = taking, bout, att, de
    h.status, h.loser, h.draw, h.version = "playing", None, False, 0
    h.owner, h.cheats, h.catch_fail = {}, {}, set()
    return h


def _easy(view: dict, actions: list[dict], rng: random.Random) -> dict:
    trump = view["trump"]
    defends = [a for a in actions if a["type"] == "defend"]
    if defends and rng.random() < 0.8:
        return min(defends, key=lambda a: _value(a["card"], trump))
    attacks = [a for a in actions if a["type"] == "attack"]
    if attacks and not view["table"]:
        return rng.choice(attacks)
    if attacks and rng.random() < 0.4:
        return rng.choice(attacks)
    for t in ("pass", "take"):
        for a in actions:
            if a["type"] == t:
                return a
    return rng.choice(actions)


def _unseen(view: dict) -> set[str]:
    """Карти, місцезнаходження яких боту невідоме (колода + чужі руки)."""
    allc = set(make_deck(view["rules"]["deck_size"]))
    seen = set(view["hand"]) | set(view["discard"])
    seen |= {c for pair in view["table"] for c in pair if c}
    return allc - seen


def _smart(view: dict, actions: list[dict], rng: random.Random, hard: bool) -> dict:
    trump = view["trump"]
    me = view["me"]
    hand = view["hand"]
    deck = view["deck_count"]
    endgame = deck == 0
    by_type: dict[str, list[dict]] = {}
    for a in actions:
        by_type.setdefault(a["type"], []).append(a)

    # ---------- захист ----------
    if me == view["defender"] and not view["taking"]:
        # перевід, якщо це дешево (не козир) і не віддаємо сильну карту
        for a in by_type.get("transfer", []):
            if suit_of(a["card"]) != trump or (endgame and hard):
                return a
        plan = _plan_defense(view)
        if plan is not None:
            trumps_used = sum(1 for c in plan.values() if suit_of(c) == trump)
            cards_on_table = len(view["table"]) + len([1 for _, d in view["table"] if d])
            # на початку гри не витрачаємо старші козирі заради 1-2 дрібних карт
            if not endgame and trumps_used and deck > 10 and cards_on_table <= 2:
                high_trump = any(suit_of(c) == trump and rank_of(c) >= 12 for c in plan.values())
                if high_trump:
                    return {"type": "take"}
            i = min(plan)
            return {"type": "defend", "card": plan[i], "target": i}
        if "take" in by_type:
            return by_type["take"][0]
        return actions[0]

    # ---------- атака / підкидання ----------
    attacks = by_type.get("attack", [])
    if not view["table"]:
        # хід: найменша не-козирна, бажано пара однакових рангів
        counts: dict[int, int] = {}
        for c in hand:
            counts[rank_of(c)] = counts.get(rank_of(c), 0) + 1
        def lead_key(a: dict) -> tuple:
            c = a["card"]
            return (suit_of(c) == trump, -min(counts[rank_of(c)], 2) if hard else 0, rank_of(c))
        if hard and endgame:
            defender = view["defender"]
            known = next(p["known"] for p in view["players"] if p["id"] == defender)
            # у кінці гри атакуємо картами, які захисник не зможе побити відомими картами
            def unbeatable(c: str) -> bool:
                return not any(_beats(c, k, trump) for k in known)
            good = [a for a in attacks if unbeatable(a["card"])]
            if good:
                return min(good, key=lead_key)
        return min(attacks, key=lead_key)

    # підкидання
    defender = next(p for p in view["players"] if p["id"] == view["defender"])
    candidates = []
    for a in attacks:
        c = a["card"]
        if suit_of(c) == trump and not endgame:
            continue
        if rank_of(c) >= 13 and not endgame and not view["taking"]:
            continue
        candidates.append(a)
    if view["taking"]:
        # захисник бере — підкидаємо дрібні непотрібні карти
        cheap = [a for a in candidates if rank_of(a["card"]) <= 10 or endgame]
        if cheap:
            return min(cheap, key=lambda a: _value(a["card"], trump))
    elif candidates and (endgame or defender["cards"] <= 3 or rng.random() < 0.6):
        return min(candidates, key=lambda a: _value(a["card"], trump))
    if "pass" in by_type:
        return by_type["pass"][0]
    return min(attacks, key=lambda a: _value(a["card"], trump)) if attacks else actions[0]


def _beats(attack: str, defense: str, trump: str) -> bool:
    if suit_of(attack) == suit_of(defense):
        return rank_of(defense) > rank_of(attack)
    return suit_of(defense) == trump and suit_of(attack) != trump


def _plan_defense(view: dict) -> dict[int, str] | None:
    """Жадібно підбирає найдешевші карти, щоб побити всі неприкриті карти."""
    trump = view["trump"]
    hand = list(view["hand"])
    targets = [i for i, (a, d) in enumerate(view["table"]) if d is None]
    targets.sort(key=lambda i: -_value(view["table"][i][0], trump))  # спершу найсильніші
    plan: dict[int, str] = {}
    for i in targets:
        a = view["table"][i][0]
        opts = [c for c in hand if _beats(a, c, trump)]
        if not opts:
            return None
        c = min(opts, key=lambda c: _value(c, trump))
        plan[i] = c
        hand.remove(c)
    return plan
