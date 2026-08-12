"""FutFantasy application settings."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def normalize_database_url(url: str) -> str:
    """Render/Neon often give postgres:// — SQLAlchemy + psycopg need postgresql+psycopg://."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Settings(BaseSettings):
    app_name: str = "FutFantasy"
    debug: bool = True
    secret_key: str = "squadforge-dev-change-me"
    # Local default: SQLite file. On Render, set DATABASE_URL to Postgres so accounts survive redeploys.
    database_url: str = f"sqlite:///{DATA_DIR / 'squadforge.db'}"
    formula_version: str = "v0.2.1-cameo"
    budget: float = 100.0
    max_per_club: int = 3
    squad_size: int = 15
    td_block_length: int = 3
    reset_db_on_startup: bool = False  # set True once if schema changes mid-dev
    # Public base URL for password-reset links (e.g. https://your-app.onrender.com)
    public_base_url: str = ""
    # Optional SMTP for password recovery emails (leave empty = free/dev: show link on page)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_tls: bool = True

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, value: object) -> object:
        if isinstance(value, str):
            return normalize_database_url(value)
        return value


settings = Settings()
