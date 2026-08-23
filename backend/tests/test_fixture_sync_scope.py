"""Scoped FPL fixture sync — never upsert 380 rows on the live hot path."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.services import fixtures as fixtures_svc


def test_fpl_row_is_active_live_and_kickoff_passed():
    now = datetime(2026, 8, 22, 15, 30, tzinfo=timezone.utc)
    assert fixtures_svc._fpl_row_is_active(
        {"started": True, "finished": False, "kickoff_time": "2026-08-22T14:00:00Z"},
        now=now,
    )
    assert not fixtures_svc._fpl_row_is_active(
        {"started": True, "finished": True, "kickoff_time": "2026-08-22T14:00:00Z"},
        now=now,
    )
    assert not fixtures_svc._fpl_row_is_active(
        {
            "started": False,
            "finished": False,
            "kickoff_time": "2026-08-22T17:00:00Z",
        },
        now=now,
    )
    # Kickoff just passed but FPL started flag still false — still active.
    assert fixtures_svc._fpl_row_is_active(
        {
            "started": False,
            "finished": False,
            "finished_provisional": False,
            "kickoff_time": "2026-08-22T15:25:00Z",
        },
        now=now,
    )


def test_sync_fixtures_only_active_skips_finished_and_far_upcoming(db_session=None):
    from sqlalchemy import text

    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.models import Club, Fixture
    from app.services.seed import seed_if_empty

    settings.reset_db_on_startup = False
    Base.metadata.create_all(bind=engine)
    # Test DBs may predate Fixture.minutes — mirror app startup patch.
    with engine.begin() as conn:
        cols = {c["name"] for c in __import__("sqlalchemy").inspect(engine).get_columns("fixtures")}
        if "minutes" not in cols:
            conn.execute(text("ALTER TABLE fixtures ADD COLUMN minutes INTEGER"))
    db = SessionLocal()
    try:
        seed_if_empty(db)
        for i, club in enumerate(db.query(Club).order_by(Club.code).all(), start=1):
            if not club.fpl_team_id:
                club.fpl_team_id = i
        ars = db.query(Club).filter(Club.code == "ARS").one()
        mun = db.query(Club).filter(Club.code == "MUN").one()
        liv = db.query(Club).filter(Club.code == "LIV").one()
        che = db.query(Club).filter(Club.code == "CHE").one()
        db.commit()

        now = datetime.now(timezone.utc)
        rows = [
            {
                "id": 88001,
                "event": 1,
                "team_h": int(ars.fpl_team_id),
                "team_a": int(mun.fpl_team_id),
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "kickoff_time": (now - timedelta(minutes=20)).isoformat().replace("+00:00", "Z"),
                "started": True,
                "finished": False,
                "team_h_score": 1,
                "team_a_score": 0,
                "stats": [],
            },
            {
                "id": 88002,
                "event": 1,
                "team_h": int(liv.fpl_team_id),
                "team_a": int(che.fpl_team_id),
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "kickoff_time": (now - timedelta(hours=3)).isoformat().replace("+00:00", "Z"),
                "started": True,
                "finished": True,
                "finished_provisional": True,
                "team_h_score": 2,
                "team_a_score": 1,
                "stats": [],
            },
            {
                "id": 88003,
                "event": 1,
                "team_h": int(ars.fpl_team_id),
                "team_a": int(liv.fpl_team_id),
                "team_h_difficulty": 3,
                "team_a_difficulty": 3,
                "kickoff_time": (now + timedelta(hours=5)).isoformat().replace("+00:00", "Z"),
                "started": False,
                "finished": False,
                "team_h_score": None,
                "team_a_score": None,
                "stats": [],
            },
        ]
        out = fixtures_svc.sync_fixtures(db, rows=rows, event=1, only_active=True)
        assert out["fixtures"] == 1
        assert out["skipped_inactive"] == 2
        assert out["fetched"] == 3
        assert db.query(Fixture).filter(Fixture.fpl_id == 88001).one().started == 1
        assert db.query(Fixture).filter(Fixture.fpl_id == 88002).one_or_none() is None
        assert db.query(Fixture).filter(Fixture.fpl_id == 88003).one_or_none() is None
    finally:
        db.close()


def test_fetch_fixtures_passes_event_param():
    captured: dict = {}

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return [{"id": 1, "event": 1}]

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = params
            return _Resp()

    with patch("app.services.fixtures.httpx.Client", _Client):
        rows = fixtures_svc.fetch_fixtures(event=1)
    assert rows == [{"id": 1, "event": 1}]
    assert captured["params"] == {"event": 1}


def test_refresh_fixtures_default_scope_is_live():
    from app.config import settings
    from app.db import Base, SessionLocal, engine
    from app.models import Gameweek
    from app.services.seed import seed_if_empty

    settings.reset_db_on_startup = False
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
        gw = db.query(Gameweek).filter(Gameweek.is_current == 1).one()
        with patch.object(fixtures_svc, "sync_fixtures", return_value={"fixtures": 2, "fetched": 10}) as sync:
            info = fixtures_svc.refresh_fixtures(db)
        assert info["scope"] == "live"
        sync.assert_called_once()
        kwargs = sync.call_args.kwargs
        assert kwargs.get("event") == int(gw.number)
        assert kwargs.get("only_active") is True
    finally:
        db.close()
