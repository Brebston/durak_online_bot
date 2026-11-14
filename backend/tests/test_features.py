"""Прогрес, рейтинг, реванш, турніри, адмінські інструменти."""
import gzip
import json
import random
import time

import pytest
from fastapi.testclient import TestClient
from test_server import play_vs_bots, recv_until  # noqa: I001 — спершу змінні середовища з test_server

from app import main
from app.game.bot_ai import choose_action
from app.progress import Progress, season_bounds, season_id
from app.tournaments import simulate

ADMIN = {"Authorization": "dev 1"}


def H(uid):
    return {"Authorization": f"dev {uid}:Player{uid}"}


@pytest.fixture(scope="module")
def client():
    main.init_state()
    with TestClient(main.app) as c:
        main.S.rooms.rng.uniform = lambda a, b: 0.0
        main.S.rooms.speed = 0
        main.S.tournaments.speed = 0
        yield c


def test_daily_streak_and_quests(client):
    me = client.get("/api/me", headers=H(901)).json()
    assert me["daily"]["streak"] == 1 and me["daily"]["xp"] == 20
    assert client.get("/api/me", headers=H(901)).json()["daily"] is None   # двічі за день — не нараховуємо
    p = client.get("/api/progress", headers=H(901)).json()
    assert len(p["quests"]) == 3 and p["streak"]["days"] == 1
    assert {a["id"] for a in p["achievements"]} >= {"first_win", "first_transfer", "no_take_win"}


def test_streak_continues_and_awards_back():
    db = main.S.db
    db.upsert_user(950, "S", None)
    pr = Progress(db)
    now = time.time()
    for i in range(7):
        r = pr.daily_login(950, now - (6 - i) * 86400)
    assert r["streak"] == 7 and r["item"] == "back_streak"
    assert pr.daily_login(950, now + 3 * 86400)["streak"] == 1      # пропуск — серія з початку


def test_ranked_match_changes_rating(client):
    client.get("/api/me", headers=H(902))
    m = play_vs_bots(client, 902, "ranked")
    assert m["room"]["ranked"]
    p = client.get("/api/progress", headers=H(902)).json()
    assert p["stats"]["games"] == 1
    assert p["rating"]["games"] == 1
    if not m["result"]["draw"]:
        assert p["rating"]["value"] != 1000
    lb = client.get("/api/leaderboard?kind=rating", headers=H(902)).json()
    assert lb["me"]["user_id"] == 902
    assert client.get("/api/leaderboard?kind=week&scope=friends", headers=H(902)).status_code == 200
    assert client.get("/api/leaderboard?kind=season", headers=H(902)).json()["season"] == season_id()
    prof = client.get("/api/profile/902", headers=H(901)).json()
    assert prof["stats"]["games"] == 1 and "rating" in prof


def test_rematch_one_button(client):
    uid = 903
    rng = random.Random(3)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"auth": f"dev {uid}:P{uid}"}))
        recv_until(ws, lambda m: m["type"] == "hello")
        ws.send_text(json.dumps({"type": "find", "mode": "free", "size": 2, "stake": 0, "rules": {}}))
        rooms = []
        while len(rooms) < 2:
            m = recv_until(ws, lambda m: m["type"] == "room")
            rid = m["room"]["id"]
            if rid not in rooms:
                rooms.append(rid)
            g = m["game"]
            if m["room"]["status"] == "finished" and len(rooms) == 1:
                names = [s["name"] for s in m["room"]["seats"]]
                ws.send_text(json.dumps({"type": "rematch", "room": rid}))
                continue
            if g and g["actions"] and g["me"] in g["awaited"] and m["room"]["status"] == "playing":
                ws.send_text(json.dumps({"type": "action", "room": rid, "action": choose_action(g, "medium", rng),
                                         "version": g["version"]}))
        # той самий склад за столом
        assert sorted(s["name"] for s in m["room"]["seats"]) == sorted(names)


def test_simulate_bot_match():
    assert simulate({"variant": "podkidnoy", "deck_size": 36}, ("hard", "easy"), 1) in (0, 1)


def test_tournament_with_bots(client):
    uid = 904
    client.get("/api/me", headers=H(uid))
    lst = client.get("/api/tournaments", headers=H(uid)).json()["tournaments"]
    t8 = next(t for t in lst if t["size"] == 8 and t["status"] == "registering")
    r = client.post("/api/tournaments/register", json={"id": t8["id"]}, headers=H(uid)).json()
    assert r["joined"] and r["registered"] == 1 and r["starts_at"]
    # зайнятий турніром — не може шукати іншу гру
    rng = random.Random(4)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"auth": f"dev {uid}:P{uid}"}))
        recv_until(ws, lambda m: m["type"] == "hello")
        ws.send_text(json.dumps({"type": "find", "mode": "free", "size": 2, "stake": 0, "rules": {}}))
        assert recv_until(ws, lambda m: m["type"] in ("error", "room"))["type"] == "error"
        # гравців мало — вільні місця займають боти
        client.portal.call(main.S.tournaments.start, t8["id"])
        end = None
        for _ in range(20000):
            m = json.loads(ws.receive_text())
            if m["type"] == "tournament" and m["event"] in ("out", "won"):
                end = m
                break
            if m["type"] == "room" and m["room"]["status"] == "playing":
                g = m["game"]
                assert m["room"]["tournament"] == t8["id"]
                if g and g["actions"] and g["me"] in g["awaited"]:
                    ws.send_text(json.dumps({"type": "action", "room": m["room"]["id"],
                                             "action": choose_action(g, "medium", rng), "version": g["version"]}))
        assert end
    # турнір доходить до кінця (решта матчів — боти між собою)
    for _ in range(200):
        v = client.get(f"/api/tournaments/{t8['id']}", headers=H(uid)).json()
        if v["status"] == "finished":
            break
        time.sleep(0.05)
    assert v["status"] == "finished" and v["winner"]
    assert [len(r) for r in v["rounds"]] == [4, 2, 1]
    assert v["out"] == (end["event"] == "out")
    assert (v["winner"] == f"Player{uid}") == (end["event"] == "won")
    if end["event"] == "won":
        me = client.get("/api/progress", headers=H(uid)).json()
        assert any(t["label"].startswith("🏆") for t in me["titles"])
    # нова реєстрація відкрилась автоматично
    lst = client.get("/api/tournaments", headers=H(uid)).json()["tournaments"]
    assert any(t["size"] == 8 and t["status"] == "registering" for t in lst)


def test_reports_and_alerts(client):
    for u in (911, 912, 913, 914):
        client.get("/api/me", headers=H(u))
    for u in (911, 912, 913):
        assert client.post("/api/report", json={"user_id": 914, "reason": "грубіян"}, headers=H(u)).status_code == 200
    assert client.post("/api/report", json={"user_id": 914, "reason": "x"}, headers=H(911)).status_code == 400
    a = client.get("/api/admin/alerts", headers=ADMIN).json()
    assert any(x["kind"] == "reports" for x in a["alerts"])
    assert len([r for r in a["reports"] if r["target_id"] == 914]) == 3
    # велика сума
    client.post("/api/admin/adjust", json={"user_id": 911, "amount": 9000, "reason": "тест"}, headers=ADMIN)
    a = client.get("/api/admin/alerts", headers=ADMIN).json()
    assert any(x["kind"] == "amount" for x in a["alerts"])
    assert client.get("/api/admin/overview", headers=ADMIN).json()["alerts_new"] >= 2
    client.post("/api/admin/alerts/seen", headers=ADMIN)
    assert client.get("/api/admin/overview", headers=ADMIN).json()["alerts_new"] == 0
    assert client.get("/api/admin/alerts", headers=H(911)).status_code == 403


def test_analytics_backup_broadcast(client):
    a = client.get("/api/admin/analytics?days=7", headers=ADMIN).json()
    assert len(a["series"]) == 7 and a["series"][-1]["dau"] >= 1
    assert a["totals"]["users"] >= 1 and a["modes"]
    name, data = main.S.ops.make_backup()
    assert name.endswith(".db.gz") and gzip.decompress(data)[:15] == b"SQLite format 3"
    # без бота розсилка й бекап недоступні, але статус показується
    assert client.post("/api/admin/broadcast", json={"text": "Привіт"}, headers=ADMIN).status_code == 400
    st = client.get("/api/admin/broadcast", headers=ADMIN).json()
    assert st["recipients"] >= 1 and st["bot"] is False


def test_award_items_not_for_sale(client):
    client.post("/api/admin/adjust", json={"user_id": 911, "amount": 100, "reason": "тест"}, headers=ADMIN)
    assert client.post("/api/shop/buy", json={"item_id": "back_champion"}, headers=H(911)).status_code == 400


def test_season_awards():
    db = main.S.db
    pr = Progress(db)
    db.upsert_user(960, "Top", None)
    db.kv_set("season_awarded", "2000-01")
    prev_start = season_bounds(season_id(season_bounds(season_id())[0] - 1))[0]
    db.ex("INSERT INTO match_points(user_id,points,created_at) VALUES(960,30000,?)", (prev_start + 10,))
    pr.award_finished_seasons()
    assert db.one("SELECT 1 FROM inventory WHERE user_id=960 AND item_id='back_season'")


def test_tournament_surrender_means_out(client):
    uid = 905
    client.get("/api/me", headers=H(uid))
    t8 = next(t for t in client.get("/api/tournaments", headers=H(uid)).json()["tournaments"]
              if t["size"] == 8 and t["status"] == "registering")
    client.post("/api/tournaments/register", json={"id": t8["id"]}, headers=H(uid))
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"auth": f"dev {uid}:P{uid}"}))
        recv_until(ws, lambda m: m["type"] == "hello")
        client.portal.call(main.S.tournaments.start, t8["id"])
        recv_until(ws, lambda m: m["type"] == "room" and m["room"]["status"] == "playing")
        ws.send_text(json.dumps({"type": "surrender"}))
        assert recv_until(ws, lambda m: m["type"] == "tournament" and m["event"] in ("out", "won"))["event"] == "out"
    v = client.get(f"/api/tournaments/{t8['id']}", headers=H(uid)).json()
    mine = next(g for g in v["rounds"][0] if g["me"])
    assert mine["winner"] == (0 if mine["b"] == f"Player{uid}" else 1)


def test_turn_push_sent_once_when_player_misses_move(client):
    """Пропущений хід → одне нагадування в Telegram. Ботам — ніколи, двічі за матч — ні."""
    sent = []

    async def fake_notify(uid, room_id):
        sent.append((uid, room_id))

    main.S.rooms.notify_turn = fake_notify
    try:
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"auth": "dev 960:Away"}))
            recv_until(ws, lambda m: m["type"] == "hello")
            ws.send_text(json.dumps({"type": "find", "mode": "free", "size": 2, "stake": 0,
                                     "rules": {"variant": "podkidnoy"}}))
            # НЕ ходимо, імітуючи згорнутий застосунок
            m = recv_until(ws, lambda m: m["type"] == "room" and m.get("game"))
            rid = m["room"]["id"]
            room = main.S.rooms.rooms[rid]

            # Дедлайн гасимо в циклі, а не один раз: між читанням кадру й записом
            # могла пройти черга бота, і тоді ходу від нас ще не чекають.
            for _ in range(60):        # таймер оглядає кімнати раз на 0.5 с
                if sent:
                    break
                room.deadline = 0
                time.sleep(0.2)
            assert sent == [(960, rid)]

            # повернувся, походив і знову відійшов — другого нагадування немає
            seat = room.seat_by_pid("u960")
            if seat:
                seat.timeouts = 0
                assert seat.turn_push is True
            room.deadline = 0
            time.sleep(1.2)
            assert len(sent) == 1
    finally:
        main.S.rooms.notify_turn = None


def test_weekly_quests_live_beside_daily(client):
    """Тижневі — той самий механізм, інший період: більша ціль і нагорода."""
    from app.progress import QUEST_KINDS, WEEK_TARGET_SCALE

    db = main.S.db
    db.upsert_user(970, "Weekly", None)
    pr = Progress(db)
    daily, weekly = pr.quests(970), pr.weekly(970)
    assert len(daily) == 3 and len(weekly) == 3
    assert all("-W" in q["day"] for q in weekly)
    assert all("-W" not in q["day"] for q in daily)
    for q in weekly:
        base = QUEST_KINDS[q["qid"]][1]
        assert q["target"] in [b * WEEK_TARGET_SCALE for b in base]

    # один матч рухає обидва набори
    done = pr._bump_quests(970, {k: 99 for k in QUEST_KINDS})
    assert any(d["weekly"] for d in done), done
    assert any(not d["weekly"] for d in done), done


def test_head_to_head_counts_only_duels(client):
    db = main.S.db
    pr = Progress(db)
    for uid in (980, 981, 982):
        db.upsert_user(uid, f"P{uid}", None)

    def rec(mid, players, result):
        db.ex("INSERT INTO matches(id,created_at,mode,stake,rules,players,status,result) VALUES(?,?,?,?,?,?,?,?)",
              (mid, int(time.time()), "free", 0, "{}", json.dumps([]), "finished", json.dumps(result)))
        for u in players:
            db.ex("INSERT OR IGNORE INTO match_players(match_id,user_id) VALUES(?,?)", (mid, u))

    rec("h2h1", [980, 981], {"loser": "u981"})
    rec("h2h2", [980, 981], {"loser": "u980"})
    rec("h2h3", [980, 981], {"draw": True})
    rec("h2h4", [980, 981, 982], {"loser": "u982"})   # програв третій — не очна зустріч

    assert pr.head_to_head(980, 981) == {"played": 4, "wins": 1, "losses": 1, "draws": 1}
    assert pr.head_to_head(981, 980) == {"played": 4, "wins": 1, "losses": 1, "draws": 1}
    assert pr.head_to_head(980, 982)["played"] == 1


def test_gift_cosmetic_to_friend():
    """Подарунок: платить дарувальник, предмет — другові, фішки йдуть у банк, не гравцю.

    На власній БД: подарунок переводить фішки в банк гри, а він спільний для всіх
    тестових модулів (вони ділять один файл) — псувати його балансні перевірки не можна.
    """
    from app.db import DB
    from app.ledger import BANK, Ledger
    from app.shop import Shop, ShopError

    db = DB(":memory:")
    giver, friend = 985, 986
    for uid in (giver, friend):
        db.upsert_user(uid, f"P{uid}", None)
    led = Ledger(db)
    led.post(f"u:{giver}", 1000, "deposit")
    shop = Shop(db, led)

    bank_before = led.balance(BANK)
    shop.gift(giver, friend, "back_navy")                 # 100 фішок

    assert "back_navy" in shop.owned(friend)              # предмет у друга
    assert "back_navy" not in shop.owned(giver)           # і не в дарувальника
    assert shop.equipped(friend)["back"] != "back_navy"   # вдягає сам
    assert led.balance(f"u:{friend}") == 0                # це не переказ фішок
    assert led.balance(f"u:{giver}") == 900
    assert led.balance(BANK) == bank_before + 100         # оплата йде в банк гри

    for bad in (
        lambda: shop.gift(giver, friend, "back_navy"),    # вже є
        lambda: shop.gift(giver, giver, "back_carbon"),   # самому собі
        lambda: shop.gift(giver, friend, "back_classic"), # безкоштовний
        lambda: shop.gift(giver, friend, "back_champion"),# лише нагорода
    ):
        with pytest.raises(ShopError):
            bad()


def test_gift_only_to_friends(client):
    """Ендпоінт: чужому гравцю подарунок не йде (фішки при цьому не рухаються)."""
    client.get("/api/me", headers=H(987))
    r = client.post("/api/shop/gift", json={"user_id": 988, "item_id": "back_carbon"}, headers=H(987))
    assert r.status_code == 403


def test_daily_deal_is_identical_for_everyone(client):
    """Роздача дня: однакові карти всім, одна спроба на добу, своя таблиця."""
    hands = {}
    for uid in (991, 992):
        client.get("/api/me", headers=H(uid))
        with client.websocket_connect("/ws") as ws:
            ws.send_text(json.dumps({"auth": f"dev {uid}:D{uid}"}))
            recv_until(ws, lambda m: m["type"] == "hello")
            r = client.post("/api/daily", headers=H(uid))
            assert r.status_code == 200, r.text
            m = recv_until(ws, lambda m: m["type"] == "room" and m.get("game"))
            g = m["game"]
            hands[uid] = sorted(g["hand"])
            assert g["trump_card_shown"]
            trump = g["trump_card_shown"]
            ws.send_text(json.dumps({"type": "surrender"}))
            recv_until(ws, lambda m: m["type"] == "room" and m["room"]["status"] == "finished")

    assert hands[991] == hands[992], "роздача дня має бути однаковою"
    assert len(hands[991]) == 6

    # друга спроба за добу — ні
    assert client.post("/api/daily", headers=H(991)).status_code == 409

    d = client.get("/api/daily", headers=H(991)).json()
    assert d["played"] is True
    assert {r["user_id"] for r in d["top"]} >= {991, 992}
    assert d["me"]["outcome"] == "loss"          # здався
    assert trump


def test_season_pass_unlocks_and_claims_once(client):
    from app.progress import SEASON_PASS

    db = main.S.db
    db.upsert_user(995, "Pass", None)
    pr = Progress(db)
    sid = season_id()

    p = pr.season_pass(995, sid)
    assert p["points"] == 0 and p["claimable"] == 0
    assert all(not x["unlocked"] for x in p["tiers"])

    # очки сезону — ті самі, що в таблиці лідерів
    first = SEASON_PASS[0]
    db.ex("INSERT INTO match_points(user_id,points,created_at) VALUES(?,?,?)",
          (995, first["points"], int(time.time())))
    p = pr.season_pass(995, sid)
    assert p["points"] == first["points"] and p["claimable"] == 1
    assert p["tiers"][0]["unlocked"] and not p["tiers"][0]["claimed"]

    xp_before = db.user(995)["xp"] or 0
    got = pr.claim_season_tier(995, first["tier"], sid)
    assert got["xp"] == first["xp"]
    assert (db.user(995)["xp"] or 0) == xp_before + first["xp"]
    assert pr.season_pass(995, sid)["claimable"] == 0

    with pytest.raises(ValueError):            # двічі одну нагороду — ні
        pr.claim_season_tier(995, first["tier"], sid)
    with pytest.raises(ValueError):            # закритий рівень — ні
        pr.claim_season_tier(995, SEASON_PASS[-1]["tier"], sid)

    # останній рівень дає титул
    db.ex("INSERT INTO match_points(user_id,points,created_at) VALUES(?,?,?)",
          (995, SEASON_PASS[-1]["points"], int(time.time())))
    last = pr.claim_season_tier(995, SEASON_PASS[-1]["tier"], sid)
    assert last["title"] and sid in last["title"]
    assert any(sid in tl["label"] for tl in pr.titles(995))


def test_tutorial_match_does_not_spend_daily_free_limit(client):
    uid = 996
    assert client.get("/api/me", headers=H(uid)).json()["tutorial_done"] is False
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"auth": f"dev {uid}:Novice"}))
        recv_until(ws, lambda m: m["type"] == "hello")
        assert client.post("/api/tutorial", headers=H(uid)).status_code == 200
        m = recv_until(ws, lambda m: m["type"] == "room" and m.get("game"))
        assert m["room"]["tutorial"] is True          # клієнт знає, що показувати підказки
        assert len(m["game"]["hand"]) == 6
        ws.send_text(json.dumps({"type": "surrender"}))
        recv_until(ws, lambda m: m["type"] == "room" and m["room"]["status"] == "finished")

    me = client.get("/api/me", headers=H(uid)).json()
    assert me["tutorial_done"] is True
    # денний ліміт безкоштовних ігор навчання не витрачає
    u = main.S.db.user(uid)
    assert (u["free_count"] or 0) == 0
    assert main.S.db.one("SELECT kind FROM matches WHERE kind='tutorial' LIMIT 1")
