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
    assert adv._normalize_name("Nott'm Forest") == "nottm forest"
    assert adv._normalize_name("Coventry City") == "coventry city"


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

        with patch.object(adv, "_api_get", return_value={"response": []}) as mocked:
            first = adv.ensure_club_team_ids(db)
            assert first["updated"] == 2
            second = adv.ensure_club_team_ids(db)
            assert second["skipped"] == "already_mapped"
            # Known FPL codes use the hardcoded map — no network required.
            assert mocked.call_count == 0

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


def test_team_match_stats_maps_away_first_response():
    """API-Football often returns away block before home — both sides must fill."""
    from app.models import Fixture

    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        adv._team_stats_cache.clear()
        db.add(Club(code="ARS", name="Arsenal", api_football_team_id=42))
        db.add(Club(code="COV", name="Coventry", api_football_team_id=77))
        fx = Fixture(
            fpl_id=88001,
            gameweek_number=1,
            home_club_code="ARS",
            away_club_code="COV",
            kickoff_at="2026-08-21T17:00:00Z",
            started=1,
            finished=0,
        )
        db.add(fx)
        db.commit()
        db.refresh(fx)

        def fake_get(path, params=None, **kwargs):
            if path == "/fixtures":
                return {
                    "response": [
                        {
                            "fixture": {"id": 999},
                            "teams": {"home": {"id": 42}, "away": {"id": 77}},
                        }
                    ]
                }
            if path == "/fixtures/statistics":
                # Away block first (the bug case)
                return {
                    "response": [
                        {
                            "team": {"id": 77},
                            "statistics": [
                                {"type": "Ball Possession", "value": "38%"},
                                {"type": "Shots on Goal", "value": 1},
                                {"type": "Total Shots", "value": 4},
                            ],
                        },
                        {
                            "team": {"id": 42},
                            "statistics": [
                                {"type": "Ball Possession", "value": "62%"},
                                {"type": "Shots on Goal", "value": 5},
                                {"type": "Total Shots", "value": 12},
                            ],
                        },
                    ]
                }
            return {"response": []}

        with patch.object(adv, "_api_get", side_effect=fake_get):
            out = adv.team_match_stats_for_fixture(db, fx, force=True)
        assert out is not None
        assert out["possession"]["home"] == "62%"
        assert out["possession"]["away"] == "38%"
        assert out["shots_on_target"]["home"] == "5"
        assert out["shots_on_target"]["away"] == "1"
        assert out["chances_created"]["home"] == "12"
    finally:
        settings.api_football_key = old_key
        db.close()


def test_team_match_stats_result_reports_no_club_ids():
    from app.models import Fixture

    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        adv._team_stats_cache.clear()
        db.add(Club(code="ARS", name="Arsenal", api_football_team_id=42))
        # Unknown code — not in hardcoded PL map and API returns empty.
        db.add(Club(code="ZZZ", name="Zed United"))
        fx = Fixture(
            fpl_id=88003,
            gameweek_number=1,
            home_club_code="ARS",
            away_club_code="ZZZ",
            kickoff_at="2026-08-21T19:00:00Z",
            started=1,
        )
        db.add(fx)
        db.commit()
        db.refresh(fx)

        with patch.object(adv, "_api_get", return_value={"response": []}):
            result = adv.team_match_stats_result(db, fx, force=True)
        assert result["team_stats"] is None
        assert result["team_stats_status"] == "no_club_ids"
        assert "ZZZ" in (result.get("missing_clubs") or [])
    finally:
        settings.api_football_key = old_key
        db.close()


def test_ensure_club_team_ids_code_map_covers_promotees():
    """Promoted clubs map even when season team lists are empty."""
    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        db.add(Club(code="COV", name="Coventry City"))
        db.add(Club(code="HUL", name="Hull City"))
        db.add(Club(code="SUN", name="Sunderland"))
        db.add(Club(code="NFO", name="Nott'm Forest"))
        db.commit()

        with patch.object(adv, "_api_get", return_value={"response": []}):
            out = adv.ensure_club_team_ids(db)
        assert out["updated"] == 4
        assert out.get("still_missing") == 0
        clubs = {c.code: c.api_football_team_id for c in db.query(Club).all()}
        assert clubs["COV"] == 71
        assert clubs["HUL"] == 64
        assert clubs["SUN"] == 746
        assert clubs["NFO"] == 65
    finally:
        settings.api_football_key = old_key
        db.close()


def test_ensure_club_team_ids_search_fallback_for_unknown_code():
    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        db.add(Club(code="ZZZ", name="Zed United"))
        db.commit()

        def fake_get(path, params=None, **kwargs):
            if path == "/teams" and (params or {}).get("search"):
                return {
                    "response": [
                        {"team": {"id": 9999, "name": "Zed United", "country": "England"}},
                    ]
                }
            return {"response": []}

        with patch.object(adv, "_api_get", side_effect=fake_get):
            out = adv.ensure_club_team_ids(db)
        assert out["updated"] == 1
        club = db.query(Club).filter(Club.code == "ZZZ").one()
        assert club.api_football_team_id == 9999
    finally:
        settings.api_football_key = old_key
        db.close()


def test_team_match_stats_cache_ttl():
    from app.models import Fixture

    _reset()
    db = SessionLocal()
    try:
        old_key = settings.api_football_key
        settings.api_football_key = "test-key"
        adv._team_stats_cache.clear()
        db.add(Club(code="ARS", name="Arsenal", api_football_team_id=42))
        db.add(Club(code="CHE", name="Chelsea", api_football_team_id=49))
        fx = Fixture(
            fpl_id=88002,
            gameweek_number=1,
            home_club_code="ARS",
            away_club_code="CHE",
            kickoff_at="2026-08-21T17:00:00Z",
            started=1,
        )
        db.add(fx)
        db.commit()
        db.refresh(fx)

        calls = {"n": 0}

        def fake_get(path, params=None, **kwargs):
            calls["n"] += 1
            if path == "/fixtures":
                return {
                    "response": [
                        {
                            "fixture": {"id": 1001},
                            "teams": {"home": {"id": 42}, "away": {"id": 49}},
                        }
                    ]
                }
            return {
                "response": [
                    {
                        "team": {"id": 42},
                        "statistics": [{"type": "Ball Possession", "value": "55%"}],
                    },
                    {
                        "team": {"id": 49},
                        "statistics": [{"type": "Ball Possession", "value": "45%"}],
                    },
                ]
            }

        with patch.object(adv, "_api_get", side_effect=fake_get):
            first = adv.team_match_stats_for_fixture(db, fx)
            second = adv.team_match_stats_for_fixture(db, fx)
            forced = adv.team_match_stats_for_fixture(db, fx, force=True)
        assert first["possession"]["home"] == "55%"
        assert second["possession"]["home"] == "55%"
        assert forced["possession"]["home"] == "55%"
        # First open: fixtures resolve + statistics. Cache hit skips both.
        # force=True hits both again.
        assert calls["n"] == 4
    finally:
        settings.api_football_key = old_key
        db.close()
