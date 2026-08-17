"""League / leagues pages show ranked standings snippets."""

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Gameweek, ManagerGameweekScore
from app.services import league as league_svc
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


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def test_my_rank_and_league_pages_show_positions():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="RankA",
            password="secret12",
            email="ranka@example.com",
            team_name="Alpha FC",
        )
        b = league_svc.register_manager(
            db,
            display_name="RankB",
            password="secret12",
            email="rankb@example.com",
            team_name="Beta FC",
        )
        league = league_svc.create_league(db, "Rank League", a)
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).order_by(Gameweek.number).first()
        assert gw is not None
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gw.id, total=40))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gw.id, total=55))
        db.commit()

        rank_a, n = standings_svc.my_rank_in_league(db, league, a.id, gw)
        rank_b, _ = standings_svc.my_rank_in_league(db, league, b.id, gw)
        assert n == 2
        assert rank_b == 1
        assert rank_a == 2
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "RankB", "password": "secret12"}, follow_redirects=False)

    league_html = client.get(f"/league/{league.id}").text
    assert "standings-board" in league_html
    assert "standings-rank" in league_html
    assert "Beta FC" in league_html
    assert "Alpha FC" in league_html
    assert "is-top-1" in league_html
    assert ">55<" in league_html or "55</span>" in league_html

    leagues_html = client.get("/leagues").text
    assert "#1 of 2" in leagues_html
    assert "Classic" in leagues_html
    assert "Rank League" in leagues_html
