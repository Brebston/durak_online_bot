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
