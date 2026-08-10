"""SquadForge application settings."""

from pathlib import Path

from pydantic_settings import BaseSettings

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)


class Settings(BaseSettings):
    app_name: str = "SquadForge"
    debug: bool = True
    secret_key: str = "squadforge-dev-change-me"
    database_url: str = f"sqlite:///{DATA_DIR / 'squadforge.db'}"
    formula_version: str = "v0.2.1-cameo"
    budget: float = 100.0
    max_per_club: int = 3
    squad_size: int = 15
    td_block_length: int = 3
    reset_db_on_startup: bool = False  # set True once if schema changes mid-dev



settings = Settings()
