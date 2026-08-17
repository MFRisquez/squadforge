"""H2H fixtures on league page + match detail sheet."""

import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import ChipState, Gameweek, H2HMatch, ManagerGameweekScore, Player
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


def test_h2h_fixture_cards_and_league_page_sheet():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="FxA",
            password="secret12",
            email="fxa@example.com",
            team_name="Foxes",
        )
        b = league_svc.register_manager(
            db,
            display_name="FxB",
            password="secret12",
            email="fxb@example.com",
            team_name="Badgers",
        )
        league = league_svc.create_league(db, "H2H Fixtures", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one_or_none()
        if not gw:
            gw = Gameweek(number=1, status="live", name="GW1", is_current=1)
            db.add(gw)
            db.flush()
        else:
            gw.status = "live"
            gw.is_current = 1
        # Past deadline required for scores / top XI to be public
        gw.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        player = db.query(Player).first()
        assert player is not None
        breakdown = json.dumps(
            {"players": [{"player_id": player.id, "points": 12, "base": 12, "mult": 1}]}
        )
        db.add(
            ManagerGameweekScore(
                manager_id=a.id,
                gameweek_id=gw.id,
                total=44,
                breakdown_json=breakdown,
            )
        )
        db.add(
            ManagerGameweekScore(
                manager_id=b.id,
                gameweek_id=gw.id,
                total=30,
                breakdown_json=json.dumps(
                    {"players": [{"player_id": player.id, "points": 8, "base": 8, "mult": 1}]}
                ),
            )
        )
        # Ensure chips remaining for A
        state = db.query(ChipState).filter(ChipState.manager_id == a.id).one()
        state.wildcard_remaining = 1
        state.triple_captain_remaining = 1
        db.commit()

        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert len(cards) == 1
        card = cards[0]
        assert card["show_scores"] is True
        assert card["home"]["team_name"] in {"Foxes", "Badgers"}
        assert card["home"]["top_player"] is not None or card["away"]["top_player"] is not None
        assert "Wildcard" in (card["home"]["chips_left"] + card["away"]["chips_left"])
        lid = league.id
        pname = player.name
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "FxA", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{lid}").text
    assert "This week's fixtures" in html
    assert "data-h2h-match" in html
    assert "h2hMatchDetail" in html
    assert "match-detail-sheet" in html
    assert "league_h2h.js" in html
    assert "h2hFixturesBoot" in html
    assert "Foxes" in html and "Badgers" in html
    # Boot JSON includes top player payload
    assert pname.split()[0] in html or pname in html


def test_h2h_fixture_cards_hide_top_player_before_deadline():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="PreDlA",
            password="secret12",
            email="predla@example.com",
            team_name="Pre Deadline A",
        )
        b = league_svc.register_manager(
            db,
            display_name="PreDlB",
            password="secret12",
            email="predlb@example.com",
            team_name="Pre Deadline B",
        )
        league = league_svc.create_league(db, "Pre Deadline Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.status = "live"
        gw.is_current = 1
        gw.deadline_at = (
            (datetime.now(timezone.utc) + timedelta(days=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        player = db.query(Player).first()
        assert player is not None
        db.add(
            ManagerGameweekScore(
                manager_id=a.id,
                gameweek_id=gw.id,
                total=44,
                breakdown_json=json.dumps(
                    {"players": [{"player_id": player.id, "points": 12, "base": 12, "mult": 1}]}
                ),
            )
        )
        db.commit()
        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert len(cards) == 1
        assert cards[0]["show_scores"] is False
        assert cards[0]["home"]["top_player"] is None
        assert cards[0]["away"]["top_player"] is None
    finally:
        db.close()


def test_h2h_preview_hides_scores_before_gw_starts():
    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="PrevA",
            password="secret12",
            email="preva@example.com",
            team_name="Preview A",
        )
        b = league_svc.register_manager(
            db,
            display_name="PrevB",
            password="secret12",
            email="prevb@example.com",
            team_name="Preview B",
        )
        league = league_svc.create_league(db, "Preview Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = Gameweek(number=99, status="upcoming", name="GW99", is_current=0)
        db.add(gw)
        db.flush()
        db.add(
            H2HMatch(
                league_id=league.id,
                gameweek_id=gw.id,
                home_manager_id=a.id,
                away_manager_id=b.id,
                home_points=0,
                away_points=0,
                result="pending",
            )
        )
        db.commit()
        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert len(cards) == 1
        assert cards[0]["show_scores"] is False
    finally:
        db.close()
