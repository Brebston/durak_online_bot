"""HTTP API + WebSocket ігрового сервера."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import AuthError, validate_init_data
from .config import settings
from .crypto import DealCipher
from .db import DB
from .ledger import BANK, FEE, Ledger, LedgerError, acc
from .rooms import RoomError, RoomManager
from .shop import CATALOG, Shop, ShopError
from .social import Social, SocialError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("main")


# ---------- обмеження частоти ----------
class RateLimiter:
    def __init__(self, rate: float, burst: int):
        self.rate, self.burst = rate, burst
        self.state: dict[str, tuple[float, float]] = {}

    def blocked(self, key: str) -> bool:
        if key not in self.state:
            return False
        tokens, last = self.state[key]
        return min(self.burst, tokens + (time.monotonic() - last) * self.rate) < 1

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        tokens, last = self.state.get(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens < 1:
            self.state[key] = (tokens, now)
            return False
        self.state[key] = (tokens - 1, now)
        return True


class State:
    db: DB
    ledger: Ledger
    rooms: RoomManager
    shop: Shop
    social: Social
    tg = None
    conns: dict[int, set[WebSocket]] = defaultdict(set)
    http_limit = RateLimiter(5, 30)
    ws_limit = RateLimiter(8, 20)
    auth_fail = RateLimiter(0.2, 10)
    chat_limit = RateLimiter(1, 4)


S = State()


async def send_to_user(uid: int, msg: dict) -> None:
    dead = []
    for ws in list(S.conns.get(uid, ())):
        try:
            await ws.send_text(json.dumps(msg, ensure_ascii=False))
        except Exception:  # noqa: BLE001
            dead.append(ws)
    for ws in dead:
        S.conns[uid].discard(ws)


def init_state(db_path: str | None = None) -> None:
    S.db = DB(db_path or settings.db_path)
    S.ledger = Ledger(S.db)
    S.shop = Shop(S.db, S.ledger)
    S.social = Social(S.db)
    S.rooms = RoomManager(S.db, S.ledger, DealCipher(settings.deal_key), send_to_user, shop=S.shop, social=S.social)
    S.rooms.online = is_online


def is_online(uid: int) -> bool:
    return bool(S.conns.get(uid))


def online_ids() -> set[int]:
    return {u for u, c in S.conns.items() if c}


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not getattr(S, "db", None):
        init_state()
    task = None
    if settings.bot_token:
        from .bot import TgBot

        S.tg = TgBot(S.db, S.ledger, send_to_user)
        await S.tg.start()
        S.rooms.bot_username = S.tg.username
        S.rooms.notify_offline = S.tg.notify_invite
        task = asyncio.create_task(S.tg.run_polling())
        log.info("Bot @%s started", S.tg.username)
    else:
        log.warning("BOT_TOKEN не задано — бот не запущено (лише DEV_MODE)")
    yield
    if task:
        task.cancel()


app = FastAPI(title="Durak Online", lifespan=lifespan)


# ---------- авторизація ----------
def authenticate(raw: str, ip: str = "") -> dict:
    if S.auth_fail.blocked(ip or "?"):
        raise AuthError("Забагато невдалих спроб, зачекайте")
    raw = raw or ""
    if settings.dev_mode and raw.startswith("dev "):
        # DEV: "dev <id>:<ім'я>" — лише для локальної розробки без Telegram
        from urllib.parse import unquote

        uid, _, name = raw[4:].partition(":")
        user = {"id": int(uid), "first_name": unquote(name) or f"Dev {uid}"}
    else:
        if raw.startswith("tma "):
            raw = raw[4:]
        try:
            user = validate_init_data(raw, settings.bot_token, settings.auth_max_age)
        except AuthError as e:
            S.auth_fail.allow(ip or "?")
            S.db.ex("INSERT INTO auth_log(ts,user_id,ok,note) VALUES(?,?,0,?)", (int(time.time()), None, f"{e} {ip}"))
            raise
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or str(user["id"])
    u = S.db.upsert_user(int(user["id"]), name, user.get("username"))
    return {"id": u["id"], "name": u["name"], "username": u["username"], "banned": u["banned"]}


async def current_user(request: Request, authorization: str = Header(default="")) -> dict:
    ip = request.client.host if request.client else ""
    try:
        user = authenticate(authorization, ip)
    except AuthError as e:
        raise HTTPException(401, str(e))
    if not S.http_limit.allow(f"u{user['id']}"):
        raise HTTPException(429, "Забагато запитів")
    return user


async def admin_user(user: dict = Depends(current_user)) -> dict:
    if user["id"] not in settings.admin_ids:
        raise HTTPException(403, "Лише для адміністратора")
    return user


# ---------- профіль ----------
def user_stats(uid: int) -> dict:
    rows = S.db.q(
        "SELECT m.players, m.result, m.status FROM matches m JOIN match_players mp ON mp.match_id=m.id "
        "WHERE mp.user_id=? AND m.status='finished'", (uid,))
    st = {"played": 0, "wins": 0, "losses": 0, "draws": 0}
    for r in rows:
        res = json.loads(r["result"] or "{}")
        pid = f"u{uid}"
        st["played"] += 1
        if res.get("draw"):
            st["draws"] += 1
        elif res.get("loser") == pid:
            st["losses"] += 1
        else:
            st["wins"] += 1
    return st


@app.get("/api/me")
async def me(user: dict = Depends(current_user)):
    S.db.ex("INSERT INTO auth_log(ts,user_id,ok,note) VALUES(?,?,1,'api')", (int(time.time()), user["id"]))
    u = S.db.user(user["id"])
    a = acc(user["id"])
    modes = S.rooms.modes()
    today = time.strftime("%Y-%m-%d")
    used = u["free_count"] if u["free_day"] == today else 0
    limit = int(modes.get("free_games_per_day") or 0)
    is_admin = user["id"] in settings.admin_ids
    room = S.rooms.current(user["id"])
    return {
        "id": u["id"], "name": u["name"], "username": u["username"],
        "balance": {"chips": S.ledger.balance(a)},
        "available": {"chips": S.ledger.available(a)},
        "stats": user_stats(user["id"]),
        "settings": {"sound": bool(u["sound"]), "notify": bool(u["notify"]),
                     "discoverable": bool(u["discoverable"])},
        "cosmetics": S.shop.equipped(user["id"]),
        "emojis": S.shop.emojis(user["id"]),
        "friend_requests": S.db.one("SELECT COUNT(*) n FROM friend_requests WHERE to_id=?", (user["id"],))["n"],
        "unread": S.db.one("SELECT COUNT(*) n FROM messages WHERE to_id=? AND read=0", (user["id"],))["n"],
        "free_left": None if (not limit or is_admin) else max(0, limit - used),
        "is_admin": is_admin,
        "banned": bool(u["banned"]),
        "verification": "not_required",
        "modes": modes,
        "shop": {"rate": settings.stars_to_chips, "packs": settings.star_packs, "enabled": bool(S.tg) or settings.dev_mode},
        "room": room.id if room else None,
    }


class SettingsIn(BaseModel):
    sound: bool
    notify: bool
    discoverable: bool = True


@app.post("/api/settings")
async def save_settings(body: SettingsIn, user: dict = Depends(current_user)):
    S.db.ex("UPDATE users SET sound=?, notify=?, discoverable=? WHERE id=?",
            (int(body.sound), int(body.notify), int(body.discoverable), user["id"]))
    return {"ok": True}


# ---------- магазин косметики ----------
@app.get("/api/shop")
async def shop_list(user: dict = Depends(current_user)):
    return {"items": CATALOG, "owned": sorted(S.shop.owned(user["id"])), "equipped": S.shop.equipped(user["id"])}


class ItemIn(BaseModel):
    item_id: str


@app.post("/api/shop/buy")
async def shop_buy(body: ItemIn, user: dict = Depends(current_user)):
    try:
        S.shop.buy(user["id"], body.item_id)
    except ShopError as e:
        raise HTTPException(400, str(e))
    return {"owned": sorted(S.shop.owned(user["id"])), "equipped": S.shop.equipped(user["id"])}


@app.post("/api/shop/equip")
async def shop_equip(body: ItemIn, user: dict = Depends(current_user)):
    try:
        return {"equipped": S.shop.equip(user["id"], body.item_id)}
    except ShopError as e:
        raise HTTPException(400, str(e))


# ---------- друзі та повідомлення ----------
@app.get("/api/users/search")
async def users_search(q: str = "", user: dict = Depends(current_user)):
    return {"users": S.social.search(user["id"], q, online_ids())}


@app.get("/api/friends")
async def friends(user: dict = Depends(current_user)):
    return S.social.overview(user["id"], online_ids())


class FriendIn(BaseModel):
    user_id: int
    accept: bool = True


@app.post("/api/friends/request")
async def friend_request(body: FriendIn, user: dict = Depends(current_user)):
    try:
        status = S.social.request(user["id"], body.user_id)
    except SocialError as e:
        raise HTTPException(400, str(e))
    await send_to_user(body.user_id, {"type": "friends", "event": status, "from": user["name"]})
    return {"status": status}


@app.post("/api/friends/respond")
async def friend_respond(body: FriendIn, user: dict = Depends(current_user)):
    try:
        S.social.respond(user["id"], body.user_id, body.accept)
    except SocialError as e:
        raise HTTPException(400, str(e))
    if body.accept:
        await send_to_user(body.user_id, {"type": "friends", "event": "accepted", "from": user["name"]})
    return {"ok": True}


@app.post("/api/friends/remove")
async def friend_remove(body: FriendIn, user: dict = Depends(current_user)):
    S.social.remove(user["id"], body.user_id)
    return {"ok": True}


@app.get("/api/messages/{other}")
async def messages(other: int, user: dict = Depends(current_user)):
    try:
        return {"messages": S.social.conversation(user["id"], other)}
    except SocialError as e:
        raise HTTPException(400, str(e))


class MessageIn(BaseModel):
    to: int
    text: str


@app.post("/api/messages")
async def message_send(body: MessageIn, user: dict = Depends(current_user)):
    if not S.ws_limit.allow(f"dm{user['id']}"):
        raise HTTPException(429, "Забагато повідомлень")
    try:
        msg = S.social.send_message(user["id"], body.to, body.text)
    except SocialError as e:
        raise HTTPException(400, str(e))
    await send_to_user(body.to, {"type": "dm", "msg": {**msg, "from_name": user["name"]}})
    return {"message": msg}


@app.get("/api/history")
async def history(user: dict = Depends(current_user)):
    rows = S.db.q(
        "SELECT m.* FROM matches m JOIN match_players mp ON mp.match_id=m.id WHERE mp.user_id=? "
        "ORDER BY m.created_at DESC LIMIT 50", (user["id"],))
    pid = f"u{user['id']}"
    out = []
    for r in rows:
        res = json.loads(r["result"] or "{}")
        players = json.loads(r["players"])
        if r["status"] == "cancelled":
            outcome = "cancelled"
        elif r["status"] != "finished":
            outcome = "playing"
        elif res.get("draw"):
            outcome = "draw"
        elif res.get("loser") == pid:
            outcome = "loss"
        else:
            outcome = "win"
        out.append({
            "id": r["id"], "created_at": r["created_at"], "mode": r["mode"], "stake": r["stake"],
            "variant": json.loads(r["rules"])["variant"], "outcome": outcome,
            "delta": (res.get("payouts") or {}).get(pid, 0),
            "opponents": [p["name"] for p in players if p["pid"] != pid],
        })
    return {"matches": out, "transactions": S.ledger.history(acc(user["id"]), 30)}


class InvoiceIn(BaseModel):
    stars: int


@app.post("/api/invoice")
async def invoice(body: InvoiceIn, user: dict = Depends(current_user)):
    if body.stars not in settings.star_packs:
        raise HTTPException(400, "Невідомий пакет")
    if user["banned"]:
        raise HTTPException(403, "Обліковий запис заблоковано")
    if S.tg:
        return {"link": await S.tg.create_invoice(user["id"], body.stars)}
    if settings.dev_mode:
        chips = body.stars * settings.stars_to_chips
        S.ledger.post(acc(user["id"]), chips, "deposit", reason=f"DEV {body.stars} Stars", idem=f"dev:{time.time_ns()}")
        return {"link": None, "dev_credited": chips}
    raise HTTPException(503, "Оплата недоступна")


class TicketIn(BaseModel):
    text: str
    match_id: str | None = None


@app.post("/api/support")
async def support(body: TicketIn, user: dict = Depends(current_user)):
    text = body.text.strip()[:2000]
    if len(text) < 5:
        raise HTTPException(400, "Опишіть проблему детальніше")
    tid = S.db.ex("INSERT INTO tickets(user_id,text,match_id,created_at) VALUES(?,?,?,?)",
                  (user["id"], text, body.match_id, int(time.time())))
    return {"id": tid}


@app.get("/api/lobby")
async def lobby(user: dict = Depends(current_user)):
    return {"rooms": S.rooms.list_waiting()}


# ---------- адмін ----------
@app.get("/api/admin/overview")
async def admin_overview(admin: dict = Depends(admin_user)):
    return {
        "bank": {"balance": S.ledger.balance(BANK), "available": S.ledger.available(BANK)},
        "fee": S.ledger.balance(FEE),
        "shop": S.ledger.balance("shop"),
        "stars": await stars_overview(),
        "users": S.db.one("SELECT COUNT(*) n FROM users")["n"],
        "matches": S.db.one("SELECT COUNT(*) n FROM matches")["n"],
        "active_rooms": [
            {"id": r.id, "match_id": r.match_id, "status": r.status, "mode": r.mode, "stake": r.stake,
             "seats": [s.name for s in r.seats]}
            for r in S.rooms.rooms.values() if r.status in ("waiting", "playing")
        ],
        "open_tickets": S.db.one("SELECT COUNT(*) n FROM tickets WHERE status='open'")["n"],
        "modes": S.rooms.modes(),
    }


async def stars_overview() -> dict:
    """Скільки Stars заплатили гравці (за журналом) і скільки зараз на балансі бота (з Telegram)."""
    rows = S.db.q("SELECT reason FROM transactions WHERE kind='deposit'")
    refunds = S.db.q("SELECT ref FROM transactions WHERE kind='refund'")
    paid = 0
    for r in rows:
        try:
            paid += int((r["reason"] or "0").split()[0])
        except ValueError:
            pass
    bot_balance = None
    if S.tg:
        try:
            bal = await S.tg.bot.get_my_star_balance()
            bot_balance = bal.amount
        except Exception:  # noqa: BLE001
            bot_balance = None
    return {"paid_total": paid, "refunds": len(refunds), "bot_balance": bot_balance,
            "withdraw_hint": "Виведення: профіль бота в Telegram → Balance/Stars → Withdraw через Fragment (у TON)."}


@app.get("/api/admin/users")
async def admin_users(q: str = "", admin: dict = Depends(admin_user)):
    like = f"%{q.lstrip('@')}%"
    rows = S.db.q("SELECT * FROM users WHERE CAST(id AS TEXT) LIKE ? OR name LIKE ? OR username LIKE ? "
                  "ORDER BY last_seen DESC LIMIT 50", (like, like, like))
    for r in rows:
        r["balance"] = S.ledger.balance(acc(r["id"]))
        r["available"] = S.ledger.available(acc(r["id"]))
    return {"users": rows}


class AdjustIn(BaseModel):
    user_id: int | None = None   # None → банк гри
    amount: int
    reason: str


@app.post("/api/admin/adjust")
async def admin_adjust(body: AdjustIn, admin: dict = Depends(admin_user)):
    account = BANK if body.user_id is None else acc(body.user_id)
    if body.user_id is not None and not S.db.user(body.user_id):
        raise HTTPException(404, "Гравця не знайдено")
    try:
        S.ledger.admin_adjust(admin["id"], account, body.amount, body.reason)
    except LedgerError as e:
        raise HTTPException(400, str(e))
    if body.user_id is not None:
        await send_to_user(body.user_id, {"type": "balance"})
    return {"balance": S.ledger.balance(account)}


@app.get("/api/admin/transactions")
async def admin_tx(account: str = "", admin: dict = Depends(admin_user)):
    if account:
        rows = S.db.q("SELECT * FROM transactions WHERE account=? ORDER BY id DESC LIMIT 200", (account,))
    else:
        rows = S.db.q("SELECT * FROM transactions ORDER BY id DESC LIMIT 200")
    return {"transactions": rows}


@app.get("/api/admin/matches")
async def admin_matches(q: str = "", admin: dict = Depends(admin_user)):
    rows = S.db.q("SELECT id,created_at,finished_at,mode,stake,players,status,result FROM matches "
                  "WHERE id LIKE ? ORDER BY created_at DESC LIMIT 100", (f"%{q}%",))
    for r in rows:
        r["players"] = json.loads(r["players"])
        r["result"] = json.loads(r["result"] or "null")
    return {"matches": rows}


@app.get("/api/admin/match/{match_id}")
async def admin_match(match_id: str, reveal: bool = False, admin: dict = Depends(admin_user)):
    m = S.db.one("SELECT * FROM matches WHERE id=?", (match_id,))
    if not m:
        raise HTTPException(404, "Матч не знайдено")
    events = S.db.q("SELECT seq,ts,actor,type,data FROM match_events WHERE match_id=? ORDER BY seq", (match_id,))
    for e in events:
        e["data"] = json.loads(e["data"] or "{}")
    deal = None
    if reveal:
        # Роздачу (приховані карти) можна відкрити лише ПІСЛЯ завершення матчу, з записом в аудит.
        if m["status"] == "playing":
            raise HTTPException(403, "Карти не розкриваються під час активного матчу")
        deal = S.rooms.cipher.decrypt(m["deal_enc"])
        S.db.audit(admin["id"], "reveal_deal", match_id, {})
    m.pop("deal_enc", None)
    m["players"] = json.loads(m["players"])
    m["result"] = json.loads(m["result"] or "null")
    m["rules"] = json.loads(m["rules"])
    return {"match": m, "events": events, "deal": deal}


class CancelIn(BaseModel):
    room_id: str
    reason: str


@app.post("/api/admin/cancel")
async def admin_cancel(body: CancelIn, admin: dict = Depends(admin_user)):
    try:
        await S.rooms.admin_cancel(admin["id"], body.room_id, body.reason)
    except RoomError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


class BanIn(BaseModel):
    user_id: int
    banned: bool
    reason: str


@app.post("/api/admin/ban")
async def admin_ban(body: BanIn, admin: dict = Depends(admin_user)):
    if len(body.reason.strip()) < 3:
        raise HTTPException(400, "Вкажіть причину")
    S.db.ex("UPDATE users SET banned=?, ban_reason=? WHERE id=?", (int(body.banned), body.reason, body.user_id))
    S.db.audit(admin["id"], "ban" if body.banned else "unban", acc(body.user_id), {"reason": body.reason})
    return {"ok": True}


@app.get("/api/admin/tickets")
async def admin_tickets(admin: dict = Depends(admin_user)):
    return {"tickets": S.db.q("SELECT * FROM tickets ORDER BY status='open' DESC, id DESC LIMIT 100")}


class AnswerIn(BaseModel):
    ticket_id: int
    answer: str


@app.post("/api/admin/tickets/answer")
async def admin_answer(body: AnswerIn, admin: dict = Depends(admin_user)):
    t = S.db.one("SELECT * FROM tickets WHERE id=?", (body.ticket_id,))
    if not t:
        raise HTTPException(404, "Не знайдено")
    S.db.ex("UPDATE tickets SET status='closed', answer=? WHERE id=?", (body.answer, body.ticket_id))
    S.db.audit(admin["id"], "ticket_answer", str(body.ticket_id), {"answer": body.answer})
    if S.tg:
        try:
            await S.tg.bot.send_message(t["user_id"], f"Відповідь на звернення №{t['id']}:\n{body.answer}")
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True}


class ModesIn(BaseModel):
    free: bool
    stake: bool
    bots: bool
    stakes: list[int]
    commission_percent: float
    free_games_per_day: int
    bot_fill_seconds: int = 8
    bot_level: str = "mixed"


@app.post("/api/admin/modes")
async def admin_modes(body: ModesIn, admin: dict = Depends(admin_user)):
    data = body.model_dump()
    data["stakes"] = sorted({s for s in data["stakes"] if s > 0})
    if not 0 <= data["commission_percent"] <= 50:
        raise HTTPException(400, "Комісія 0–50%")
    if data["bot_level"] not in ("easy", "medium", "hard", "mixed") or not 0 <= data["bot_fill_seconds"] <= 300:
        raise HTTPException(400, "Невірні налаштування ботів")
    S.db.kv_set("modes", json.dumps(data))
    S.db.audit(admin["id"], "modes", None, data)
    return S.rooms.modes()


@app.get("/api/admin/audit")
async def admin_audit(admin: dict = Depends(admin_user)):
    return {"audit": S.db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 200")}


# ---------- WebSocket ----------
@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    ip = ws.client.host if ws.client else ""
    try:
        first = json.loads(await asyncio.wait_for(ws.receive_text(), timeout=15))
        user = authenticate(first.get("auth", ""), ip)
    except Exception as e:  # noqa: BLE001
        await ws.send_text(json.dumps({"type": "error", "message": f"Авторизація: {e}", "fatal": True}))
        await ws.close()
        return
    uid = user["id"]
    S.db.ex("INSERT INTO auth_log(ts,user_id,ok,note) VALUES(?,?,1,'ws')", (int(time.time()), uid))
    S.conns[uid].add(ws)
    await ws.send_text(json.dumps({"type": "hello", "user": user["id"]}))
    room = S.rooms.current(uid)
    if room:
        await ws.send_text(json.dumps(S.rooms.payload(room, uid), ensure_ascii=False))
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            if not S.ws_limit.allow(f"u{uid}"):
                await ws.send_text(json.dumps({"type": "error", "message": "Забагато дій, зачекайте"}))
                continue
            try:
                await handle_ws(uid, user, msg)
            except RoomError as e:
                if str(e) == "stale":
                    r = S.rooms.current(uid)
                    if r:
                        await ws.send_text(json.dumps(S.rooms.payload(r, uid), ensure_ascii=False))
                else:
                    await ws.send_text(json.dumps({"type": "error", "message": str(e)}))
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        log.exception("ws error")
    finally:
        S.conns[uid].discard(ws)


async def handle_ws(uid: int, user: dict, msg: dict) -> None:
    t = msg.get("type")
    fresh = S.db.user(uid)
    if fresh and fresh["banned"] and t not in ("leave", "ping"):
        raise RoomError("Обліковий запис заблоковано")
    if t == "ping":
        await send_to_user(uid, {"type": "pong"})
    elif t == "find":
        await S.rooms.find_match(user, msg.get("mode", "free"), int(msg.get("size", 2)),
                                 int(msg.get("stake", 0)), msg.get("rules"))
    elif t == "create":
        await S.rooms.create(user, msg.get("mode", "free"), int(msg.get("size", 2)),
                             int(msg.get("stake", 0)), msg.get("rules"), private=True,
                             name=str(msg.get("name") or ""), listed=bool(msg.get("listed")))
    elif t == "chat":
        if not S.chat_limit.allow(f"u{uid}"):
            raise RoomError("Не так швидко 🙂")
        await S.rooms.chat(uid, text=msg.get("text"), emoji=msg.get("emoji"))
    elif t == "invite":
        await S.rooms.invite(uid, int(msg.get("user_id", 0)))
    elif t == "join":
        await S.rooms.join(user, str(msg.get("room", "")))
    elif t == "add_bots":
        await S.rooms.add_bots(uid, str(msg.get("room", "")), msg.get("level", "medium"))
    elif t == "leave":
        await S.rooms.leave(uid)
        await send_to_user(uid, {"type": "left"})
    elif t == "action":
        await S.rooms.action(uid, str(msg.get("room", "")), msg.get("action") or {}, msg.get("version"))
    elif t == "surrender":
        await S.rooms.surrender(uid)
    elif t == "state":
        r = S.rooms.current(uid)
        await send_to_user(uid, S.rooms.payload(r, uid) if r else {"type": "left"})
    else:
        raise RoomError("Невідома команда")


@app.get("/api/health")
async def health():
    return {"ok": True}


# ---------- статика Mini App ----------
DIST = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        f = DIST / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
