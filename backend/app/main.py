from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.config import settings
from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.services.seed import seed_if_empty
from app.web_routes import router as web_router

BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title=settings.app_name)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.include_router(api_router)
app.include_router(web_router)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "web" / "static")), name="static")


def _ensure_schema_patches() -> None:
    """SQLite create_all won't add new columns — patch lightly."""
    tables = set(inspect(engine).get_table_names())
    if "players" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("players")}
        statements = []
        if "status" not in cols:
            statements.append("ALTER TABLE players ADD COLUMN status VARCHAR(8) DEFAULT 'a'")
        if "chance_of_playing" not in cols:
            statements.append("ALTER TABLE players ADD COLUMN chance_of_playing INTEGER")
        if "news" not in cols:
            statements.append("ALTER TABLE players ADD COLUMN news VARCHAR(255) DEFAULT ''")
        if statements:
            with engine.begin() as conn:
                for stmt in statements:
                    conn.execute(text(stmt))
    if "leagues" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("leagues")}
        if "league_type" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE leagues ADD COLUMN league_type VARCHAR(16) DEFAULT 'classic'"))
    if "squad_picks" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("squad_picks")}
        if "is_vice_captain" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE squad_picks ADD COLUMN is_vice_captain INTEGER DEFAULT 0"))
    if "clubs" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("clubs")}
        if "kit_code" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clubs ADD COLUMN kit_code INTEGER"))
    if "gameweeks" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("gameweeks")}
        if "deadline_at" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE gameweeks ADD COLUMN deadline_at VARCHAR(64)"))
    if "transfer_logs" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("transfer_logs")}
        if "is_hit" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE transfer_logs ADD COLUMN is_hit INTEGER DEFAULT 0"))


@app.on_event("startup")
def on_startup() -> None:
    required = {
        "clubs",
        "td_picks",
        "chip_states",
        "memberships",
        "leagues",
        "owned_players",
        "transfer_states",
        "h2h_matches",
    }
    existing = set(inspect(engine).get_table_names())
    if settings.reset_db_on_startup or not required.issubset(existing):
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _ensure_schema_patches()
    db = SessionLocal()
    try:
        seed_if_empty(db, force_fpl_sync=False)
    finally:
        db.close()
