"""Merge fixture stats_json G/A into MatchEvents when live lags."""

from __future__ import annotations

import json

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Fixture, Gameweek, MatchEvent, Player
from app.services import live_scoring as live_svc
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


def test_merge_fixture_stats_adds_goal_when_live_blank():
    db = SessionLocal()
    try:
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        player = (
            db.query(Player)
            .filter(Player.external_id.like("fpl-%"))
            .order_by(Player.id)
            .first()
        )
        assert player is not None
        fpl_id = int(player.external_id.split("-", 1)[1])
        # Wipe any prior events for this player/GW
        db.query(MatchEvent).filter(
            MatchEvent.gameweek_id == gw.id, MatchEvent.player_id == player.id
        ).delete()
        # Upsert one fixture — do not wipe all GW1 rows (breaks sibling H2H tests).
        fx = db.query(Fixture).filter(Fixture.fpl_id == 991001).one_or_none()
        stats_json = json.dumps(
            [
                {
                    "identifier": "goals_scored",
                    "a": [],
                    "h": [{"element": fpl_id, "value": 1}],
                },
                {"identifier": "assists", "a": [], "h": []},
            ]
        )
        if fx is None:
            db.add(
                Fixture(
                    fpl_id=991001,
                    gameweek_number=1,
                    home_club_code=player.team_code or "ARS",
                    away_club_code="AVL",
                    started=1,
                    finished=0,
                    home_score=1,
                    away_score=0,
                    stats_json=stats_json,
                )
            )
        else:
            fx.home_club_code = player.team_code or "ARS"
            fx.away_club_code = "AVL"
            fx.started = 1
            fx.finished = 0
            fx.home_score = 1
            fx.away_score = 0
            fx.stats_json = stats_json
        db.commit()

        n = live_svc.merge_fixture_stats_into_events(db, gw)
        assert n >= 1
        db.commit()
        metrics = live_svc.metrics_for_player(db, gw.id, player.id)
        assert metrics.get("goals") == 1.0
        assert metrics.get("minutes") == 1.0  # appearance unlocked
    finally:
        db.close()


def test_merge_runs_even_if_fixture_refresh_fails(monkeypatch):
    """Fixture refresh errors must not skip merge of existing stats_json."""
    db = SessionLocal()
    try:
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        players = (
            db.query(Player)
            .filter(Player.external_id.like("fpl-%"))
            .order_by(Player.id)
            .limit(2)
            .all()
        )
        assert len(players) >= 2
        # Use a different player than the first test so fixture 991001 does not double-count.
        player = players[1]
        fpl_id = int(player.external_id.split("-", 1)[1])
        db.query(MatchEvent).filter(
            MatchEvent.gameweek_id == gw.id, MatchEvent.player_id == player.id
        ).delete()
        fx = db.query(Fixture).filter(Fixture.fpl_id == 991002).one_or_none()
        stats_json = json.dumps(
            [
                {
                    "identifier": "goals_scored",
                    "a": [],
                    "h": [{"element": fpl_id, "value": 1}],
                },
                {"identifier": "assists", "a": [], "h": []},
            ]
        )
        if fx is None:
            db.add(
                Fixture(
                    fpl_id=991002,
                    gameweek_number=1,
                    home_club_code=player.team_code or "ARS",
                    away_club_code="AVL",
                    started=1,
                    finished=0,
                    home_score=1,
                    away_score=0,
                    stats_json=stats_json,
                )
            )
        else:
            fx.home_club_code = player.team_code or "ARS"
            fx.away_club_code = "AVL"
            fx.started = 1
            fx.finished = 0
            fx.home_score = 1
            fx.away_score = 0
            fx.stats_json = stats_json
        db.commit()

        def boom(*_a, **_k):
            raise RuntimeError("fpl fixtures down")

        monkeypatch.setattr(live_svc.fixtures_svc, "refresh_fixtures", boom)
        monkeypatch.setattr(
            live_svc,
            "_http_get",
            lambda url: {"elements": []} if "/live/" in url else [],
        )

        # Patch the late import inside ingest_fpl_live
        import app.services.fpl_sync as fpl_sync

        monkeypatch.setattr(
            fpl_sync,
            "fetch_bootstrap",
            lambda: {"elements": [], "teams": [], "events": [{"id": 1, "finished": False}]},
        )

        out = live_svc.ingest_fpl_live(db, gw)
        assert out.get("source") == "fpl_live"
        metrics = live_svc.metrics_for_player(db, gw.id, player.id)
        assert metrics.get("goals") == 1.0
        assert metrics.get("minutes") == 1.0
    finally:
        db.close()
