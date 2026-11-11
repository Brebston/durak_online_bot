import random

import pytest

from app.game.bot_ai import choose_action
from app.game.engine import Game, IllegalMove, Rules, make_deck


def play_out(g: Game, levels: dict, rng: random.Random, max_steps=5000):
    steps = 0
    total = g.rules.deck_size
    while g.status == "playing":
        steps += 1
        assert steps < max_steps, "гра не завершилась"
        moved = False
        for p in g.players:
            v = g.view(p)
            # бот бачить лише свої карти
            assert set(v["hand"]) == set(g.hands[p])
            a = choose_action(v, levels[p], rng)
            if a:
                g.apply(p, a)
                moved = True
                break
        assert moved, "ніхто не може ходити"
        cards = len(g.deck) + len(g.discard) + sum(len(h) for h in g.hands.values()) \
            + sum(1 for pair in g.table for c in pair if c)
        assert cards == total
        assert len(g.table) <= g.rules.max_table
    return steps


@pytest.mark.parametrize("variant", ["podkidnoy", "perevodnoy"])
@pytest.mark.parametrize("n", [2, 3, 4])
@pytest.mark.parametrize("deck", [36, 52])
def test_random_games_terminate(variant, n, deck):
    rng = random.Random(1)
    for seed in range(40):
        players = [f"p{i}" for i in range(n)]
        g = Game(players, Rules(variant=variant, deck_size=deck), seed=seed)
        levels = ["easy", "medium", "hard"] if seed < 4 else ["easy", "medium"]
        lv = {p: rng.choice(levels) for p in players}
        play_out(g, lv, rng)
        assert g.status == "finished"
        assert g.draw or g.loser in players
        if not g.draw:
            assert g.loser not in g.out


def test_illegal_moves_rejected():
    g = Game(["a", "b"], Rules(), seed=3)
    other = g.defender
    with pytest.raises(IllegalMove):
        g.apply(other, {"type": "attack", "card": g.hands[other][0]})
    with pytest.raises(IllegalMove):
        g.apply(g.attacker, {"type": "attack", "card": "99X"})
    # карта суперника
    with pytest.raises(IllegalMove):
        g.apply(g.attacker, {"type": "attack", "card": g.hands[other][0]})


def test_view_hides_other_hands():
    g = Game(["a", "b", "c"], Rules(), seed=5)
    v = g.view("a")
    assert v["hand"] == g.sort_hand(g.hands["a"])
    s = str({k: v[k] for k in v if k != "hand" and k != "actions"})
    for c in g.hands["b"]:
        assert f"'{c}'" not in s or c in v["discard"]


def test_first_bout_limit_and_take():
    g = Game(["a", "b"], Rules(), seed=11)
    att, de = g.attacker, g.defender
    g.apply(att, {"type": "attack", "card": g.hands[att][0]})
    g.apply(de, {"type": "take"})
    # після «беру» атакувальник може підкинути або пасувати
    acts = g.legal_actions(att)
    assert {"type": "pass"} in acts
    n_before = len(g.hands[de])
    g.apply(att, {"type": "pass"})
    assert g.bout == 2
    assert len(g.hands[de]) == n_before + 1
    assert g.attacker == att  # у грі на двох захисник, що взяв, пропускає хід


def test_transfer():
    for seed in range(200):
        g = Game(["a", "b", "c"], Rules(variant="perevodnoy"), seed=seed)
        att, de = g.attacker, g.defender
        for c in g.hands[att]:
            if any(rank_of(c) == rank_of(d) for d in g.hands[de]):
                g.apply(att, {"type": "attack", "card": c})
                t = next(a for a in g.legal_actions(de) if a["type"] == "transfer")
                g.apply(de, t)
                assert g.defender != de and g.attacker == de
                assert len(g.table) == 2
                return
    pytest.fail("не знайшли розклад для переводу")


def rank_of(c):
    return int(c[:-1])


def test_deck():
    assert len(make_deck(36)) == 36 and len(set(make_deck(52))) == 52


# ---------------- режим «Шулер» ----------------
from app.game.bot_ai import catch_decision  # noqa: E402


@pytest.mark.parametrize("n", [2, 3, 4])
def test_cheating_games_terminate(n):
    rng = random.Random(7)
    caught = cheated = 0
    for seed in range(40):
        players = [f"p{i}" for i in range(n)]
        g = Game(players, Rules(cheating=True, variant=rng.choice(["podkidnoy", "perevodnoy"])), seed=seed)
        seen = {p: set() for p in players}
        steps = 0
        while g.status == "playing":
            steps += 1
            assert steps < 6000
            moved = False
            for p in players:
                c = catch_decision(g.view(p), "medium", rng, seen[p])
                if c:
                    ev = g.apply(p, c)
                    caught += ev["caught"]
                    moved = True
                    break
            if not moved:
                for p in players:
                    a = choose_action(g.view(p), rng.choice(["easy", "medium"]), rng)
                    if a:
                        cheated += bool(a.get("cheat"))
                        g.apply(p, a)
                        moved = True
                        break
            assert moved
            total = len(g.deck) + len(g.discard) + sum(len(h) for h in g.hands.values()) \
                + sum(1 for pair in g.table for c in pair if c)
            assert total == 36
        assert g.draw or g.loser in players
    print('cheated', cheated, 'caught', caught)
    assert cheated > 0 and caught > 0


def test_catch_returns_cheat_card_and_false_accusation():
    for seed in range(300):
        g = Game(["a", "b", "c"], Rules(cheating=True), seed=seed)
        att, de = g.attacker, g.defender
        other = next(p for p in g.players if p not in (att, de))
        g.apply(att, {"type": "attack", "card": g.hands[att][0]})
        cheat = next((x for x in g.legal_actions(de) if x.get("cheat")), None)
        honest = next((x for x in g.legal_actions(de) if x["type"] == "defend" and not x.get("cheat")), None)
        if not cheat:
            continue
        card = cheat["card"]
        g.apply(de, {"type": "defend", "card": card, "target": 0})
        v = g.view(other)  # мухлювання не видно в даних інших гравців
        assert "cheats" not in v and "owner" not in v and card not in v["mine_on_table"]
        # хибне звинувачення: атакувальна карта чесна
        ev = g.apply(other, {"type": "catch", "card": g.table[0][0]})
        assert ev["caught"] is False
        assert not any(x["type"] == "catch" for x in g.legal_actions(other))
        ev = g.apply(att, {"type": "catch", "card": card})
        assert ev["caught"] and card in g.hands[de] and g.table[0][1] is None
        _ = honest
        return
    pytest.fail("не знайшли розклад")


def test_rules_reject_bad_types():
    for bad in ({"hand_size": "6"}, {"max_table": 50}, {"turn_seconds": 1.5}, {"cheating": "yes"}, {"variant": 1}):
        with pytest.raises(ValueError):
            Rules.from_dict(bad)
