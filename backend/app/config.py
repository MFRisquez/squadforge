"""FutFantasy application settings."""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


def normalize_database_url(url: str) -> str:
    """Render/Supabase often give postgres:// — SQLAlchemy + psycopg need postgresql+psycopg://."""
    if not url:
        return url
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://") and "+psycopg" not in url.split("://", 1)[0]:
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    # Supabase requires TLS; Render Postgres usually does too when using external hosts
    host = url.split("@")[-1].split("/")[0].lower() if "@" in url else ""
    if "supabase" in host and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


class Settings(BaseSettings):
    app_name: str = "Fut Fantasy"
    debug: bool = True
    secret_key: str = "squadforge-dev-change-me"
    # Local default: SQLite file. On Render, set DATABASE_URL to Supabase Postgres.
    database_url: str = f"sqlite:///{DATA_DIR / 'squadforge.db'}"
    # Optional API-Football key (Render: API_FOOTBALL_KEY). Empty = skip advanced stats.
    api_football_key: str = ""
    api_football_season: int = 2025
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
