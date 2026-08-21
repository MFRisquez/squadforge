from pathlib import Path

import logging

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.gzip import GZipMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api import router as api_router
from app.config import settings
from app.db import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.services.seed import seed_if_empty
from app.web_routes import router as web_router

BASE_DIR = Path(__file__).resolve().parent
ICONS_DIR = BASE_DIR / "web" / "static" / "icons"
logger = logging.getLogger("squadforge.main")
_DEFAULT_SECRET_KEY = "squadforge-dev-change-me"

app = FastAPI(title=settings.app_name)
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=not settings.debug,
)


@app.middleware("http")
async def advertise_client_hints(request, call_next):
    """Ask browsers for mobile/viewport hints so we can skip desk-side on phones."""
    response = await call_next(request)
    # Merge if a proxy already set Accept-CH.
    existing = response.headers.get("Accept-CH", "")
    wanted = "Sec-CH-UA-Mobile, Sec-CH-Viewport-Width, Viewport-Width"
    response.headers["Accept-CH"] = (
        f"{existing}, {wanted}" if existing and wanted not in existing else wanted
    )
    response.headers["Critical-CH"] = "Sec-CH-UA-Mobile, Sec-CH-Viewport-Width"
    return response


app.include_router(api_router)
app.include_router(web_router)


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browser tab / address-bar icon (browsers request /favicon.ico by default)."""
    return FileResponse(ICONS_DIR / "favicon.ico", media_type="image/x-icon")


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
        if "season_stats_json" not in cols:
            statements.append("ALTER TABLE players ADD COLUMN season_stats_json TEXT DEFAULT '{}'")
        if "photo" not in cols:
            statements.append("ALTER TABLE players ADD COLUMN photo VARCHAR(64) DEFAULT ''")
        if statements:
            with engine.begin() as conn:
                for stmt in statements:
                    conn.execute(text(stmt))
    if "leagues" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("leagues")}
        if "league_type" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE leagues ADD COLUMN league_type VARCHAR(16) DEFAULT 'classic'"))
        if "owner_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE leagues ADD COLUMN owner_id INTEGER"))
    if "squad_picks" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("squad_picks")}
        if "is_vice_captain" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE squad_picks ADD COLUMN is_vice_captain INTEGER DEFAULT 0"))
        if "captain_armed" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE squad_picks ADD COLUMN captain_armed INTEGER DEFAULT 0"))
    if "clubs" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("clubs")}
        if "kit_code" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clubs ADD COLUMN kit_code INTEGER"))
        if "fpl_team_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clubs ADD COLUMN fpl_team_id INTEGER"))
        if "api_football_team_id" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE clubs ADD COLUMN api_football_team_id INTEGER"))
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
    if "managers" in tables:
        cols = {c["name"] for c in inspect(engine).get_columns("managers")}
        if "email" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE managers ADD COLUMN email VARCHAR(120) DEFAULT ''"))
        if "password_hash" not in cols:
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE managers ADD COLUMN password_hash VARCHAR(255) DEFAULT ''"))


@app.on_event("startup")
def on_startup() -> None:
    if settings.secret_key == _DEFAULT_SECRET_KEY and not settings.debug:
        logger.warning(
            "INSECURE: SECRET_KEY is still the built-in default while DEBUG is False. "
            "Set a unique SECRET_KEY in the environment before serving real users."
        )
    # Never wipe existing data on deploy. Only drop when explicitly requested.
    if settings.reset_db_on_startup:
        Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    _ensure_schema_patches()
    db_kind = "postgres" if "postgresql" in settings.database_url else "sqlite"
    logger.info("database backend: %s", db_kind)
    if db_kind == "sqlite":
        logger.warning(
            "SQLite is wiped on every Render redeploy. "
            "Set DATABASE_URL to your Supabase Postgres URI so accounts persist."
        )
    db = SessionLocal()
    try:
        seed_if_empty(db, force_fpl_sync=False)
        from app.services import league as league_svc
        from app.services import live_scoring as live_svc

        n = league_svc.backfill_null_league_owners(db)
        if n:
            logger.info("backfilled owner_id on %s legacy league(s)", n)
        cleared = live_svc.clear_demo_scoring_data(db)
        if cleared.get("match_events_deleted"):
            logger.info(
                "cleared demo scoring data · events=%s scores=%s gws=%s",
                cleared.get("match_events_deleted"),
                cleared.get("manager_scores_deleted"),
                cleared.get("gameweek_ids"),
            )
        from app.services import standings as standings_svc

        purged = standings_svc.purge_h2h_matches_before_kickoff(db)
        if purged.get("deleted"):
            logger.info(
                "purged %s pre-kickoff H2HMatch row(s) for circle-method regenerate",
                purged["deleted"],
            )
    finally:
        db.close()
    from app.services.auto_score import start_auto_scorer

    start_auto_scorer(interval_sec=120.0)
