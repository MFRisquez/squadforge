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
        demo = []
        for i in range(2):
            demo.append((f"dgk-{i}", f"Demo GK {i+1}", "GK", "ARS", 4.5))
        for i in range(5):
            demo.append((f"ddef-{i}", f"Demo DEF {i+1}", "DEF", "LIV", 4.5))
        for i in range(5):
            demo.append((f"dmid-{i}", f"Demo MID {i+1}", "MID", "MCI", 5.0))
        for i in range(3):
            demo.append((f"datt-{i}", f"Demo ATT {i+1}", "ATT", "CHE", 5.5))
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
