"""Telegram-бот: запуск Mini App, оплата Telegram Stars, адмін-команди, підтримка."""
from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    MenuButtonWebApp,
    Message,
    PreCheckoutQuery,
    WebAppInfo,
)

from .bot_i18n import bt, pick_lang
from .config import settings
from .db import DB
from .ledger import BANK, Ledger, LedgerError, acc

log = logging.getLogger("bot")

TERMS = (
    "💳 <b>Умови оплати</b>\n"
    "• Фішки купуються за Telegram Stars: 1 ⭐ = {rate} фішок.\n"
    "• У грі на фішки можна подати заявку на ручну виплату в Stars. Після схвалення адміністратор надсилає їх у Telegram; автоматичної виплати немає.\n"
    "• У грі на фішки ставка резервується до старту матчу. «Дурень» віддає ставку, решта гравців ділять її порівну"
    " (комісія — {fee}%). Нічия або скасований матч — резерв повертається.\n"
    "• Повернення Stars за невикористані фішки — через /paysupport."
)


class TgBot:
    def __init__(self, db: DB, ledger: Ledger, notify: Callable[[int, dict], Awaitable[None]]):
        self.db = db
        self.ledger = ledger
        self.notify = notify
        self.bot = Bot(settings.bot_token)
        self.dp = Dispatcher()
        self.username = ""
        r = Router()
        self._register(r)
        self.dp.include_router(r)

    def lang_of(self, user) -> str:
        u = self.db.user(user.id) if user else None
        return pick_lang(u.get("lang") if u else None, getattr(user, "language_code", None))

    def webapp_button(self, text: str = "🃏 Грати", room: str | None = None) -> InlineKeyboardMarkup:
        url = settings.webapp_url + (f"?room={room}" if room else "")
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=text, web_app=WebAppInfo(url=url))]])

    async def start(self) -> None:
        me = await self.bot.get_me()
        self.username = me.username or ""
        try:
            await self.bot.set_chat_menu_button(
                menu_button=MenuButtonWebApp(text="Грати", web_app=WebAppInfo(url=settings.webapp_url)))
        except Exception:  # noqa: BLE001
            log.warning("menu button not set (WEBAPP_URL має бути https)")

    async def run_polling(self) -> None:
        await self.dp.start_polling(self.bot, handle_signals=False)

    async def notify_invite(self, uid: int, from_name: str, stake: int, room_id: str) -> None:
        """Запрошення другові, який зараз не в грі (якщо він не вимкнув сповіщення)."""
        u = self.db.user(uid)
        if not u or not u["notify"]:
            return
        lang = pick_lang(u.get("lang"), None)
        text = bt(lang, "invite_push", name=from_name, stake=bt(lang, "stake", n=stake) if stake else "")
        try:
            await self.bot.send_message(uid, text, reply_markup=self.webapp_button(bt(lang, "join"), room=room_id))
        except Exception:  # noqa: BLE001
            log.info("cannot notify %s", uid)

    async def notify_turn(self, uid: int, room_id: str) -> None:
        """Нагадування тому, хто пропустив хід (якщо він не вимкнув сповіщення).

        Кнопка веде одразу в ту саму кімнату, а не в головне меню: гравець має
        встигнути повернутись, поки матч не завершився автоздачею.
        """
        u = self.db.user(uid)
        if not u or not u["notify"]:
            return
        lang = pick_lang(u.get("lang"), None)
        try:
            await self.bot.send_message(uid, bt(lang, "turn_push"),
                                        reply_markup=self.webapp_button(bt(lang, "back_to_game"), room=room_id))
        except Exception:  # noqa: BLE001
            log.info("cannot notify %s", uid)

    async def notify_text(self, uid: int, key: str) -> None:
        """Коротке сповіщення з кнопкою «Грати» (якщо гравець не вимкнув сповіщення). key — ключ bot_i18n."""
        u = self.db.user(uid)
        if not u or not u["notify"]:
            return
        lang = pick_lang(u.get("lang"), None)
        try:
            await self.bot.send_message(uid, bt(lang, key), reply_markup=self.webapp_button(bt(lang, "play")))
        except Exception:  # noqa: BLE001
            log.info("cannot notify %s", uid)

    async def create_invoice(self, uid: int, stars: int) -> str:
        chips = stars * settings.stars_to_chips
        return await self.bot.create_invoice_link(
            title=f"{chips} фішок",
            description="Ігрові фішки для «Дурак онлайн». Не виводяться і не обмінюються на гроші.",
            payload=f"chips:{uid}:{stars}:{int(time.time())}",
            currency="XTR",
            prices=[LabeledPrice(label=f"{chips} фішок", amount=stars)],
        )

    # ------------------------------------------------------------------
    def _register(self, r: Router) -> None:
        def is_admin(m: Message) -> bool:
            return bool(m.from_user and m.from_user.id in settings.admin_ids)

        def resolve_user(token: str) -> dict | None:
            token = token.strip()
            if token.lstrip("-").isdigit():
                return self.db.user(int(token))
            return self.db.one("SELECT * FROM users WHERE lower(username)=lower(?)", (token.lstrip("@"),))

        @r.message(CommandStart())
        async def start(m: Message, command: CommandObject):
            u = m.from_user
            self.db.upsert_user(u.id, u.full_name, u.username)
            room = None
            if command.args and command.args.startswith("room_"):
                room = command.args[5:]
            lang = self.lang_of(u)
            text = bt(lang, "invited") if room else bt(lang, "welcome")
            await m.answer(text, reply_markup=self.webapp_button(bt(lang, "play"), room=room))

        @r.message(Command("id"))
        async def my_id(m: Message):
            lang = self.lang_of(m.from_user)
            role = bt(lang, "role_admin" if is_admin(m) else "role_player")
            await m.answer(bt(lang, "id", id=m.from_user.id, role=role))

        @r.message(Command("balance"))
        async def balance(m: Message):
            a = acc(m.from_user.id)
            await m.answer(bt(self.lang_of(m.from_user), "balance", b=self.ledger.balance(a), a=self.ledger.available(a)))

        @r.message(Command("terms"))
        async def terms(m: Message):
            await m.answer(TERMS.format(rate=settings.stars_to_chips, fee=settings.commission_percent),
                           parse_mode="HTML")

        @r.message(Command("support", "paysupport"))
        async def support(m: Message, command: CommandObject):
            if not command.args:
                await m.answer(bt(self.lang_of(m.from_user), "support_usage"))
                return
            tid = self.db.ex("INSERT INTO tickets(user_id,text,created_at) VALUES(?,?,?)",
                             (m.from_user.id, command.args[:2000], int(time.time())))
            await m.answer(bt(self.lang_of(m.from_user), "support_ok", n=tid))
            for admin in settings.admin_ids:
                try:
                    await self.bot.send_message(admin, f"🆘 Звернення №{tid} від {m.from_user.id}: {command.args[:500]}")
                except Exception:  # noqa: BLE001
                    pass

        # ---------- Stars ----------
        @r.pre_checkout_query()
        async def pre_checkout(q: PreCheckoutQuery):
            try:
                kind, uid, stars, _ = q.invoice_payload.split(":")
                ok = (kind == "chips" and int(uid) == q.from_user.id and int(stars) == q.total_amount
                      and q.currency == "XTR" and int(stars) in settings.star_packs)
            except ValueError:
                ok = False
            u = self.db.user(q.from_user.id)
            if u and u["banned"]:
                ok = False
            await q.answer(ok=ok, error_message=None if ok else "Платіж відхилено. Спробуйте ще раз з гри.")

        @r.message(F.successful_payment)
        async def paid(m: Message):
            p = m.successful_payment
            stars = p.total_amount
            chips = stars * settings.stars_to_chips
            uid = m.from_user.id
            self.db.upsert_user(uid, m.from_user.full_name, m.from_user.username)
            new = self.ledger.post(acc(uid), chips, "deposit", ref=p.telegram_payment_charge_id,
                                   reason=f"{stars} Stars", idem=f"stars:{p.telegram_payment_charge_id}")
            if new:
                await m.answer(bt(self.lang_of(m.from_user), "paid", c=chips, b=self.ledger.balance(acc(uid))))
                await self.notify(uid, {"type": "balance"})

        # ---------- адмін ----------
        @r.message(Command("give"))
        async def give(m: Message, command: CommandObject):
            if not is_admin(m):
                await m.answer(bt(self.lang_of(m.from_user), "admin_only", id=m.from_user.id))
                return
            parts = (command.args or "").split(maxsplit=2)
            if len(parts) < 3:
                await m.answer("Формат: /give <id або @username> <сума> <причина>\nСума може бути від'ємною (списання).")
                return
            u = resolve_user(parts[0])
            if not u:
                await m.answer("Гравця не знайдено (він має хоча б раз запустити бота).")
                return
            try:
                amount = int(parts[1])
                self.ledger.admin_adjust(m.from_user.id, acc(u["id"]), amount, parts[2])
            except (ValueError, LedgerError) as e:
                await m.answer(f"Помилка: {e}")
                return
            await m.answer(f"Готово. {u['name']}: {amount:+} → баланс {self.ledger.balance(acc(u['id']))}.")
            await self.notify(u["id"], {"type": "balance"})

        @r.message(Command("bank"))
        async def bank(m: Message, command: CommandObject):
            if not is_admin(m):
                await m.answer(bt(self.lang_of(m.from_user), "admin_only", id=m.from_user.id))
                return
            parts = (command.args or "").split(maxsplit=1)
            if len(parts) < 2:
                await m.answer(f"Банк гри: {self.ledger.balance(BANK)} (вільно {self.ledger.available(BANK)}).\n"
                               "Поповнити: /bank <сума> <причина>")
                return
            try:
                self.ledger.admin_adjust(m.from_user.id, BANK, int(parts[0]), parts[1])
            except (ValueError, LedgerError) as e:
                await m.answer(f"Помилка: {e}")
                return
            await m.answer(f"Банк гри: {self.ledger.balance(BANK)}.")

        @r.message(Command("refund"))
        async def refund(m: Message, command: CommandObject):
            if not is_admin(m):
                await m.answer(bt(self.lang_of(m.from_user), "admin_only", id=m.from_user.id))
                return
            parts = (command.args or "").split()
            if len(parts) != 2:
                await m.answer("Формат: /refund <user_id> <charge_id>")
                return
            uid, charge = int(parts[0]), parts[1]
            dep = self.db.one("SELECT * FROM transactions WHERE idem=?", (f"stars:{charge}",))
            if not dep or dep["account"] != acc(uid):
                await m.answer("Платіж не знайдено.")
                return
            if self.ledger.available(acc(uid)) < dep["amount"]:
                await m.answer("У гравця вже недостатньо фішок для повернення цього платежу.")
                return
            try:
                await self.bot.refund_star_payment(user_id=uid, telegram_payment_charge_id=charge)
            except Exception as e:  # noqa: BLE001
                await m.answer(f"Telegram відхилив повернення: {e}")
                return
            self.ledger.post(acc(uid), -dep["amount"], "refund", ref=charge, admin_id=m.from_user.id,
                             reason="Повернення Stars", idem=f"refund:{charge}", allow_negative=True)
            self.db.audit(m.from_user.id, "refund_stars", acc(uid), {"charge": charge, "chips": dep["amount"]})
            await m.answer("Повернення виконано.")
            await self.notify(uid, {"type": "balance"})
