"""Club profile for DT picker sheets."""

from app.db import Base, SessionLocal, engine
from app.models import Club, Fixture, Player
from app.services import club_profile as club_svc
from app.services.seed import seed_if_empty


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def test_player_points_zero_until_minutes_and_kickoff():
    p = Player(
        external_id="pts-gate-1",
        name="Ghost",
        position="MID",
        team_code="AAA",
        price=8.0,
        season_stats_json='{"total_points": 99, "minutes": 0}',
    )
    assert club_svc._player_points(p, scoring_started=False) == 0.0
    assert club_svc._player_points(p, scoring_started=True) == 0.0

    p2 = Player(
        external_id="pts-gate-2",
        name="Starter",
        position="MID",
        team_code="AAA",
        price=8.0,
        season_stats_json='{"total_points": 42, "minutes": 90}',
    )
    assert club_svc._player_points(p2, scoring_started=False) == 0.0
    assert club_svc._player_points(p2, scoring_started=True) == 42.0


def test_top_players_zero_before_any_fixture_started():
    db = SessionLocal()
    try:
        # Isolate: no started/finished fixtures in DB
        for fx in db.query(Fixture).all():
            fx.started = 0
            fx.finished = 0
            fx.home_score = None
            fx.away_score = None
        if not db.query(Club).filter(Club.code == "PSE").one_or_none():
            db.add(Club(code="PSE", name="Preseason FC", kit_code=1))
        for i, pts in enumerate((99, 80, 60)):
            ext = f"preseason-pse-{i}"
            existing = db.query(Player).filter(Player.external_id == ext).one_or_none()
            if existing:
                existing.season_stats_json = f'{{"total_points": {pts}, "minutes": 0}}'
                existing.price = 10.0 - i
                continue
            db.add(
                Player(
                    external_id=ext,
                    name=f"Preseason {i}",
                    position="MID",
                    team_code="PSE",
                    price=10.0 - i,
                    season_stats_json=f'{{"total_points": {pts}, "minutes": 0}}',
                )
            )
        db.commit()

        assert club_svc.season_scoring_started(db) is False
        top = club_svc.club_top_players(db, "PSE", limit=3)
        assert len(top) == 3
        assert all(p["points"] == 0 for p in top)
        # Provisional order by price (highest first)
        assert top[0]["name"] == "Preseason 0"
    finally:
        db.close()


def test_club_table_stats_and_top_players():
    db = SessionLocal()
    try:
        club = db.query(Club).filter(Club.code == "LIV").one_or_none()
        if not club:
            club = Club(code="LIV", name="Liverpool", kit_code=14)
            db.add(club)
            db.flush()
        if not db.query(Club).filter(Club.code == "ARS").one_or_none():
            db.add(Club(code="ARS", name="Arsenal", kit_code=3))
            db.flush()
        if not db.query(Fixture).filter(Fixture.fpl_id == 90001).one_or_none():
            db.add(
                Fixture(
                    fpl_id=90001,
                    gameweek_number=1,
                    home_club_code="LIV",
                    away_club_code="ARS",
                    home_difficulty=3,
                    away_difficulty=4,
                    started=1,
                    finished=1,
                    home_score=2,
                    away_score=1,
                )
            )
        for i, pts in enumerate((80, 60, 40, 10)):
            ext = f"club-liv-{i}"
            existing = db.query(Player).filter(Player.external_id == ext).one_or_none()
            payload = f'{{"total_points": {pts}, "minutes": {90 + i}}}'
            if existing:
                existing.season_stats_json = payload
                continue
            db.add(
                Player(
                    external_id=ext,
                    name=f"LIV Star {i}",
                    position="MID" if i < 3 else "DEF",
                    team_code="LIV",
                    price=7.0,
                    season_stats_json=payload,
                )
            )
        db.commit()

        assert club_svc.season_scoring_started(db) is True

        table = club_svc.club_table_stats(db, "LIV")
        assert table["played"] >= 1
        assert table["wins"] >= 1
        assert table["gf"] >= 2
        assert table["ga"] >= 1
        assert table["points"] >= 3

        top = club_svc.club_top_players(db, "LIV", limit=3)
        assert len(top) == 3
        assert top[0]["points"] >= top[1]["points"] >= top[2]["points"]
        assert top[0]["points"] > 0
        assert "availability" in top[0] and "status_label" in top[0]

        profile = club_svc.club_profile(db, "LIV", from_gw=1)
        assert profile is not None
        assert profile["code"] == "LIV"
        assert profile.get("scoring_started") is True
        assert "table" in profile and "top_players" in profile and "fixtures" in profile

        clubs = club_svc.clubs_list(db, exclude="LIV")
        assert any(c["code"] == "LIV" and c["banned"] for c in clubs)
        assert any(c["code"] != "LIV" and not c["banned"] for c in clubs)
    finally:
        db.close()


def test_club_api_endpoints():
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.main import app

    settings.reset_db_on_startup = False
    client = TestClient(app, base_url="https://testserver")
    r = client.get("/api/clubs")
    assert r.status_code == 200
    data = r.json()
    assert data.get("ok") is True
    assert isinstance(data.get("clubs"), list)
    assert data["clubs"]
    code = data["clubs"][0]["code"]
    detail = client.get(f"/api/clubs/{code}")
    assert detail.status_code == 200
    body = detail.json()
    assert body.get("code") == code
    assert "table" in body
    assert "top_players" in body
    assert "fixtures" in body
    assert "scoring_started" in body
