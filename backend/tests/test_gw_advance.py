"""Current GW rolls forward when all fixtures are finished."""

from __future__ import annotations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Fixture, Gameweek
from app.services import squad as squad_svc
from app.services.seed import seed_if_empty


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def test_maybe_advance_finished_gameweek_rolls_to_next():
    db = SessionLocal()
    try:
        g1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        g2 = db.query(Gameweek).filter(Gameweek.number == 2).one_or_none()
        if g2 is None:
            g2 = Gameweek(number=2, name="GW2", status="upcoming", is_current=0)
            db.add(g2)
            db.flush()
        db.query(Gameweek).update({"is_current": 0})
        g1.is_current = 1
        g1.status = "live"
        g2.is_current = 0
        g2.status = "upcoming"
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        db.add(
            Fixture(
                fpl_id=91001,
                gameweek_number=1,
                home_club_code="ARS",
                away_club_code="CHE",
                started=1,
                finished=1,
                home_score=2,
                away_score=1,
            )
        )
        db.add(
            Fixture(
                fpl_id=91002,
                gameweek_number=1,
                home_club_code="LIV",
                away_club_code="MCI",
                started=1,
                finished=1,
                home_score=0,
                away_score=0,
            )
        )
        db.commit()

        assert squad_svc.maybe_advance_finished_gameweek(db) is True
        db.refresh(g1)
        db.refresh(g2)
        assert g1.is_current == 0
        assert g1.status == "finished"
        assert g2.is_current == 1
        assert g2.status == "live"

        # Seed may leave finished fixtures on GW2 — clear them so the next
        # call is a true no-op (otherwise we cascade GW2 → GW3).
        db.query(Fixture).filter(Fixture.gameweek_number == 2).delete()
        db.commit()

        # Idempotent once already advanced
        assert squad_svc.maybe_advance_finished_gameweek(db) is False
        cur = squad_svc.current_gameweek(db)
        assert cur.number == 2
    finally:
        db.close()


def test_does_not_advance_while_fixtures_unfinished():
    db = SessionLocal()
    try:
        g1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        g2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
        db.query(Gameweek).update({"is_current": 0})
        g1.is_current = 1
        g1.status = "live"
        g2.is_current = 0
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        db.add(
            Fixture(
                fpl_id=91011,
                gameweek_number=1,
                home_club_code="ARS",
                away_club_code="CHE",
                started=1,
                finished=0,
                home_score=1,
                away_score=0,
            )
        )
        db.commit()
        assert squad_svc.maybe_advance_finished_gameweek(db) is False
        assert g1.is_current == 1
    finally:
        db.close()


def test_sync_provisional_marks_finished_and_advances_gw():
    """FPL provisional → local finished=1 → auto-roll to next GW (unlock transfers)."""
    from datetime import datetime, timedelta, timezone
    from unittest.mock import patch

    from app.models import Club
    from app.services import fixtures as fixtures_svc

    db = SessionLocal()
    try:
        g1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        g2 = db.query(Gameweek).filter(Gameweek.number == 2).one_or_none()
        if g2 is None:
            g2 = Gameweek(number=2, name="GW2", status="upcoming", is_current=0)
            db.add(g2)
            db.flush()
        db.query(Gameweek).update({"is_current": 0})
        g1.is_current = 1
        g1.status = "live"
        g2.is_current = 0
        g2.status = "upcoming"
        for i, club in enumerate(db.query(Club).order_by(Club.code).all(), start=1):
            if not club.fpl_team_id:
                club.fpl_team_id = i
        ars = db.query(Club).filter(Club.code == "ARS").one()
        che = db.query(Club).filter(Club.code == "CHE").one()
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        db.commit()

        now = datetime.now(timezone.utc)
        rows = [
            {
                "id": 92001,
                "event": 1,
                "team_h": int(ars.fpl_team_id),
                "team_a": int(che.fpl_team_id),
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "kickoff_time": (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
                "started": True,
                "finished": False,
                "finished_provisional": True,
                "minutes": 90,
                "team_h_score": 2,
                "team_a_score": 1,
                "stats": [],
            }
        ]
        fixtures_svc.sync_fixtures(db, rows=rows, event=1, only_active=True)
        fx = db.query(Fixture).filter(Fixture.fpl_id == 92001).one()
        assert fx.finished == 1
        assert squad_svc.maybe_advance_finished_gameweek(db) is True
        db.refresh(g1)
        db.refresh(g2)
        assert g1.is_current == 0
        assert g1.status == "finished"
        assert g2.is_current == 1
        assert g2.status == "live"
    finally:
        db.close()
