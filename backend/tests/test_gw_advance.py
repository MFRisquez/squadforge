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
