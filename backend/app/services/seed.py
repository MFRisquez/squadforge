"""Seed league + prefer live FPL catalogue (weekly-refreshable)."""

from __future__ import annotations

import secrets
import string

from sqlalchemy.orm import Session

from app.models import Club, Gameweek, League, Player
from app.services.fpl_sync import sync_from_fpl


def invite_code(length: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def ensure_demo_league(db: Session) -> None:
    if db.query(League).count() == 0:
        db.add(League(name="Friends League", invite_code="FORGE1"))
        db.commit()


def seed_demo_fallback(db: Session) -> None:
    """Tiny offline catalogue only if FPL sync is unavailable."""
    if db.query(Club).count() == 0:
        for code, name in [
            ("ARS", "Arsenal"),
            ("LIV", "Liverpool"),
            ("MCI", "Man City"),
            ("CHE", "Chelsea"),
            ("MUN", "Man Utd"),
            ("TOT", "Spurs"),
            ("NEW", "Newcastle"),
            ("AVL", "Aston Villa"),
            ("BHA", "Brighton"),
            ("WHU", "West Ham"),
            ("CRY", "Crystal Palace"),
            ("FUL", "Fulham"),
            ("BRE", "Brentford"),
            ("EVE", "Everton"),
            ("WOL", "Wolves"),
            ("NFO", "Nott'm Forest"),
            ("BOU", "Bournemouth"),
            ("WCL", "West Club"),
            ("LEE", "Leeds"),
            ("SUN", "Sunderland"),
        ]:
            db.add(Club(code=code, name=name))

    if db.query(Player).count() == 0:
        # Spread clubs so a legal 15 (max 3/club) can be built offline
        demo = [
            ("dgk-0", "Demo GK 1", "GK", "ARS", 4.5),
            ("dgk-1", "Demo GK 2", "GK", "TOT", 4.5),
            ("ddef-0", "Demo DEF 1", "DEF", "LIV", 4.5),
            ("ddef-1", "Demo DEF 2", "DEF", "LIV", 4.5),
            ("ddef-2", "Demo DEF 3", "DEF", "LIV", 4.5),
            ("ddef-3", "Demo DEF 4", "DEF", "NEW", 4.5),
            ("ddef-4", "Demo DEF 5", "DEF", "AVL", 4.5),
            ("dmid-0", "Demo MID 1", "MID", "MCI", 5.0),
            ("dmid-1", "Demo MID 2", "MID", "MCI", 5.0),
            ("dmid-2", "Demo MID 3", "MID", "MCI", 5.0),
            ("dmid-3", "Demo MID 4", "MID", "BHA", 5.0),
            ("dmid-4", "Demo MID 5", "MID", "WHU", 5.0),
            ("datt-0", "Demo ATT 1", "ATT", "CHE", 5.5),
            ("datt-1", "Demo ATT 2", "ATT", "CHE", 5.5),
            ("datt-2", "Demo ATT 3", "ATT", "MUN", 5.5),
        ]
        for ext, name, pos, team, price in demo:
            db.add(Player(external_id=ext, name=name, position=pos, team_code=team, price=price))

    if db.query(Gameweek).count() == 0:
        for n in range(1, 39):
            db.add(Gameweek(number=n, name=f"Gameweek {n}", status="upcoming", is_current=1 if n == 1 else 0))
    db.commit()


def seed_if_empty(db: Session, *, force_fpl_sync: bool = False) -> dict:
    ensure_demo_league(db)
    fpl_players = db.query(Player).filter(Player.external_id.like("fpl-%")).count()
    should_sync = force_fpl_sync or fpl_players < 200
    info: dict = {"source": "existing"}
    if should_sync:
        try:
            info = sync_from_fpl(db)
            info["source"] = "fpl"
        except Exception as exc:  # network / API issues
            seed_demo_fallback(db)
            info = {"source": "demo_fallback", "error": str(exc)}
    else:
        # Keep gameweeks/league healthy even if we skip full sync
        if db.query(Gameweek).count() == 0:
            seed_demo_fallback(db)
    ensure_demo_league(db)
    return info
