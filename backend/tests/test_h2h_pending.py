"""H2H must stay pending until PL fixtures in the GW have started."""

from __future__ import annotations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Fixture, Gameweek, H2HMatch, ManagerGameweekScore
from app.services import league as league_svc
from app.services import live_scoring as live_svc
from app.services import standings as standings_svc
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


def test_resolve_h2h_stays_pending_before_kickoff():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="H2HPendA",
            password="secret12",
            email="h2hpenda@example.com",
            team_name="Pend A",
        )
        b = league_svc.register_manager(
            db,
            display_name="H2HPendB",
            password="secret12",
            email="h2hpendb@example.com",
            team_name="Pend B",
        )
        league = league_svc.create_league(db, "H2H Pending", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        db.query(Fixture).filter(Fixture.gameweek_number == 1).update(
            {"started": 0, "finished": 0}
        )
        # Simulate premature 0–0 settlement (old bug).
        matches = standings_svc.ensure_h2h_pairings(db, league, gw)
        assert matches
        for m in matches:
            m.home_points = 0.0
            m.away_points = 0.0
            m.result = "draw"
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gw.id, total=0))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gw.id, total=0))
        db.commit()

        live_svc.resolve_h2h(db, gw)
        for m in db.query(H2HMatch).filter(H2HMatch.league_id == league.id).all():
            assert m.result == "pending"

        rows, _ = standings_svc.h2h_standings(db, league, gw)
        me = next(r for r in rows if r["manager"].id == a.id)
        assert me["draws"] == 0
        assert me["played"] == 0
    finally:
        db.close()


def test_resolve_h2h_settles_after_fixture_starts():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="H2HLiveA",
            password="secret12",
            email="h2hlivea@example.com",
            team_name="Live A",
        )
        b = league_svc.register_manager(
            db,
            display_name="H2HLiveB",
            password="secret12",
            email="h2hliveb@example.com",
            team_name="Live B",
        )
        league = league_svc.create_league(db, "H2H Live", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        fx = db.query(Fixture).filter(Fixture.gameweek_number == 1).first()
        if fx is None:
            fx = Fixture(
                fpl_id=910001,
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
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gw.id, total=12))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gw.id, total=8))
        db.commit()

        live_svc.resolve_h2h(db, gw)
        match = (
            db.query(H2HMatch)
            .filter(H2HMatch.league_id == league.id, H2HMatch.gameweek_id == gw.id)
            .first()
        )
        assert match is not None
        assert match.result in {"home", "away"}
        assert match.result != "pending"
    finally:
        db.close()
