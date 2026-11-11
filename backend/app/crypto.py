"""Шифрування журналу роздачі. Розшифровка — лише після завершення матчу,
лише адміністратором і з записом в аудит (див. main.py)."""
from __future__ import annotations

import json

from cryptography.fernet import Fernet

from .config import settings


class DealCipher:
    def __init__(self, key: str | None = None):
        if not key:
            path = settings.data_dir / "deal.key"
            if path.exists():
                key = path.read_text().strip()
            else:
                settings.data_dir.mkdir(parents=True, exist_ok=True)
                key = Fernet.generate_key().decode()
                path.write_text(key)
                try:
                    path.chmod(0o600)
                except OSError:
                    pass
        self.f = Fernet(key.encode() if isinstance(key, str) else key)

    def encrypt(self, data: dict) -> str:
        return self.f.encrypt(json.dumps(data).encode()).decode()

    def decrypt(self, token: str) -> dict:
        return json.loads(self.f.decrypt(token.encode()))
