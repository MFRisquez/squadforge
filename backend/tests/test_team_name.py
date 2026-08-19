"""Home team-name edit window (locked once GW1 starts)."""

from __future__ import annotations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Fixture, Gameweek, Manager
from app.services import deadline as deadline_svc
from app.services import league as league_svc
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


def test_team_name_editable_before_gw1_kickoff():
    db = SessionLocal()
    try:
        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw1.is_current = 1
        db.query(Gameweek).filter(Gameweek.number != 1).update({"is_current": 0})
        db.query(Fixture).filter(Fixture.gameweek_number == 1).update(
            {"started": 0, "finished": 0}
        )
        db.commit()
        assert deadline_svc.team_name_editable(db) is True
    finally:
        db.close()


def test_team_name_locked_after_gw1_fixture_starts():
    db = SessionLocal()
    try:
        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw1.is_current = 1
        db.query(Gameweek).filter(Gameweek.number != 1).update({"is_current": 0})
        fx = db.query(Fixture).filter(Fixture.gameweek_number == 1).first()
        if fx is None:
            fx = Fixture(
                fpl_id=900001,
                gameweek_number=1,
                home_club_code="ARS",
                away_club_code="AVL",
                started=1,
                finished=0,
            )
            db.add(fx)
        else:
            fx.started = 1
            fx.finished = 0
        db.commit()
        assert deadline_svc.team_name_editable(db) is False
    finally:
        db.close()


def test_update_team_name_persists():
    db = SessionLocal()
    try:
        m = league_svc.register_manager(
            db,
            display_name="TeamNameUser",
            password="secret12",
            email="teamname@example.com",
            team_name="Old XI",
        )
        league_svc.update_team_name(db, m, "Forge United")
        row = db.query(Manager).filter(Manager.id == m.id).one()
        assert row.team_name == "Forge United"
    finally:
        db.close()
