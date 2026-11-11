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
