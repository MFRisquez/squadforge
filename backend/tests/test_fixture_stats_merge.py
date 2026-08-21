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
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
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
                stats_json=json.dumps(
                    [
                        {
                            "identifier": "goals_scored",
                            "a": [],
                            "h": [{"element": fpl_id, "value": 1}],
                        },
                        {
                            "identifier": "assists",
                            "a": [],
                            "h": [],
                        },
                    ]
                ),
            )
        )
        db.commit()

        n = live_svc.merge_fixture_stats_into_events(db, gw)
        assert n >= 1
        db.commit()
        metrics = live_svc.metrics_for_player(db, gw.id, player.id)
        assert metrics.get("goals") == 1.0
        assert metrics.get("minutes") == 1.0  # appearance unlocked
    finally:
        db.close()
