"""Аватарки гравців: фото з Telegram або власне зображення.

Власне зображення завжди перекодовується сервером (Pillow) у JPEG 160×160 — це прибирає
метадані (EXIF/GPS) і не дає підсунути замасковані файли.
"""
from __future__ import annotations

import base64
import io
import time
from urllib.parse import urlparse

from PIL import Image, ImageOps

from .db import DB

MAX_UPLOAD = 2_000_000          # байт у base64-даних
SIZE = 160
Image.MAX_IMAGE_PIXELS = 40_000_000


class AvatarError(Exception):
    pass


def avatar_url(u: dict | None) -> str | None:
    if not u:
        return None
    kind = u.get("avatar") or "tg"
    if kind == "custom":
        return f"/api/avatar/{u['id']}?v={u.get('avatar_ver') or 0}"
    if kind == "tg" and u.get("tg_photo"):
        return u["tg_photo"]
    return None


def safe_tg_photo(url: str | None) -> str | None:
    """Приймаємо лише https-фото з доменів Telegram."""
    if not isinstance(url, str) or len(url) > 500:
        return None
    p = urlparse(url)
    host = (p.hostname or "").lower()
    if p.scheme == "https" and (host == "t.me" or host.endswith((".telegram.org", ".telesco.pe", ".t.me"))):
        return url
    return None


def process_upload(data_url: str) -> bytes:
    if not isinstance(data_url, str) or len(data_url) > MAX_UPLOAD:
        raise AvatarError("Зображення завелике")
    _, _, b64 = data_url.partition(",")
    try:
        raw = base64.b64decode(b64 or data_url, validate=False)
        img = Image.open(io.BytesIO(raw))
        if img.format not in ("JPEG", "PNG", "WEBP", "GIF"):
            raise AvatarError("Підтримуються JPEG, PNG, WEBP")
        img = ImageOps.exif_transpose(img)
        img = ImageOps.fit(img.convert("RGB"), (SIZE, SIZE), Image.LANCZOS)
    except AvatarError:
        raise
    except Exception:  # noqa: BLE001
        raise AvatarError("Не вдалося прочитати зображення")
    out = io.BytesIO()
    img.save(out, "JPEG", quality=84, optimize=True)
    return out.getvalue()


class Avatars:
    def __init__(self, db: DB):
        self.db = db

    def set_custom(self, uid: int, data_url: str) -> None:
        jpeg = process_upload(data_url)
        with self.db.tx() as c:
            c.execute("INSERT INTO avatars(user_id,data,updated_at) VALUES(?,?,?) "
                      "ON CONFLICT(user_id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at",
                      (uid, jpeg, int(time.time())))
            c.execute("UPDATE users SET avatar='custom', avatar_ver=COALESCE(avatar_ver,0)+1 WHERE id=?", (uid,))

    def set_kind(self, uid: int, kind: str) -> None:
        if kind not in ("tg", "none"):
            raise AvatarError("Невідомий тип аватарки")
        self.db.ex("UPDATE users SET avatar=?, avatar_ver=COALESCE(avatar_ver,0)+1 WHERE id=?", (kind, uid))

    def get(self, uid: int) -> bytes | None:
        r = self.db.one("SELECT data FROM avatars WHERE user_id=?", (uid,))
        return r["data"] if r else None

    def remove(self, uid: int) -> None:
        with self.db.tx() as c:
            c.execute("DELETE FROM avatars WHERE user_id=?", (uid,))
            c.execute("UPDATE users SET avatar='none', avatar_ver=COALESCE(avatar_ver,0)+1 WHERE id=?", (uid,))
