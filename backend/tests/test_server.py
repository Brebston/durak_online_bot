import json
import os
import random
import sqlite3
import tempfile

os.environ["DEV_MODE"] = "1"
os.environ["ADMIN_IDS"] = "1"
os.environ["BOT_TOKEN"] = ""
os.environ["DATA_DIR"] = tempfile.mkdtemp()
os.environ["FREE_GAMES_PER_DAY"] = "0"
os.environ["BOT_FILL_SECONDS"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.auth import AuthError, sign_init_data, validate_init_data  # noqa: E402
from app.db import DB  # noqa: E402
from app.game.bot_ai import choose_action  # noqa: E402
from app.ledger import BANK, Ledger, LedgerError  # noqa: E402


def test_init_data_signature():
    tok = "123:ABC"
    data = sign_init_data({"id": 5, "first_name": "Ann"}, tok)
    assert validate_init_data(data, tok)["id"] == 5
    with pytest.raises(AuthError):
        validate_init_data(data, "123:WRONG")
    with pytest.raises(AuthError):
        validate_init_data(data.replace("Ann", "Bob"), tok)
    old = sign_init_data({"id": 5}, tok, auth_date=1)
    with pytest.raises(AuthError):
        validate_init_data(old, tok, max_age=60)


def test_ledger_idempotent_and_immutable():
    db = DB(":memory:")
    L = Ledger(db)
    assert L.post("u:1", 100, "deposit", idem="stars:abc")
    assert not L.post("u:1", 100, "deposit", idem="stars:abc")  # повтор платежу
    assert L.balance("u:1") == 100
    with pytest.raises(LedgerError):
        L.post("u:1", -101, "x")
    h = L.hold("u:1", 60, "r1")
    assert L.available("u:1") == 40
    with pytest.raises(LedgerError):
        L.hold("u:1", 50, "r2")
    L.release(h)
    assert L.available("u:1") == 100
    with pytest.raises(sqlite3.IntegrityError):
        db.conn.execute("UPDATE transactions SET amount=1")
    with pytest.raises(LedgerError):
        L.admin_adjust(1, "u:1", 10, "")  # без причини не можна


def test_settle_split():
    db = DB(":memory:")
    L = Ledger(db)
    for a in ("u:1", "u:2", BANK):
        L.post(a, 1000, "deposit")
    for a in ("u:1", "u:2", BANK):
        L.hold(a, 100, "room")
    res = L.settle("room", "m1", 100, "u:1", ["u:2", BANK], commission_percent=10)
    assert res == {"u:1": -100, "u:2": 45, BANK: 45}
    assert L.balance("fee") == 10
    assert L.settle("room", "m1", 100, "u:1", ["u:2", BANK], 10) == {}  # повторно не рахує
    assert L.balance("u:1") == 900 and L.held("u:1") == 0
    total = sum(L.balance(a) for a in ("u:1", "u:2", BANK, "fee"))
    assert total == 3000


def recv_until(ws, pred, limit=4000):
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        if pred(m):
            return m
    raise AssertionError("не дочекались")


def play_vs_bots(client, uid, mode, stake=0, size=2, variant="podkidnoy"):
    rng = random.Random(uid)
    with client.websocket_connect("/ws") as ws:
        ws.send_text(json.dumps({"auth": f"dev {uid}:Tester{uid}"}))
        recv_until(ws, lambda m: m["type"] == "hello")
        ws.send_text(json.dumps({"type": "find", "mode": mode, "size": size, "stake": stake,
                                 "rules": {"variant": variant}}))
        m = recv_until(ws, lambda m: m["type"] in ("room", "error"))
        assert m["type"] == "room", m
        room_id = m["room"]["id"]
        # «Знайти гру»: живих суперників немає → боти підсідають автоматично
        while True:
            m = recv_until(ws, lambda m: m["type"] in ("room", "error"))
            if m["type"] == "error":
                continue
            g = m["game"]
            if not g:
                continue
            # гравець бачить лише власні карти
            for p in g["players"]:
                if p["id"] != g["me"]:
                    assert "hand" not in p
            if m["room"]["status"] == "finished":
                return m
            if g["actions"] and g["me"] in g["awaited"]:
                act = choose_action(g, "medium", rng)
                ws.send_text(json.dumps({"type": "action", "room": room_id, "action": act,
                                         "version": g["version"]}))


@pytest.fixture(scope="module")
def client():
    main.init_state()
    with TestClient(main.app) as c:
        main.S.rooms.rng.uniform = lambda a, b: 0.0  # боти без затримки в тестах
        yield c


def test_free_game_vs_bots(client):
    m = play_vs_bots(client, 101, "free", size=3, variant="perevodnoy")
    assert m["result"]["loser"] or m["result"]["draw"]
    h = client.get("/api/history", headers={"Authorization": "dev 101"}).json()
    assert h["matches"][0]["outcome"] in ("win", "loss", "draw")
    ev = client.get(f"/api/admin/match/{h['matches'][0]['id']}", headers={"Authorization": "dev 1"}).json()
    assert ev["events"][0]["type"] == "start" and ev["events"][-1]["type"] == "finish"
    assert all("hands" not in json.dumps(e["data"]) for e in ev["events"])


def test_stake_game_with_bank(client):
    admin = {"Authorization": "dev 1"}
    client.get("/api/me", headers={"Authorization": "dev 202"})
    # без банку боти не можуть грати на фішки
    r = client.post("/api/admin/adjust", json={"user_id": 202, "amount": 500, "reason": "тест"}, headers=admin)
    assert r.status_code == 200
    # адмін нараховує і собі
    client.get("/api/me", headers=admin)
    assert client.post("/api/admin/adjust", json={"user_id": 1, "amount": 50, "reason": "собі"},
                       headers=admin).status_code == 200
    assert client.post("/api/admin/adjust", json={"amount": 1000, "reason": "банк"}, headers=admin).json()["balance"] == 1000
    m = play_vs_bots(client, 202, "stake", stake=100, size=2)
    me = client.get("/api/me", headers={"Authorization": "dev 202"}).json()
    bank = client.get("/api/admin/overview", headers=admin).json()["bank"]
    assert me["available"]["chips"] == me["balance"]["chips"]  # резерв знято
    assert me["balance"]["chips"] + bank["balance"] == 1500  # фішки не з'являються і не зникають
    if m["result"]["draw"]:
        assert me["balance"]["chips"] == 500
    elif m["result"]["loser"] == "u202":
        assert me["balance"]["chips"] == 400
    else:
        assert me["balance"]["chips"] == 600
    # роздача відкривається лише після матчу, з аудитом
    mid = m["room"]["match_id"]
    d = client.get(f"/api/admin/match/{mid}?reveal=true", headers=admin).json()
    assert len(d["deal"]["hands"]) == 2
    audit = client.get("/api/admin/audit", headers=admin).json()["audit"]
    assert audit[0]["action"] == "reveal_deal"


def test_non_admin_forbidden(client):
    assert client.get("/api/admin/overview", headers={"Authorization": "dev 303"}).status_code == 403
    assert client.get("/api/me", headers={"Authorization": "tma garbage"}).status_code == 401


def H(uid):
    return {"Authorization": f"dev {uid}:User{uid}"}


def test_shop_buy_equip(client):
    admin = {"Authorization": "dev 1"}
    client.get("/api/me", headers=H(404))
    r = client.post("/api/shop/buy", json={"item_id": "back_neon"}, headers=H(404))
    assert r.status_code == 400  # немає фішок
    client.post("/api/admin/adjust", json={"user_id": 404, "amount": 1000, "reason": "тест"}, headers=admin)
    r = client.post("/api/shop/buy", json={"item_id": "back_neon"}, headers=H(404)).json()
    assert "back_neon" in r["owned"] and r["equipped"]["back"] == "back_neon"
    assert client.post("/api/shop/buy", json={"item_id": "back_neon"}, headers=H(404)).status_code == 400
    me = client.get("/api/me", headers=H(404)).json()
    assert me["balance"]["chips"] == 600
    assert client.post("/api/shop/equip", json={"item_id": "table_space"}, headers=H(404)).status_code == 400
    assert client.post("/api/shop/equip", json={"item_id": "back_classic"}, headers=H(404)).json()["equipped"]["back"] == "back_classic"
    client.post("/api/shop/buy", json={"item_id": "emoji_animals"}, headers=H(404))
    assert "🐸" in client.get("/api/me", headers=H(404)).json()["emojis"]


def test_friends_and_messages(client):
    client.get("/api/me", headers=H(501))
    client.get("/api/me", headers=H(502))
    found = client.get("/api/users/search?q=User502", headers=H(501)).json()["users"]
    assert found and found[0]["id"] == 502
    assert client.post("/api/messages", json={"to": 502, "text": "hi"}, headers=H(501)).status_code == 400
    assert client.post("/api/friends/request", json={"user_id": 502}, headers=H(501)).json()["status"] == "requested"
    inc = client.get("/api/friends", headers=H(502)).json()["incoming"]
    assert inc[0]["id"] == 501
    client.post("/api/friends/respond", json={"user_id": 501, "accept": True}, headers=H(502))
    assert client.get("/api/friends", headers=H(501)).json()["friends"][0]["id"] == 502
    client.post("/api/messages", json={"to": 502, "text": "  привіт  "}, headers=H(501))
    msgs = client.get("/api/messages/501", headers=H(502)).json()["messages"]
    assert msgs[-1]["text"] == "привіт"
    # приховати себе з пошуку
    client.post("/api/settings", json={"sound": True, "notify": True, "discoverable": False}, headers=H(502))
    assert client.get("/api/users/search?q=User502", headers=H(501)).json()["users"] == []


def test_custom_room_chat_invite(client):
    client.get("/api/me", headers=H(501))
    client.get("/api/me", headers=H(502))
    client.post("/api/friends/request", json={"user_id": 502}, headers=H(501))
    client.post("/api/friends/request", json={"user_id": 501}, headers=H(502))  # зустрічна = дружба
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_text(json.dumps({"auth": "dev 501:User501"}))
        b.send_text(json.dumps({"auth": "dev 502:User502"}))
        recv_until(a, lambda m: m["type"] == "hello")
        recv_until(b, lambda m: m["type"] == "hello")
        a.send_text(json.dumps({"type": "create", "mode": "free", "size": 3, "name": "Друзі", "listed": True}))
        room = recv_until(a, lambda m: m["type"] == "room")["room"]
        assert room["fill_at"] == 0 and room["name"] == "Друзі"
        lobby = client.get("/api/lobby", headers=H(503)).json()["rooms"]
        assert any(r["id"] == room["id"] for r in lobby)
        a.send_text(json.dumps({"type": "invite", "user_id": 502}))
        inv = recv_until(b, lambda m: m["type"] == "invite")
        assert inv["room"] == room["id"]
        b.send_text(json.dumps({"type": "join", "room": room["id"]}))
        recv_until(a, lambda m: m["type"] == "room" and len(m["room"]["seats"]) == 2)
        b.send_text(json.dumps({"type": "chat", "text": "го"}))
        assert recv_until(a, lambda m: m["type"] == "chat")["msg"]["text"] == "го"
        b.send_text(json.dumps({"type": "chat", "emoji": "🐸"}))  # не куплено
        assert recv_until(b, lambda m: m["type"] == "error")
        a.send_text(json.dumps({"type": "chat", "emoji": "👍"}))
        assert recv_until(b, lambda m: m["type"] == "chat")["msg"]["emoji"] == "👍"
        a.send_text(json.dumps({"type": "add_bots", "room": room["id"], "level": "easy"}))
        m = recv_until(a, lambda m: m["type"] == "room" and m["room"]["status"] == "playing")
        assert all(not s["bot"] for s in m["room"]["seats"])  # у безкоштовній грі позначки бота немає
        a.send_text(json.dumps({"type": "leave"}))
        b.send_text(json.dumps({"type": "leave"}))


def test_restart_releases_holds(tmp_path):
    from app.ledger import Ledger
    db_file = tmp_path / "r.db"
    db = DB(db_file)
    L = Ledger(db)
    L.post("u:9", 100, "deposit")
    L.hold("u:9", 60, "room1")
    db.ex("INSERT INTO matches(id,created_at,mode,stake,rules,players,status) VALUES('m1',0,'stake',60,'{}','[]','playing')")
    main.init_state(str(db_file))
    assert main.S.ledger.available("u:9") == 100
    assert main.S.db.one("SELECT status FROM matches WHERE id='m1'")["status"] == "cancelled"


def test_valid_signature_passes_even_when_ip_blocked(client):
    from app.config import settings
    old = settings.bot_token
    settings.bot_token = "123:TEST"
    try:
        for _ in range(15):  # вичерпуємо ліміт невдалих спроб з цієї IP
            client.get("/api/me", headers={"Authorization": "tma hash=bad&user=%7B%7D"})
        r = client.get("/api/me", headers={"Authorization": "tma hash=bad&user=%7B%7D"})
        assert "Забагато" in r.json()["detail"]
        good = sign_init_data({"id": 777, "first_name": "Real"}, "123:TEST")
        assert client.get("/api/me", headers={"Authorization": f"tma {good}"}).status_code == 200
    finally:
        settings.bot_token = old
