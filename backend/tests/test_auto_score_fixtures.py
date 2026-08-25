"""Auto-scorer keeps Fixture.started/finished fresh (no manual Refresh needed)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Club, Fixture, Gameweek
from app.services import auto_score as auto_svc
from app.services import fixtures as fixtures_svc
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


def test_auto_score_refreshes_fixture_started_before_scoring():
    """Daemon path must call refresh_fixtures so live matches leave 'upcoming'."""
    db = SessionLocal()
    try:
        auto_svc._last_run_at = 0.0
        db.query(Gameweek).update({"is_current": 0})
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        gw.is_current = 1
        gw.status = "live"
        # Ensure clubs have FPL team ids so sync can map rows.
        for i, club in enumerate(db.query(Club).order_by(Club.code).all(), start=1):
            if not club.fpl_team_id:
                club.fpl_team_id = i
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        # Also clear finished flags on any other leftover rows.
        db.query(Fixture).update({"finished": 0})
        db.add(
            Fixture(
                fpl_id=99001,
                gameweek_number=1,
                home_club_code="ARS",
                away_club_code="MUN",
                kickoff_at="2026-08-21T19:00:00Z",
                started=0,
                finished=0,
            )
        )
        db.commit()

        ars = db.query(Club).filter(Club.code == "ARS").one()
        mun = db.query(Club).filter(Club.code == "MUN").one()
        fake_rows = [
            {
                "id": 99001,
                "event": 1,
                "team_h": int(ars.fpl_team_id),
                "team_a": int(mun.fpl_team_id),
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "kickoff_time": "2026-08-21T19:00:00Z",
                "started": True,
                "finished": False,
                "finished_provisional": False,
                "team_h_score": 1,
                "team_a_score": 0,
                "stats": [],
            }
        ]

        refresh_calls: list[dict] = []

        def _tracking_refresh(session, **kwargs):
            out = fixtures_svc.sync_fixtures(session, rows=fake_rows)
            refresh_calls.append({"out": out, "kwargs": kwargs})
            return out

        with patch.object(fixtures_svc, "refresh_fixtures", side_effect=_tracking_refresh):
            with patch(
                "app.services.live_scoring.run_gameweek_scoring",
                return_value={
                    "gameweek": 1,
                    "ingest": {"source": "test", "players_updated": 1},
                    "managers_scored": 0,
                    "players_scored": 0,
                },
            ):
                # Import after patch target is ready — auto_score imports fixtures inside try.
                auto_svc._last_gw_sweep_at = 0.0
                summary = auto_svc.maybe_score_locked_gw(force=True)

        assert summary is not None
        assert refresh_calls, "auto-scorer must call refresh_fixtures every cycle"
        assert refresh_calls[0]["kwargs"].get("scope") in {"live", "gw"}
        fx = db.query(Fixture).filter(Fixture.fpl_id == 99001).one()
        assert fx.started == 1
        assert fx.finished == 0
        assert fx.home_score == 1
    finally:
        db.close()


def test_refresh_fixtures_failure_does_not_block_auto_score():
    db = SessionLocal()
    try:
        auto_svc._last_run_at = 0.0
        db.query(Gameweek).update({"is_current": 0})
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=1))
            .isoformat()
            .replace("+00:00", "Z")
        )
        gw.is_current = 1
        gw.status = "live"
        # Keep advance from jumping off GW1 mid-test.
        db.query(Fixture).filter(Fixture.gameweek_number == 1).update({"finished": 0})
        db.commit()

        def _boom(_session, **_kwargs):
            raise RuntimeError("FPL fixtures down")

        with patch("app.services.fixtures.refresh_fixtures", side_effect=_boom):
            with patch(
                "app.services.live_scoring.run_gameweek_scoring",
                return_value={
                    "gameweek": 1,
                    "ingest": {"source": "test"},
                    "managers_scored": 0,
                    "players_scored": 0,
                },
            ) as scored:
                summary = auto_svc.maybe_score_locked_gw(force=True)
        assert summary is not None
        assert scored.called
    finally:
        db.close()
