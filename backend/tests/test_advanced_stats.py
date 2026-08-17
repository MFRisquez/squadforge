"""API-Football advanced stats ingest (mocked — no live network)."""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Club, Gameweek, MatchEvent, Player
from app.services import advanced_stats as adv


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _reset():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_normalize_name_strips_fc_and_accents():
    assert adv._normalize_name("Atlético FC") == "atletico"
    assert adv._normalize_name("AFC Bournemouth") == "bournemouth"


def test_ingest_skips_without_api_key():
    _reset()
    db = SessionLocal()
    try:
        old = settings.api_football_key
        settings.api_football_key = ""
        gw = Gameweek(number=1, name="GW1", is_current=1)
        db.add(gw)
        db.commit()
        db.refresh(gw)
        out = adv.ingest_advanced_stats(db, gw)
        assert out == {"skipped": "no_api_key"}
    finally:
        settings.api_football_key = old
        db.close()


def test_ensure_club_team_ids_maps_and_is_idempotent():
    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        db.add(Club(code="ARS", name="Arsenal"))
        db.add(Club(code="CHE", name="Chelsea"))
        db.commit()

        fake_teams = {
            "response": [
                {"team": {"id": 42, "name": "Arsenal"}},
                {"team": {"id": 49, "name": "Chelsea FC"}},
            ]
        }
        with patch.object(adv, "_api_get", return_value=fake_teams) as mocked:
            first = adv.ensure_club_team_ids(db)
            assert first["updated"] == 2
            assert mocked.call_count == 1
            second = adv.ensure_club_team_ids(db)
            assert second["skipped"] == "already_mapped"
            assert mocked.call_count == 1

        clubs = {c.code: c.api_football_team_id for c in db.query(Club).all()}
        assert clubs["ARS"] == 42
        assert clubs["CHE"] == 49
    finally:
        settings.api_football_key = old_key
        db.close()


def test_parse_and_ingest_writes_api_football_metrics():
    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        ars = Club(code="ARS", name="Arsenal", api_football_team_id=42)
        che = Club(code="CHE", name="Chelsea", api_football_team_id=49)
        db.add_all([ars, che])
        gw = Gameweek(number=3, name="GW3", is_current=1)
        db.add(gw)
        db.flush()
        player = Player(
            external_id="1001",
            name="Bukayo Saka",
            position="MID",
            team_code="ARS",
            price=10.0,
        )
        db.add(player)
        db.commit()
        db.refresh(gw)
        db.refresh(player)

        def fake_get(path, params=None, **kwargs):
            if path == "/fixtures":
                return {
                    "response": [
                        {
                            "fixture": {"id": 999},
                            "teams": {"home": {"id": 42}, "away": {"id": 49}},
                        }
                    ]
                }
            if path == "/fixtures/players":
                return {
                    "response": [
                        {
                            "team": {"id": 42},
                            "players": [
                                {
                                    "player": {"name": "B. Saka"},
                                    "statistics": [
                                        {
                                            "tackles": {
                                                "total": 4,
                                                "interceptions": 2,
                                                "blocks": 1,
                                            },
                                            "passes": {"key": 3},
                                            "shots": {"on": 2},
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            return {"response": []}

        with patch.object(adv, "_api_get", side_effect=fake_get):
            out = adv.ingest_advanced_stats(db, gw, force=True)

        assert out.get("players_updated") == 1
        assert out.get("fixtures_processed") == 1
        rows = {
            r.metric: r
            for r in db.query(MatchEvent)
            .filter(MatchEvent.player_id == player.id, MatchEvent.gameweek_id == gw.id)
            .all()
        }
        assert rows["tackles"].value == 4
        assert rows["interceptions"].value == 2
        assert rows["blocks"].value == 1
        assert rows["key_passes"].value == 3
        assert rows["shots_on_target"].value == 2
        assert rows["tackles"].source == "api_football"

        # Recent-fetch guard
        with patch.object(adv, "_api_get", side_effect=fake_get) as mocked:
            skipped = adv.ingest_advanced_stats(db, gw, force=False)
            assert skipped == {"skipped": "recently_fetched"}
            assert mocked.call_count == 0
    finally:
        settings.api_football_key = old_key
        db.close()


def test_ingest_tolerates_fixture_failure():
    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        db.add(Club(code="ARS", name="Arsenal", api_football_team_id=42))
        db.add(Club(code="CHE", name="Chelsea", api_football_team_id=49))
        gw = Gameweek(number=1, name="GW1", is_current=1)
        db.add(gw)
        db.commit()
        db.refresh(gw)

        def fake_get(path, params=None, **kwargs):
            if path == "/fixtures":
                return {
                    "response": [
                        {
                            "fixture": {"id": 1},
                            "teams": {"home": {"id": 42}, "away": {"id": 49}},
                        },
                        {
                            "fixture": {"id": 2},
                            "teams": {"home": {"id": 49}, "away": {"id": 42}},
                        },
                    ]
                }
            raise RuntimeError("boom")

        with patch.object(adv, "_api_get", side_effect=fake_get):
            out = adv.ingest_advanced_stats(db, gw, force=True)
        assert out.get("fixtures_failed") == 2
        assert out.get("players_updated") == 0
        assert "error" not in out
    finally:
        settings.api_football_key = old_key
        db.close()
