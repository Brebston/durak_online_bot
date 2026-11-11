import os
from dataclasses import dataclass, field
from pathlib import Path


def _ids(v: str) -> set[int]:
    return {int(x) for x in v.replace(" ", "").split(",") if x}


@dataclass
class Settings:
    bot_token: str = os.getenv("BOT_TOKEN", "")
    webapp_url: str = os.getenv("WEBAPP_URL", "http://localhost:8000")
    admin_ids: set[int] = field(default_factory=lambda: _ids(os.getenv("ADMIN_IDS", "")))
    data_dir: Path = Path(os.getenv("DATA_DIR", "./data"))
    dev_mode: bool = os.getenv("DEV_MODE", "0") == "1"
    # 1 Telegram Star = N фішок
    stars_to_chips: int = int(os.getenv("STARS_TO_CHIPS", "10"))
    star_packs: list[int] = field(default_factory=lambda: [int(x) for x in os.getenv("STAR_PACKS", "25,50,100,250").split(",")])
    # скільки безкоштовних матчів на день (0 = без обмежень); адміністратори без обмежень
    free_games_per_day: int = int(os.getenv("FREE_GAMES_PER_DAY", "1"))
    commission_percent: float = float(os.getenv("COMMISSION_PERCENT", "0"))
    stakes: list[int] = field(default_factory=lambda: [int(x) for x in os.getenv("STAKES", "10,50,100,500").split(",")])
    # через скільки секунд «Знайти гру» підсаджує ботів, якщо живих суперників немає
    bot_fill_seconds: int = int(os.getenv("BOT_FILL_SECONDS", "8"))
    deal_key: str = os.getenv("DEAL_KEY", "")
    auth_max_age: int = int(os.getenv("AUTH_MAX_AGE", "86400"))

    @property
    def db_path(self) -> Path:
        return self.data_dir / "durak.db"


settings = Settings()
