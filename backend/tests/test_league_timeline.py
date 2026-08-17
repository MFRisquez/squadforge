"""League table format + GW-by-GW rank timeline."""

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


def test_classic_rank_history_tracks_swaps():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="HistA",
            password="secret12",
            email="hista@example.com",
            team_name="Alpha Rise",
        )
        b = league_svc.register_manager(
            db,
            display_name="HistB",
            password="secret12",
            email="histb@example.com",
            team_name="Beta Lead",
        )
        league = league_svc.create_league(db, "Timeline Cup", a)
        league_svc.join_league(db, league.invite_code, b)

        gws = []
        for n in (1, 2, 3):
            gw = db.query(Gameweek).filter(Gameweek.number == n).one_or_none()
            if not gw:
                gw = Gameweek(number=n, status="finished", name=f"GW{n}", is_current=0)
                db.add(gw)
                db.flush()
            else:
                gw.status = "finished"
                gw.is_current = 1 if n == 3 else 0
            gws.append(gw)
        # GW1: B leads (60 vs 40) → B #1, A #2
        # GW2: A 80 → totals A 120, B 90 → A #1
        # GW3: flat
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gws[0].id, total=40))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gws[0].id, total=60))
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gws[1].id, total=80))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gws[1].id, total=30))
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gws[2].id, total=20))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gws[2].id, total=20))
        db.commit()

        hist = standings_svc.classic_rank_history(db, league, gws[2], me_id=a.id)
        assert hist["gw_numbers"] == [1, 2, 3]
        by_id = {s["manager_id"]: s for s in hist["series"]}
        assert by_id[a.id]["ranks"] == [2, 1, 1]
        assert by_id[b.id]["ranks"] == [1, 2, 2]
        assert by_id[a.id]["is_me"] is True
        assert by_id[a.id]["polyline"]
        assert hist["grid"]
    finally:
        db.close()


def test_league_page_shows_table_and_timeline():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="PageA",
            password="secret12",
            email="pagea@example.com",
            team_name="Page Alpha",
        )
        b = league_svc.register_manager(
            db,
            display_name="PageB",
            password="secret12",
            email="pageb@example.com",
            team_name="Page Beta",
        )
        league = league_svc.create_league(db, "Page League", a)
        league_svc.join_league(db, league.invite_code, b)
        gws = []
        for n in (1, 2):
            gw = db.query(Gameweek).filter(Gameweek.number == n).one_or_none()
            if not gw:
                gw = Gameweek(number=n, status="finished", name=f"GW{n}", is_current=0)
                db.add(gw)
                db.flush()
            gws.append(gw)
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gws[0].id, total=10))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gws[0].id, total=50))
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gws[1].id, total=60))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gws[1].id, total=10))
        db.commit()
        lid = league.id
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "PageA", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{lid}").text
    assert "standings-board" in html or "League table" in html
    assert "Position timeline" in html
    assert "rank-timeline-chart" in html
    assert "Page Alpha" in html
    assert "Page Beta" in html


def test_fixtures_desktop_css_has_breathing_room():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "styles.css").read_text()
    assert "body.page-fixtures .fixtures-desk .fx-card" in css
    assert "padding: 0.55rem 0.7rem 0.6rem" in css
    assert "gap: 0.55rem" in css  # desk-squad / desk-xi gap
