"""Перевірка підпису initData Telegram Mini App (на сервері)."""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


class AuthError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict:
    if not init_data or not bot_token:
        raise AuthError("Немає даних авторизації")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = pairs.pop("hash", None)
    if not received:
        raise AuthError("Немає підпису")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise AuthError("Невірний підпис")
    auth_date = int(pairs.get("auth_date", "0"))
    if max_age and time.time() - auth_date > max_age:
        raise AuthError("Сесія застаріла, перезапустіть Mini App")
    user = json.loads(pairs.get("user", "{}"))
    if "id" not in user:
        raise AuthError("Немає користувача")
    return user


def sign_init_data(user: dict, bot_token: str, auth_date: int | None = None) -> str:
    """Для тестів: формує валідний initData."""
    from urllib.parse import urlencode

    pairs = {"user": json.dumps(user, separators=(",", ":")), "auth_date": str(auth_date or int(time.time()))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    pairs["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(pairs)
