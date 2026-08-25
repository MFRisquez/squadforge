"""Fase 2: League News timing (post when finished, pre within 48h)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import (
    Fixture,
    Gameweek,
    League,
    LeagueNewsEdition,
    Manager,
    Membership,
)
from app.services import league_news as news_svc
from app.services.seed import seed_if_empty


@pytest.fixture()
def db():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_if_empty(session)
        yield session
    finally:
        session.close()


def _league(db) -> League:
    league = League(name="Timing League", invite_code="TIME01", league_type="classic")
    db.add(league)
    db.commit()
    db.refresh(league)
    m = Manager(display_name="Timer", pin="1111", team_name="Timers")
    db.add(m)
    db.commit()
    db.refresh(m)
    db.add(Membership(league_id=league.id, manager_id=m.id))
    db.commit()
    return league


def test_all_fixtures_finished(db):
    gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
    db.add(
        Fixture(
            fpl_id=90001,
            gameweek_number=1,
            home_club_code="ARS",
            away_club_code="CHE",
            finished=0,
        )
    )
    db.commit()
    assert news_svc.all_fixtures_finished(db, gw) is False
    fx = db.query(Fixture).filter(Fixture.fpl_id == 90001).one()
    fx.finished = 1
    db.commit()
    assert news_svc.all_fixtures_finished(db, gw) is True


def test_gw_ready_for_post_when_season_advanced(db):
    gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
    gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
    gw1.status = "live"
    gw1.is_current = 0
    gw2.status = "live"
    gw2.is_current = 1
    # One unfinished fixture would block all_fixtures_finished
    db.add(
        Fixture(
            fpl_id=90011,
            gameweek_number=1,
            home_club_code="ARS",
            away_club_code="CHE",
            finished=0,
        )
    )
    db.commit()
    assert news_svc.all_fixtures_finished(db, gw1) is False
    assert news_svc.gw_ready_for_post(db, gw1) is True
    gw = db.query(Gameweek).filter(Gameweek.number == 2).one()
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    gw.deadline_at = (now + timedelta(hours=24)).isoformat().replace("+00:00", "Z")
    gw.status = "upcoming"
    db.commit()
    assert news_svc.pre_gw_window_open(gw, now=now, hours=48) is True
    gw.deadline_at = (now + timedelta(hours=72)).isoformat().replace("+00:00", "Z")
    db.commit()
    assert news_svc.pre_gw_window_open(gw, now=now, hours=48) is False


def test_resolve_current_prefers_pre_then_post(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    league = _league(db)
    gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
    gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
    now = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    gw1.status = "finished"
    gw2.status = "upcoming"
    gw2.deadline_at = (now + timedelta(hours=12)).isoformat().replace("+00:00", "Z")
    db.add(
        LeagueNewsEdition(
            league_id=league.id,
            edition_type="post_gw",
            gameweek_number=1,
            content_json=json.dumps({"title": "Post 1", "stories": []}),
        )
    )
    db.commit()

    view = news_svc.resolve_current_edition(db, league)
    assert view is not None
    assert view["title"] == "Post 1"
    assert view["edition_type"] == "post_gw"

    db.add(
        LeagueNewsEdition(
            league_id=league.id,
            edition_type="pre_gw",
            gameweek_number=2,
            content_json=json.dumps({"title": "Pre 2", "stories": []}),
        )
    )
    db.commit()
    view2 = news_svc.resolve_current_edition(db, league)
    assert view2["title"] == "Pre 2"
    assert view2["edition_type"] == "pre_gw"

    # Once post for GW2 exists, it wins
    db.add(
        LeagueNewsEdition(
            league_id=league.id,
            edition_type="post_gw",
            gameweek_number=2,
            content_json=json.dumps({"title": "Post 2", "stories": []}),
        )
    )
    db.commit()
    view3 = news_svc.resolve_current_edition(db, league)
    assert view3["title"] == "Post 2"


def test_maybe_generate_due_editions_post(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    league = _league(db)
    gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
    gw.status = "finished"
    db.add(
        Fixture(
            fpl_id=90002,
            gameweek_number=1,
            home_club_code="ARS",
            away_club_code="MCI",
            finished=1,
        )
    )
    db.commit()

    fake = {"title": "Auto Post", "kicker": "k", "stories": [{"headline": "h", "body": "b"}]}
    with patch.object(news_svc, "build_post_gw_package", return_value={
        "edition_type": "post_gw",
        "league_id": league.id,
        "gameweek_number": 1,
        "stories": [{"kind": "rank_move", "drama": 3, "player_id": None}],
    }), patch.object(news_svc, "call_gemini_for_edition", return_value=fake):
        result = news_svc.maybe_generate_due_editions(db)

    assert result["ok"] is True
    row = (
        db.query(LeagueNewsEdition)
        .filter(
            LeagueNewsEdition.league_id == league.id,
            LeagueNewsEdition.edition_type == "post_gw",
            LeagueNewsEdition.gameweek_number == 1,
        )
        .one_or_none()
    )
    assert row is not None
    assert json.loads(row.content_json)["title"] == "Auto Post"
    # Second call does not regenerate
    with patch.object(news_svc, "call_gemini_for_edition") as mock_call:
        news_svc.maybe_generate_due_editions(db)
        mock_call.assert_not_called()
