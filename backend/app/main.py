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
from .avatars import AvatarError, Avatars, avatar_url, safe_tg_photo
from .bot_i18n import bt, pick_lang
from .config import settings
from .crypto import DealCipher
from .db import DB
from .ledger import BANK, Ledger, LedgerError, acc
from .levels import progress
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
    avatars: Avatars
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
    S.avatars = Avatars(S.db)
    S.rooms = RoomManager(S.db, S.ledger, DealCipher(settings.deal_key), send_to_user, shop=S.shop, social=S.social)
    S.rooms.online = is_online
    recover_after_restart()
    moved = S.ledger.sweep_to_bank()
    if moved:
        log.info("Перенесено в банк гри %s фішок комісії/магазину", moved)


def recover_after_restart() -> None:
    """Кімнати живуть у памʼяті, тож після перезапуску (напр. автодеплою) матчі, що йшли,
    скасовуються, а всі резерви ставок повертаються гравцям і банку."""
    stale = S.db.q("SELECT id FROM matches WHERE status='playing'")
    reason = json.dumps({"cancelled": True, "reason": "Перезапуск сервера — ставки повернуто"}, ensure_ascii=False)
    for m in stale:
        S.db.ex("UPDATE matches SET status='cancelled', finished_at=?, result=? WHERE id=?",
                (int(time.time()), reason, m["id"]))
    held = S.db.one("SELECT COUNT(*) n FROM holds WHERE status='active' AND room_id NOT LIKE 'withdrawal:%'")["n"]
    # Waiting/playing rooms are in memory and disappear on restart; withdrawal reserves persist in SQLite.
    S.db.ex("UPDATE holds SET status='released' WHERE status='active' AND room_id NOT LIKE 'withdrawal:%'")
    if stale or held:
        S.db.audit(None, "restart_recovery", None, {"matches": len(stale), "holds": held})
        log.warning("Після перезапуску скасовано матчів: %s, повернуто резервів: %s", len(stale), held)


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
    if settings.dev_mode and settings.bot_token:
        log.warning("DEV_MODE=1 ігнорується, бо задано BOT_TOKEN: вхід лише через Telegram")
    cleanup = asyncio.create_task(S.rooms.cleanup_loop())
    yield
    cleanup.cancel()
    if task:
        task.cancel()


app = FastAPI(title="Durak Online", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def dev_auth_allowed() -> bool:
    """DEV-вхід без Telegram працює лише без BOT_TOKEN — випадково увімкнений DEV_MODE на бойовому
    сервері не дасть увійти під чужим ID."""
    return settings.dev_mode and not settings.bot_token


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    h = resp.headers
    h.setdefault("X-Content-Type-Options", "nosniff")
    h.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    # Mini App відкривається всередині Telegram (у т.ч. web.telegram.org в iframe) — дозволяємо лише його
    h.setdefault("Content-Security-Policy", "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org")
    if request.url.path.startswith("/api/"):
        h.setdefault("Cache-Control", "no-store")
    return resp


MAX_WS_MESSAGE = 4096


# ---------- авторизація ----------
def authenticate(raw: str, ip: str = "") -> dict:
    """Валідний підпис Telegram пропускається завжди. Ліміт стосується лише невдалих спроб:
    за проксі (Railway, Cloudflare) багато гравців можуть мати спільну IP-адресу, тож чужі
    помилки не повинні блокувати справжніх гравців."""
    raw = raw or ""
    if dev_auth_allowed() and raw.startswith("dev "):
        # DEV: "dev <id>:<ім'я>" — лише для локальної розробки без Telegram
        from urllib.parse import unquote

        uid, _, name = raw[4:].partition(":")
        user = {"id": int(uid), "first_name": unquote(name) or f"Dev {uid}"}
    else:
        if raw.startswith("tma "):
            raw = raw[4:]
        if not raw:
            raise AuthError("Відкрийте гру через бота в Telegram")
        if S.auth_fail.blocked(ip or "?"):
            # перевіряємо підпис навіть під блокуванням — справжній гравець пройде
            try:
                user = validate_init_data(raw, settings.bot_token, settings.auth_max_age)
            except AuthError:
                raise AuthError("Забагато невдалих спроб, зачекайте хвилину")
        else:
            try:
                user = validate_init_data(raw, settings.bot_token, settings.auth_max_age)
            except AuthError as e:
                S.auth_fail.allow(ip or "?")
                S.db.ex("INSERT INTO auth_log(ts,user_id,ok,note) VALUES(?,?,0,?)", (int(time.time()), None, f"{e} {ip}"))
                raise
    name = " ".join(x for x in (user.get("first_name"), user.get("last_name")) if x) or str(user["id"])
    u = S.db.upsert_user(int(user["id"]), name[:64], user.get("username"), safe_tg_photo(user.get("photo_url")))
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
        "progress": progress(int(u["xp"] or 0)),
        "lang": u["lang"],
        "cosmetics": S.shop.equipped(user["id"]),
        "avatar": {"url": avatar_url(u), "kind": u["avatar"] or "tg", "has_tg": bool(u["tg_photo"])},
        "emojis": S.shop.emojis(user["id"]),
        "friend_requests": S.db.one("SELECT COUNT(*) n FROM friend_requests WHERE to_id=?", (user["id"],))["n"],
        "unread": S.db.one("SELECT COUNT(*) n FROM messages WHERE to_id=? AND read=0", (user["id"],))["n"],
        "free_left": None if (not limit or is_admin) else max(0, limit - used),
        "is_admin": is_admin,
        "banned": bool(u["banned"]),
        "verification": "not_required",
        "modes": modes,
        "withdrawal": {
            "stars_per_chips": settings.stars_to_chips,
            "eur_per_star": settings.withdrawal_eur_per_star if settings.withdrawal_eur_per_star > 0 else None,
        },
        "shop": {"rate": settings.stars_to_chips, "packs": settings.star_packs, "enabled": bool(S.tg) or dev_auth_allowed()},
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


class LangIn(BaseModel):
    lang: str


@app.post("/api/lang")
async def save_lang(body: LangIn, user: dict = Depends(current_user)):
    if body.lang not in ("uk", "en", "pl", "ru"):
        raise HTTPException(400, "Невідома мова")
    S.db.ex("UPDATE users SET lang=? WHERE id=?", (body.lang, user["id"]))
    return {"ok": True}


# ---------- аватарки ----------
class AvatarIn(BaseModel):
    kind: str                 # custom | tg | none
    data: str | None = None   # data:image/...;base64,... (для custom)


@app.post("/api/avatar")
async def set_avatar(body: AvatarIn, user: dict = Depends(current_user)):
    try:
        if body.kind == "custom":
            S.avatars.set_custom(user["id"], body.data or "")
        else:
            S.avatars.set_kind(user["id"], body.kind)
    except AvatarError as e:
        raise HTTPException(400, str(e))
    return {"url": avatar_url(S.db.user(user["id"]))}


@app.get("/api/avatar/{uid}")
async def get_avatar(uid: int):
    from fastapi.responses import Response

    data = S.avatars.get(uid)
    if not data:
        raise HTTPException(404, "Не знайдено")
    return Response(data, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=86400"})


class AdminAvatarIn(BaseModel):
    user_id: int
    reason: str


@app.post("/api/admin/avatar/remove")
async def admin_remove_avatar(body: AdminAvatarIn, admin: dict = Depends(admin_user)):
    if len(body.reason.strip()) < 3:
        raise HTTPException(400, "Вкажіть причину")
    S.avatars.remove(body.user_id)
    S.db.audit(admin["id"], "avatar_removed", acc(body.user_id), {"reason": body.reason})
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


class ChipTransferIn(BaseModel):
    to: int
    amount: int
    request_id: str


@app.post("/api/transfers")
async def transfer_chips(body: ChipTransferIn, user: dict = Depends(current_user)):
    """Transfer chips to a friend and notify them through Telegram."""
    uid, recipient_id = user["id"], body.to
    if recipient_id == uid:
        raise HTTPException(400, "Не можна переказати фішки собі")
    if body.amount <= 0 or body.amount > 1_000_000_000:
        raise HTTPException(400, "Некоректна сума переказу")
    if len(body.request_id) > 80 or not body.request_id.strip():
        raise HTTPException(400, "Некоректний ID запиту")
    if not S.social.are_friends(uid, recipient_id):
        raise HTTPException(403, "Переказувати фішки можна лише друзям")
    recipient = S.db.user(recipient_id)
    if not recipient:
        raise HTTPException(404, "Гравця не знайдено")
    transfer_id = f"{uid}:{body.request_id}"
    try:
        inserted = S.ledger.transfer(
            acc(uid), acc(recipient_id), body.amount, "player_transfer",
            ref=transfer_id, reason=f"{uid} → {recipient_id}",
            idem=f"player-transfer:{transfer_id}",
        )
    except LedgerError as e:
        raise HTTPException(400, str(e))
    if not inserted:
        raise HTTPException(409, "Цей переказ уже оброблено")

    await send_to_user(uid, {"type": "balance"})
    await send_to_user(recipient_id, {"type": "balance"})
    if S.tg:
        lang = pick_lang(recipient.get("lang"), None)
        try:
            await S.tg.bot.send_message(
                recipient_id,
                bt(lang, "chips_received", name=user["name"], amount=body.amount),
                reply_markup=S.tg.webapp_button(bt(lang, "play")),
            )
        except Exception:  # noqa: BLE001
            log.info("cannot notify %s about chip transfer", recipient_id)
    return {"ok": True, "to": recipient_id, "amount": body.amount,
            "balance": S.ledger.balance(acc(uid))}


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
    if dev_auth_allowed():
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
    if S.db.one("SELECT COUNT(*) n FROM tickets WHERE user_id=? AND status='open'", (user["id"],))["n"] >= 5:
        raise HTTPException(429, "У вас уже 5 відкритих звернень — дочекайтеся відповіді")
    tid = S.db.ex("INSERT INTO tickets(user_id,text,match_id,created_at) VALUES(?,?,?,?)",
                  (user["id"], text, body.match_id, int(time.time())))
    return {"id": tid}


def withdrawal_public(row: dict) -> dict:
    return {k: row[k] for k in (
        "id", "chips", "stars", "eur_estimate", "status", "created_at", "decided_at",
        "completed_at", "decision_note", "payout_reference",
    )}


@app.get("/api/withdrawals")
async def withdrawals(user: dict = Depends(current_user)):
    rows = S.db.q("SELECT * FROM withdrawal_requests WHERE user_id=? ORDER BY id DESC LIMIT 30", (user["id"],))
    return {"requests": [withdrawal_public(r) for r in rows]}


class WithdrawalIn(BaseModel):
    chips: int


@app.post("/api/withdrawals")
async def create_withdrawal(body: WithdrawalIn, user: dict = Depends(current_user)):
    if body.chips <= 0 or settings.stars_to_chips <= 0 or body.chips % settings.stars_to_chips:
        raise HTTPException(400, f"Сума має бути додатною і кратною {settings.stars_to_chips} фішкам")
    stars = body.chips // settings.stars_to_chips
    estimate = stars * settings.withdrawal_eur_per_star if settings.withdrawal_eur_per_star > 0 else None
    try:
        request_id = S.ledger.create_withdrawal_request(user["id"], body.chips, stars, estimate)
    except LedgerError as e:
        raise HTTPException(400, str(e))
    if S.tg:
        for admin_id in settings.admin_ids:
            try:
                await S.tg.bot.send_message(
                    admin_id,
                    f"Нова заявка на виведення №{request_id}: {body.chips} фішок → {stars} ⭐ "
                    f"від {user['name']} (Telegram ID {user['id']}).",
                )
            except Exception:  # noqa: BLE001
                log.info("cannot notify admin %s about withdrawal %s", admin_id, request_id)
    return {"id": request_id, "chips": body.chips, "stars": stars, "eur_estimate": estimate, "status": "pending"}


@app.get("/api/lobby")
async def lobby(user: dict = Depends(current_user)):
    return {"rooms": S.rooms.list_waiting()}


# ---------- адмін ----------
@app.get("/api/admin/overview")
async def admin_overview(admin: dict = Depends(admin_user)):
    return {
        "bank": {"balance": S.ledger.balance(BANK), "available": S.ledger.available(BANK)},
        "fee": S.ledger.bank_report(None)["fee"],
        "shop": S.ledger.bank_report(None)["shop"],
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


@app.get("/api/admin/withdrawals")
async def admin_withdrawals(status: str = "", admin: dict = Depends(admin_user)):
    if status and status not in ("open", "pending", "approved", "completed", "rejected"):
        raise HTTPException(400, "Невідомий статус")
    if status == "open":
        where, args = "WHERE w.status IN ('pending','approved')", ()
    else:
        where = "WHERE w.status=?" if status else ""
        args = (status,) if status else ()
    rows = S.db.q(
        "SELECT w.*, u.name, u.username FROM withdrawal_requests w JOIN users u ON u.id=w.user_id "
        f"{where} ORDER BY CASE w.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, w.id DESC LIMIT 200",
        args,
    )
    return {"requests": rows}


def audit_withdrawal(conn, admin_id: int, action: str, request: dict, data: dict | None = None) -> None:
    payload = {"user_id": request["user_id"], "chips": request["chips"], "stars": request["stars"], **(data or {})}
    conn.execute(
        "INSERT INTO audit(ts,admin_id,action,target,data) VALUES(?,?,?,?,?)",
        (int(time.time()), admin_id, action, str(request["id"]), json.dumps(payload, ensure_ascii=False)),
    )


@app.post("/api/admin/withdrawals/{request_id}/approve")
async def approve_withdrawal(request_id: int, admin: dict = Depends(admin_user)):
    with S.db.tx() as conn:
        row = conn.execute("SELECT * FROM withdrawal_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Заявку не знайдено")
        if row["status"] != "pending":
            raise HTTPException(409, "Схвалити можна лише заявку зі статусом «очікує»")
        hold = conn.execute(
            "SELECT amount FROM holds WHERE account=? AND room_id=? AND status='active'",
            (acc(row["user_id"]), f"withdrawal:{request_id}"),
        ).fetchone()
        if not hold or hold["amount"] != row["chips"]:
            raise HTTPException(409, "Резерв заявки не знайдено")
        conn.execute(
            "UPDATE withdrawal_requests SET status='approved', decided_at=?, decided_by=? WHERE id=? AND status='pending'",
            (int(time.time()), admin["id"], request_id),
        )
        audit_withdrawal(conn, admin["id"], "withdrawal_approved", dict(row))
    if S.tg:
        try:
            await S.tg.bot.send_message(row["user_id"], f"Заявку на {row['stars']} ⭐ схвалено. Очікуйте ручну виплату.")
        except Exception:  # noqa: BLE001
            log.info("cannot notify withdrawal user %s", row["user_id"])
    return {"ok": True, "status": "approved"}


class RejectWithdrawalIn(BaseModel):
    reason: str


@app.post("/api/admin/withdrawals/{request_id}/reject")
async def reject_withdrawal(request_id: int, body: RejectWithdrawalIn, admin: dict = Depends(admin_user)):
    reason = body.reason.strip()[:500]
    if len(reason) < 3:
        raise HTTPException(400, "Вкажіть причину відхилення")
    with S.db.tx() as conn:
        row = conn.execute("SELECT * FROM withdrawal_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Заявку не знайдено")
        if row["status"] not in ("pending", "approved"):
            raise HTTPException(409, "Цю заявку вже закрито")
        conn.execute(
            "UPDATE withdrawal_requests SET status='rejected', decided_at=?, decided_by=?, decision_note=? "
            "WHERE id=? AND status IN ('pending','approved')",
            (int(time.time()), admin["id"], reason, request_id),
        )
        conn.execute("UPDATE holds SET status='released' WHERE room_id=? AND status='active'",
                     (f"withdrawal:{request_id}",))
        audit_withdrawal(conn, admin["id"], "withdrawal_rejected", dict(row), {"reason": reason})
    if S.tg:
        try:
            await S.tg.bot.send_message(row["user_id"], f"Заявку на {row['stars']} ⭐ відхилено. Причина: {reason}")
        except Exception:  # noqa: BLE001
            log.info("cannot notify withdrawal user %s", row["user_id"])
    await send_to_user(row["user_id"], {"type": "balance"})
    return {"ok": True, "status": "rejected"}


class CompleteWithdrawalIn(BaseModel):
    payout_reference: str


@app.post("/api/admin/withdrawals/{request_id}/complete")
async def complete_withdrawal(request_id: int, body: CompleteWithdrawalIn, admin: dict = Depends(admin_user)):
    reference = body.payout_reference.strip()[:500]
    if len(reference) < 3:
        raise HTTPException(400, "Вкажіть підтвердження ручної виплати")
    with S.db.tx() as conn:
        row = conn.execute("SELECT * FROM withdrawal_requests WHERE id=?", (request_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Заявку не знайдено")
        if row["status"] != "approved":
            raise HTTPException(409, "Виконати можна лише схвалену заявку")
        request = dict(row)
        try:
            S.ledger.complete_withdrawal(conn, request, admin["id"], reference)
        except LedgerError as e:
            raise HTTPException(409, str(e))
        conn.execute(
            "UPDATE withdrawal_requests SET status='completed', completed_at=?, completed_by=?, payout_reference=? "
            "WHERE id=? AND status='approved'",
            (int(time.time()), admin["id"], reference, request_id),
        )
        audit_withdrawal(conn, admin["id"], "withdrawal_completed", request, {"payout_reference": reference})
    if S.tg:
        try:
            await S.tg.bot.send_message(row["user_id"], f"Виплату {row['stars']} ⭐ за заявкою №{request_id} виконано.")
        except Exception:  # noqa: BLE001
            log.info("cannot notify withdrawal user %s", row["user_id"])
    await send_to_user(row["user_id"], {"type": "balance"})
    return {"ok": True, "status": "completed"}


@app.get("/api/admin/bank")
async def admin_bank(period: str = "all", tz: int = 0, admin: dict = Depends(admin_user)):
    """Моніторинг банку: виграші/програші ботів банку, комісія, магазин, поповнення."""
    now = int(time.time())
    if period not in ("today", "7d", "30d", "all"):
        raise HTTPException(400, "Невідомий період")
    tz = max(-14 * 60, min(14 * 60, tz))
    day_start = (now + tz * 60) // 86400 * 86400 - tz * 60
    since = {"today": day_start, "7d": now - 7 * 86400, "30d": now - 30 * 86400, "all": None}[period]
    return {"period": period, **S.ledger.bank_report(since, tz),
            "balance": S.ledger.balance(BANK), "available": S.ledger.available(BANK)}


@app.get("/api/admin/users")
async def admin_users(q: str = "", admin: dict = Depends(admin_user)):
    like = f"%{q.lstrip('@')}%"
    rows = S.db.q("SELECT * FROM users WHERE CAST(id AS TEXT) LIKE ? OR name LIKE ? OR username LIKE ? "
                  "ORDER BY last_seen DESC LIMIT 50", (like, like, like))
    for r in rows:
        r["balance"] = S.ledger.balance(acc(r["id"]))
        r["available"] = S.ledger.available(acc(r["id"]))
        r["avatar_url"] = avatar_url(r)
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
        if not 0 < abs(body.amount) <= 1_000_000_000:
            raise LedgerError("Сума поза допустимими межами")
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
        raw_first = await asyncio.wait_for(ws.receive_text(), timeout=15)
        if len(raw_first) > MAX_WS_MESSAGE:
            raise AuthError("Завеликий запит")
        first = json.loads(raw_first)
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
            raw_msg = await ws.receive_text()
            if len(raw_msg) > MAX_WS_MESSAGE:
                continue  # завеликі повідомлення ігноруємо
            try:
                msg = json.loads(raw_msg)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
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
                    await ws.send_text(json.dumps({"type": "error", "message": str(e), "key": e.key, "args": e.args_},
                                                  ensure_ascii=False))
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
