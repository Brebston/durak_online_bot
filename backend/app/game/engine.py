"""Ігровий рушій «Дурака»: підкидний і перевідний, 2–4 гравці.

Сервер — єдине джерело правди. Клієнт отримує лише `view(pid)`:
власні карти, відкриту інформацію та список дозволених дій.
"""
from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from typing import Any

SUITS = ["S", "C", "D", "H"]  # ♠ ♣ ♦ ♥


class IllegalMove(Exception):
    pass


def rank_of(card: str) -> int:
    return int(card[:-1])


def suit_of(card: str) -> str:
    return card[-1]


@dataclass
class Rules:
    variant: str = "podkidnoy"      # podkidnoy | perevodnoy
    deck_size: int = 36             # 24 | 36 | 52
    hand_size: int = 6
    max_table: int = 6              # макс. карт у одному відбої
    first_bout_limit: int = 5       # ліміт першого відбою (0 = як max_table)
    throw_in: str = "all"           # all | neighbors
    first_move: str = "lowest_trump"  # lowest_trump | random
    turn_seconds: int = 30
    cheating: bool = False          # режим «Шулер»: можна мухлювати, суперники можуть спіймати

    _INT_FIELDS = ("deck_size", "hand_size", "max_table", "first_bout_limit", "turn_seconds")

    @classmethod
    def from_dict(cls, d: dict | None) -> Rules:
        r = cls()
        if not d:
            return r
        if not isinstance(d, dict):
            raise ValueError("rules")
        for k, v in d.items():
            if k.startswith("_") or not hasattr(r, k):
                continue
            # жорстка перевірка типів: клієнт не може підсунути рядок, float чи обʼєкт
            if k in cls._INT_FIELDS:
                if isinstance(v, bool) or not isinstance(v, int):
                    raise ValueError(k)
            elif k == "cheating":
                if not isinstance(v, bool):
                    raise ValueError(k)
            elif not isinstance(v, str):
                raise ValueError(k)
            setattr(r, k, v)
        r.validate()
        return r

    def validate(self) -> None:
        if self.variant not in ("podkidnoy", "perevodnoy"):
            raise ValueError("variant")
        if self.deck_size not in (24, 36, 52):
            raise ValueError("deck_size")
        if not 4 <= self.hand_size <= 8:
            raise ValueError("hand_size")
        if not 1 <= self.max_table <= 6:
            raise ValueError("max_table")
        if not 0 <= self.first_bout_limit <= 6:
            raise ValueError("first_bout_limit")
        if self.throw_in not in ("all", "neighbors"):
            raise ValueError("throw_in")
        if self.first_move not in ("lowest_trump", "random"):
            raise ValueError("first_move")
        if not 10 <= self.turn_seconds <= 120:
            raise ValueError("turn_seconds")

    def to_dict(self) -> dict:
        return asdict(self)


def make_deck(size: int) -> list[str]:
    low = {24: 9, 36: 6, 52: 2}[size]
    return [f"{r}{s}" for s in SUITS for r in range(low, 15)]


@dataclass
class Game:
    players: list[str]
    rules: Rules = field(default_factory=Rules)
    seed: int | None = None

    def __post_init__(self) -> None:
        n = len(self.players)
        if not 2 <= n <= 4:
            raise ValueError("2–4 гравці")
        if n * self.rules.hand_size > self.rules.deck_size:
            raise ValueError("Замало карт у колоді")
        self.rng = random.Random(self.seed) if self.seed is not None else random.SystemRandom()
        self.deck = make_deck(self.rules.deck_size)
        self.rng.shuffle(self.deck)
        # deck[0] — нижня карта (козир, відкрита), беремо з кінця
        self.trump_card = self.deck[0]
        self.trump = suit_of(self.trump_card)
        self.hands: dict[str, list[str]] = {p: [] for p in self.players}
        for _ in range(self.rules.hand_size):
            for p in self.players:
                self.hands[p].append(self.deck.pop())
        self.initial_deal = {p: list(h) for p, h in self.hands.items()}
        self.initial_deck = list(self.deck)
        self.table: list[list[str | None]] = []  # [[attack, defense|None], ...]
        self.discard: list[str] = []
        self.out: list[str] = []          # порядок виходу з гри
        self.known: dict[str, set[str]] = {p: set() for p in self.players}  # публічно відомі карти на руках
        self.passed: set[str] = set()
        self.taking = False
        self.bout = 1
        self.version = 0
        self.status = "playing"           # playing | finished
        self.loser: str | None = None
        self.draw = False
        self.surrendered: str | None = None
        # режим «Шулер» (приховано від гравців): хто що поклав і які карти — мухлювання
        self.owner: dict[str, str] = {}
        self.cheats: dict[str, str] = {}
        self.catch_fail: set[str] = set()
        self.last_bout: dict | None = None   # стіл у момент завершення відбою (для анімації)
        self.attacker = self._first_attacker()
        self.defender = self._next_active(self.attacker)

    # ---------- допоміжні ----------
    def idx(self, p: str) -> int:
        return self.players.index(p)

    def is_active(self, p: str) -> bool:
        return p not in self.out

    def _next_active(self, p: str) -> str:
        i = self.idx(p)
        n = len(self.players)
        for k in range(1, n + 1):
            q = self.players[(i + k) % n]
            if self.is_active(q):
                return q
        return p

    def _prev_active(self, p: str) -> str:
        i = self.idx(p)
        n = len(self.players)
        for k in range(1, n + 1):
            q = self.players[(i - k) % n]
            if self.is_active(q):
                return q
        return p

    def _first_attacker(self) -> str:
        if self.rules.first_move == "lowest_trump":
            best = None
            for p in self.players:
                for c in self.hands[p]:
                    if suit_of(c) == self.trump and (best is None or rank_of(c) < best[0]):
                        best = (rank_of(c), p)
            if best:
                return best[1]
        return self.rng.choice(self.players)

    def beats(self, attack: str, defense: str) -> bool:
        if suit_of(attack) == suit_of(defense):
            return rank_of(defense) > rank_of(attack)
        return suit_of(defense) == self.trump and suit_of(attack) != self.trump

    def table_ranks(self) -> set[int]:
        return {rank_of(c) for pair in self.table for c in pair if c}

    def unbeaten(self) -> list[int]:
        return [i for i, (a, d) in enumerate(self.table) if d is None]

    def bout_limit(self) -> int:
        if self.bout == 1 and self.rules.first_bout_limit:
            return min(self.rules.first_bout_limit, self.rules.max_table)
        return self.rules.max_table

    def attackers(self) -> list[str]:
        act = [p for p in self.players if self.is_active(p) and p != self.defender]
        if self.rules.throw_in == "neighbors":
            nb = {self._prev_active(self.defender), self._next_active(self.defender)}
            act = [p for p in act if p in nb]
        return act

    def _can_add_count(self) -> bool:
        return (len(self.table) < self.bout_limit()
                and len(self.unbeaten()) < len(self.hands[self.defender]))

    def _can_throw_any(self, p: str) -> bool:
        """Чи може гравець щось підкинути (у режимі «Шулер» — будь-яку карту)."""
        if self.rules.cheating:
            return (p != self.defender and self.is_active(p) and bool(self.table) and bool(self.hands[p])
                    and p in self.attackers() and self._can_add_count())
        return bool(self._throwable(p))

    def _throwable(self, p: str) -> list[str]:
        if p == self.defender or not self.is_active(p) or not self.table:
            return []
        if p not in self.attackers() or not self._can_add_count():
            return []
        ranks = self.table_ranks()
        return [c for c in self.hands[p] if rank_of(c) in ranks]

    # ---------- дозволені дії ----------
    def legal_actions(self, p: str) -> list[dict]:
        if self.status != "playing" or not self.is_active(p):
            return []
        acts: list[dict] = self._catch_actions(p)
        if p == self.defender:
            if not self.taking:
                for i in self.unbeaten():
                    a = self.table[i][0]
                    for c in self.hands[p]:
                        if self.beats(a, c):
                            acts.append({"type": "defend", "card": c, "target": i})
                        elif self.rules.cheating:
                            acts.append({"type": "defend", "card": c, "target": i, "cheat": True})
                if self._transfer_ok_base():
                    rank = rank_of(self.table[0][0])
                    for c in self.hands[p]:
                        if rank_of(c) == rank:
                            acts.append({"type": "transfer", "card": c})
                if self.unbeaten():
                    acts.append({"type": "take"})
            return acts
        if p not in self.attackers():
            return acts
        if not self.table:
            if p == self.attacker:
                acts += [{"type": "attack", "card": c} for c in self.hands[p]]
            return acts
        legal = self._throwable(p)
        acts += [{"type": "attack", "card": c} for c in legal]
        if self.rules.cheating and self._can_add_count():
            acts += [{"type": "attack", "card": c, "cheat": True} for c in self.hands[p] if c not in legal]
        if p not in self.passed and (self.taking or not self.unbeaten()):
            acts.append({"type": "pass"})
        return acts

    def _catch_actions(self, p: str) -> list[dict]:
        """«Спіймати» можна будь-яку чужу карту на столі (раз за відбій можна помилитися)."""
        if not self.rules.cheating or p in self.catch_fail or not self.is_active(p):
            return []
        return [{"type": "catch", "card": c} for pair in self.table for c in pair
                if c and self.owner.get(c) != p]

    def _transfer_ok_base(self) -> bool:
        if self.rules.variant != "perevodnoy" or self.taking or not self.table:
            return False
        if any(d is not None for _, d in self.table):
            return False
        r = rank_of(self.table[0][0])
        if any(rank_of(a) != r for a, _ in self.table):
            return False
        nxt = self._next_active(self.defender)
        if nxt == self.defender:
            return False
        n_after = len(self.table) + 1
        return n_after <= self.rules.max_table and len(self.hands[nxt]) >= n_after

    # ---------- застосування дії ----------
    def apply(self, p: str, action: dict) -> dict:
        if self.status != "playing":
            raise IllegalMove("Гру завершено")
        t = action.get("type")
        legal = self.legal_actions(p)
        key = {k: action.get(k) for k in ("type", "card", "target") if action.get(k) is not None}
        match = None
        for la in legal:
            base = {k: v for k, v in la.items() if k != "cheat"}
            if base == key:
                match = la
                break
        if match is None:
            raise IllegalMove("Недозволений хід")
        is_cheat = bool(match.get("cheat"))
        ev: dict[str, Any] = {"player": p, **key, "defender": self.defender}
        if t == "catch":
            return self._apply_catch(p, action["card"], ev)
        if t in ("attack", "defend", "transfer"):
            self.owner[action["card"]] = p
            if is_cheat:
                self.cheats[action["card"]] = p
        if t == "attack":
            self.hands[p].remove(action["card"])
            self.known[p].discard(action["card"])
            self.table.append([action["card"], None])
            self.passed.clear()
        elif t == "defend":
            self.hands[p].remove(action["card"])
            self.known[p].discard(action["card"])
            self.table[action["target"]][1] = action["card"]
            self.passed.clear()
        elif t == "transfer":
            self.hands[p].remove(action["card"])
            self.known[p].discard(action["card"])
            self.table.append([action["card"], None])
            self.attacker = p
            self.defender = self._next_active(p)
            self.passed.clear()
            ev["new_defender"] = self.defender
        elif t == "take":
            self.taking = True
            self.passed.clear()
        elif t == "pass":
            self.passed.add(p)
        self.version += 1
        ev["bout_end"] = self._maybe_end_bout()
        return ev

    def _apply_catch(self, p: str, card: str, ev: dict) -> dict:
        cheater = self.cheats.get(card)
        if not cheater:
            self.catch_fail.add(p)   # хибне звинувачення — до кінця відбою ловити не можна
            ev["caught"] = False
            self.version += 1
            ev["bout_end"] = None
            return ev
        # карта повертається мухлярові; якщо це була атака — знімаємо пару
        for i, (a, d) in enumerate(self.table):
            if d == card:
                self.table[i][1] = None
                break
            if a == card:
                self.table.pop(i)
                if d:
                    owner = self.owner.get(d, self.defender)
                    self.hands[owner].append(d)
                    self.owner.pop(d, None)
                    self.cheats.pop(d, None)
                break
        self.hands[cheater].append(card)
        self.known[cheater].add(card)
        self.cheats.pop(card, None)
        self.owner.pop(card, None)
        self.passed.clear()
        ev.update({"caught": True, "cheater": cheater})
        self.version += 1
        ev["bout_end"] = self._maybe_end_bout()
        return ev

    def _attackers_done(self) -> bool:
        for q in self.attackers():
            if q in self.passed:
                continue
            if not self.hands[q] or not self._can_throw_any(q):
                continue  # нічого підкинути — автоматично пас
            return False
        return True

    def _maybe_end_bout(self) -> str | None:
        if not self.table:
            return None
        if self.taking:
            if self._attackers_done():
                self._end_bout(took=True)
                return "take"
        elif not self.unbeaten() and self._attackers_done():
            self._end_bout(took=False)
            return "beaten"
        return None

    def _end_bout(self, took: bool) -> None:
        self.last_bout = {"table": [list(x) for x in self.table], "took": took, "n": self.bout,
                          "defender": self.defender}
        self.owner.clear()
        self.cheats.clear()      # невиявлене мухлювання «проходить»
        self.catch_fail.clear()
        cards = [c for pair in self.table for c in pair if c]
        if took:
            self.hands[self.defender].extend(cards)
            self.known[self.defender].update(cards)
        else:
            self.discard.extend(cards)
        self.table = []
        # добір: атакувальник, далі за годинниковою, захисник останнім
        order: list[str] = []
        q = self.attacker
        for _ in range(len(self.players)):
            if self.is_active(q) and q != self.defender and q not in order:
                order.append(q)
            q = self.players[(self.idx(q) + 1) % len(self.players)]
        order.append(self.defender)
        for q in order:
            while len(self.hands[q]) < self.rules.hand_size and self.deck:
                self.hands[q].append(self.deck.pop())
        old_def = self.defender
        if not self.deck:
            for q in self.players:
                if self.is_active(q) and not self.hands[q]:
                    self.out.append(q)
        active = [q for q in self.players if self.is_active(q)]
        self.taking = False
        self.passed.clear()
        self.bout += 1
        if len(active) <= 1:
            self.status = "finished"
            if active:
                self.loser = active[0]
            else:
                self.draw = True
            return
        if took:
            self.attacker = self._next_active(old_def)
        else:
            self.attacker = old_def if self.is_active(old_def) else self._next_active(old_def)
        self.defender = self._next_active(self.attacker)

    def surrender(self, p: str) -> None:
        if self.status != "playing" or not self.is_active(p):
            raise IllegalMove("Не можна здатися")
        self.status = "finished"
        self.loser = p
        self.surrendered = p
        self.version += 1

    # ---------- таймер ----------
    def awaited(self) -> list[str]:
        """Гравці, від яких зараз очікується дія."""
        if self.status != "playing":
            return []
        if not self.table:
            return [self.attacker]
        if self.unbeaten() and not self.taking:
            return [self.defender]
        return [q for q in self.attackers() if q not in self.passed and self._can_throw_any(q)]

    def timeout_action(self, p: str) -> dict | None:
        """Дія за замовчуванням, якщо гравець не встиг."""
        legal = self.legal_actions(p)
        if not legal:
            return None
        if p == self.defender:
            return {"type": "take"} if any(a["type"] == "take" for a in legal) else None
        if not self.table:
            card = min(self.hands[p], key=lambda c: (suit_of(c) == self.trump, rank_of(c)))
            return {"type": "attack", "card": card}
        if any(a["type"] == "pass" for a in legal):
            return {"type": "pass"}
        return None

    # ---------- представлення ----------
    def sort_hand(self, cards: list[str]) -> list[str]:
        return sorted(cards, key=lambda c: (suit_of(c) == self.trump, SUITS.index(suit_of(c)), rank_of(c)))

    def view(self, p: str | None) -> dict:
        """Те, що бачить гравець p (None — глядач/журнал): без чужих карт."""
        return {
            "version": self.version,
            "status": self.status,
            "rules": self.rules.to_dict(),
            "trump": self.trump,
            "trump_card": self.trump_card if self.deck else None,
            "trump_card_shown": self.trump_card,
            "deck_count": len(self.deck),
            "discard_count": len(self.discard),
            "discard": list(self.discard),
            "table": [list(x) for x in self.table],
            "last_bout": self.last_bout,
            "mine_on_table": sorted(c for c, o in self.owner.items() if o == p) if p else [],
            "bout": self.bout,
            "bout_limit": self.bout_limit(),
            "attacker": self.attacker,
            "defender": self.defender,
            "taking": self.taking,
            "players": [
                {
                    "id": q,
                    "cards": len(self.hands[q]),
                    "out": q in self.out,
                    "place": self.out.index(q) + 1 if q in self.out else None,
                    "passed": q in self.passed,
                    "known": sorted(self.known[q]),
                }
                for q in self.players
            ],
            "awaited": self.awaited(),
            "loser": self.loser,
            "draw": self.draw,
            "surrendered": self.surrendered,
            "me": p,
            "hand": self.sort_hand(self.hands[p]) if p in self.hands else [],
            "actions": self.legal_actions(p) if p in self.hands else [],
        }
