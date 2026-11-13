"""Переклади повідомлень Telegram-бота для гравців (uk, en, pl, ru)."""
from __future__ import annotations

LANGS = ("uk", "en", "pl", "ru")

TEXTS: dict[str, dict[str, str]] = {
    "play": {"uk": "🃏 Грати", "en": "🃏 Play", "pl": "🃏 Graj", "ru": "🃏 Играть"},
    "menu": {"uk": "Грати", "en": "Play", "pl": "Graj", "ru": "Играть"},
    "join": {"uk": "Приєднатися", "en": "Join", "pl": "Dołącz", "ru": "Присоединиться"},
    "welcome": {
        "uk": "Вітаю в «Дурак онлайн»! Підкидний і перевідний, 2–4 гравці, друзі, чат і рівні.",
        "en": "Welcome to Durak Online! Classic and transfer Durak, 2–4 players, friends, chat and levels.",
        "pl": "Witaj w Durak Online! Klasyczny i przekazywany Dureń, 2–4 graczy, znajomi, czat i poziomy.",
        "ru": "Добро пожаловать в «Дурак онлайн»! Подкидной и переводной, 2–4 игрока, друзья, чат и уровни.",
    },
    "invited": {
        "uk": "Запрошення до гри! Натисніть кнопку, щоб приєднатися.",
        "en": "You're invited to a game! Tap the button to join.",
        "pl": "Zaproszenie do gry! Naciśnij przycisk, aby dołączyć.",
        "ru": "Приглашение в игру! Нажмите кнопку, чтобы присоединиться.",
    },
    "invite_push": {
        "uk": "{name} кличе вас у «Дурака»{stake}",
        "en": "{name} invites you to play Durak{stake}",
        "pl": "{name} zaprasza cię do gry w Durnia{stake}",
        "ru": "{name} зовёт вас в «Дурака»{stake}",
    },
    "stake": {"uk": " (ставка {n})", "en": " (stake {n})", "pl": " (stawka {n})", "ru": " (ставка {n})"},
    "id": {
        "uk": "Ваш Telegram ID: {id} ({role})", "en": "Your Telegram ID: {id} ({role})",
        "pl": "Twój Telegram ID: {id} ({role})", "ru": "Ваш Telegram ID: {id} ({role})",
    },
    "role_admin": {"uk": "адміністратор", "en": "admin", "pl": "administrator", "ru": "администратор"},
    "role_player": {"uk": "гравець", "en": "player", "pl": "gracz", "ru": "игрок"},
    "balance": {
        "uk": "Баланс: {b} фішок (доступно {a}).", "en": "Balance: {b} chips ({a} available).",
        "pl": "Saldo: {b} żetonów (dostępne {a}).", "ru": "Баланс: {b} фишек (доступно {a}).",
    },
    "support_usage": {
        "uk": "Опишіть проблему після команди, напр.:\n/support Не зарахувались фішки після оплати",
        "en": "Describe the problem after the command, e.g.:\n/support My chips weren't credited after payment",
        "pl": "Opisz problem po poleceniu, np.:\n/support Żetony nie zostały dodane po płatności",
        "ru": "Опишите проблему после команды, напр.:\n/support Не зачислились фишки после оплаты",
    },
    "support_ok": {
        "uk": "Звернення №{n} прийнято. Відповідь прийде сюди.", "en": "Ticket #{n} received. We'll reply here.",
        "pl": "Zgłoszenie nr {n} przyjęte. Odpowiedź przyjdzie tutaj.", "ru": "Обращение №{n} принято. Ответ придёт сюда.",
    },
    "paid": {
        "uk": "✅ Зараховано {c} фішок. Баланс: {b}.", "en": "✅ {c} chips credited. Balance: {b}.",
        "pl": "✅ Dodano {c} żetonów. Saldo: {b}.", "ru": "✅ Зачислено {c} фишек. Баланс: {b}.",
    },
    "chips_received": {
        "uk": "🎁 {name} переказав вам {amount} фішок у «Дурак онлайн».",
        "en": "🎁 {name} sent you {amount} chips in Durak Online.",
        "pl": "🎁 {name} wysłał ci {amount} żetonów w Durak Online.",
        "ru": "🎁 {name} перевёл вам {amount} фишек в «Дурак онлайн».",
    },
    "tournament_match": {
        "uk": "🏆 Ваш матч у турнірі почався — заходьте, суперник чекає!",
        "en": "🏆 Your tournament match has started — come in, your opponent is waiting!",
        "pl": "🏆 Twój mecz w turnieju się zaczął — wchodź, przeciwnik czeka!",
        "ru": "🏆 Ваш матч в турнире начался — заходите, соперник ждёт!",
    },
    "admin_only": {
        "uk": "Команда лише для адміністратора. Ваш Telegram ID: {id} — додайте його в змінну ADMIN_IDS на сервері.",
        "en": "Admin-only command. Your Telegram ID: {id} — add it to ADMIN_IDS on the server.",
        "pl": "Polecenie tylko dla administratora. Twój Telegram ID: {id} — dodaj go do ADMIN_IDS na serwerze.",
        "ru": "Команда только для администратора. Ваш Telegram ID: {id} — добавьте его в ADMIN_IDS на сервере.",
    },
}


def pick_lang(saved: str | None, telegram_code: str | None) -> str:
    if saved in LANGS:
        return saved
    code = (telegram_code or "").lower()[:2]
    return code if code in LANGS else "en"


def bt(lang: str, key: str, **kw) -> str:
    variants = TEXTS[key]
    return variants.get(lang, variants["en"]).format(**kw)
