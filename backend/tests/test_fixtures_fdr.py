"""Fixture difficulty mapping + next-3 lookups."""

import json

from app.db import Base, SessionLocal, engine
from app.models import Club, Fixture, Gameweek, Player
from app.services import fixtures as fixtures_svc
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
        for code, name, fpl_id in [
            ("ARS", "Arsenal", 1),
            ("LIV", "Liverpool", 14),
            ("MCI", "Man City", 43),
            ("CHE", "Chelsea", 8),
            ("NEW", "Newcastle", 4),
            ("AVL", "Aston Villa", 7),
            ("BHA", "Brighton", 36),
            ("WHU", "West Ham", 21),
            ("TOT", "Spurs", 6),
            ("MUN", "Man Utd", 1),  # duplicate id ok — LIV def club only matters
        ]:
            club = db.query(Club).filter(Club.code == code).one_or_none()
            if club:
                club.fpl_team_id = fpl_id
                club.name = name
        # Clear conflicting MUN id
        mun = db.query(Club).filter(Club.code == "MUN").one_or_none()
        if mun:
            mun.fpl_team_id = 13

        # Next 3 for LIV starting GW2
        samples = [
            (101, 2, "LIV", "ARS", 2, 4),
            (102, 3, "CHE", "LIV", 3, 3),
            (103, 4, "LIV", "MCI", 5, 2),
            (104, 5, "LIV", "BHA", 1, 4),
        ]
        for fpl_id, gw, home, away, hd, ad in samples:
            db.add(
                Fixture(
                    fpl_id=fpl_id,
                    gameweek_number=gw,
                    home_club_code=home,
                    away_club_code=away,
                    home_difficulty=hd,
                    away_difficulty=ad,
                    kickoff_at="2026-08-20T14:00:00Z",
                )
            )
        db.query(Gameweek).update({"is_current": 0})
        gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
        gw2.is_current = 1
        db.commit()
    finally:
        db.close()


def test_map_fdr_collapses_five_to_four():
    assert fixtures_svc.map_fdr(1) == 1
    assert fixtures_svc.map_fdr(4) == 4
    assert fixtures_svc.map_fdr(5) == 4
    assert fixtures_svc.map_fdr(None) == 3


def test_next_fixtures_for_player_perspective():
    db = SessionLocal()
    try:
        liv = db.query(Player).filter(Player.team_code == "LIV").first()
        assert liv is not None
        items = fixtures_svc.next_fixtures_for_player(db, player_id=liv.id, limit=3)
        assert len(items) == 3
        assert items[0]["gw"] == 2
        assert items[0]["opponent"] == "ARS"
        assert items[0]["venue"] == "H"
        assert items[0]["difficulty"] == 2
        assert items[1]["venue"] == "A"
        assert items[1]["opponent"] == "CHE"
        assert items[1]["difficulty"] == 3
        assert items[2]["opponent"] == "MCI"
        assert items[2]["difficulty"] == 4
    finally:
        db.close()


def test_fixture_detail_parses_goals_and_assists():
    db = SessionLocal()
    try:
        fx = db.query(Fixture).filter(Fixture.fpl_id == 101).one()
        # Fake FPL element ids — names fall back to Player N if catalogue missing
        fx.stats_json = json.dumps(
            [
                {
                    "identifier": "goals_scored",
                    "h": [{"element": 1, "value": 2}],
                    "a": [{"element": 2, "value": 1}],
                },
                {
                    "identifier": "assists",
                    "h": [{"element": 3, "value": 1}],
                    "a": [],
                },
            ]
        )
        fx.home_score = 2
        fx.away_score = 1
        fx.started = 1
        fx.finished = 1
        db.commit()

        detail = fixtures_svc.fixture_detail(db, fixture_id=fx.id)
        assert detail is not None
        assert detail["home"]["score"] == 2
        assert detail["goals"]["home"][0]["value"] == 2
        assert detail["goals"]["away"][0]["value"] == 1
        assert detail["assists"]["home"][0]["value"] == 1
        assert fixtures_svc.fixtures_for_gameweek(db, gw_number=2)
    finally:
        db.close()
