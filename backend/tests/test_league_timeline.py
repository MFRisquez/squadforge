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
        assert by_id[a.id]["points"]
        assert by_id[a.id]["points"][0]["title"].startswith("Alpha Rise")
        assert "#2" in by_id[a.id]["points"][0]["title"]
        assert hist["grid"]

        raw = standings_svc.rank_history(db, league, gws[2])
        assert raw["gameweeks"] == [1, 2, 3]
        by_name = {m["name"]: m["ranks"] for m in raw["managers"]}
        assert by_name["Alpha Rise"] == [2, 1, 1]
        assert by_name["Beta Lead"] == [1, 2, 2]
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
    assert "standings-list" in html
    assert "Position timeline" not in html
    assert "rank-timeline-chart" not in html
    assert "Page Alpha" in html
    assert "Page Beta" in html


def test_unified_league_table_macro_for_h2h():
    """H2H uses the same standings-board list with W/D/L/Pts columns (no separate table)."""
    from pathlib import Path

    macro = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "web"
        / "templates"
        / "macros_standings.html"
    ).read_text()
    assert "macro league_table" in macro
    assert "standings-row-h2h" in macro
    assert "row.wins" in macro
    assert "row.h2h_points" in macro

    league_tpl = (
        Path(__file__).resolve().parents[1] / "app" / "web" / "templates" / "league.html"
    ).read_text()
    standings_tpl = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "web"
        / "templates"
        / "standings.html"
    ).read_text()
    assert "league_table(" in league_tpl
    assert "league_table(" in standings_tpl
    assert "standings-h2h" not in league_tpl
    assert "<table class=\"standings standings-h2h\">" not in standings_tpl


def test_h2h_rank_history_and_league_page_timeline():
    """H2H rank history still computes; league home no longer renders the timeline."""
    from app.models import H2HMatch

    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="H2HHistA",
            password="secret12",
            email="h2hhista@example.com",
            team_name="H2H Alpha",
        )
        b = league_svc.register_manager(
            db,
            display_name="H2HHistB",
            password="secret12",
            email="h2hhistb@example.com",
            team_name="H2H Beta",
        )
        league = league_svc.create_league(db, "H2H Timeline", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gws = []
        for n in (1, 2):
            gw = db.query(Gameweek).filter(Gameweek.number == n).one_or_none()
            if not gw:
                gw = Gameweek(number=n, status="finished", name=f"GW{n}", is_current=0)
                db.add(gw)
                db.flush()
            gws.append(gw)
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gws[0].id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=40,
                away_points=60,
                result="away",
            )
        )
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gws[1].id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=70,
                away_points=20,
                result="home",
            )
        )
        db.commit()
        hist = standings_svc.league_rank_history(db, league, gws[1], me_id=a.id)
        assert hist["gw_numbers"] == [1, 2]
        by_id = {s["manager_id"]: s for s in hist["series"]}
        assert by_id[b.id]["ranks"][0] == 1
        assert by_id[a.id]["ranks"][0] == 2
        # After GW2 both have 3 H2H pts; A has higher PF (40+70=110 vs 60+20=80) → A #1
        assert by_id[a.id]["ranks"][1] == 1
        assert by_id[b.id]["ranks"][1] == 2
        lid = league.id
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "H2HHistA", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{lid}").text
    assert "Position timeline" not in html
    assert "rank-timeline-chart" not in html
    assert "standings-board" in html
    assert "H2H Alpha" in html
    assert "H2H Beta" in html


def test_fixtures_desktop_css_has_breathing_room():
    from pathlib import Path

    css = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "styles.css").read_text()
    assert "body.page-fixtures .fixtures-desk .fx-card" in css
    assert "padding: 0.55rem 0.7rem 0.6rem" in css
    assert "gap: 0.55rem" in css  # desk-squad / desk-xi gap
