"""News magazine tab: nav + feed + no panel inside League."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Club, Fixture, Gameweek, LeagueNewsEdition, OwnedPlayer, Player
from app.services import league as league_svc
from app.services import league_news as news_svc
from app.services.seed import seed_if_empty


@pytest.fixture()
def db():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = SessionLocal()
    try:
        seed_if_empty(session)
        yield session
    finally:
        session.close()


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _fill_squad(db, manager_id: int) -> None:
    by_pos: dict[str, list] = {"GK": [], "DEF": [], "MID": [], "ATT": []}
    for pl in db.query(Player).all():
        if pl.position in by_pos and len(by_pos[pl.position]) < 5:
            by_pos[pl.position].append(pl)
    picks = by_pos["GK"][:2] + by_pos["DEF"][:5] + by_pos["MID"][:5] + by_pos["ATT"][:3]
    assert len(picks) == 15
    for pl in picks:
        db.add(OwnedPlayer(manager_id=manager_id, player_id=pl.id))
    db.commit()


def test_nav_has_news_and_league_tabs(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    mgr = league_svc.register_manager(
        db,
        display_name="NavFan",
        password="secret12",
        email="nav@example.com",
        team_name="Nav FC",
    )
    _fill_squad(db, mgr.id)
    client = _client()
    client.post("/login", data={"login": "NavFan", "password": "secret12"}, follow_redirects=False)
    home = client.get("/")
    assert home.status_code == 200
    assert 'href="/news"' in home.text
    assert ">News<" in home.text
    assert 'href="/leagues"' in home.text or "/standings/" in home.text


def test_league_page_has_no_news_panel(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    mgr = league_svc.register_manager(
        db,
        display_name="NoPanel",
        password="secret12",
        email="nopanel@example.com",
        team_name="NoPanel FC",
    )
    league = league_svc.create_league(db, "No Panel Desk", mgr, league_type="classic")
    client = _client()
    client.post("/login", data={"login": "NoPanel", "password": "secret12"}, follow_redirects=False)
    resp = client.get(f"/league/{league.id}")
    assert resp.status_code == 200
    assert "league-news-panel" not in resp.text
    assert "Generar ahora" not in resp.text
    assert 'id="leagueNewsToggle"' not in resp.text


def test_news_page_aggregates_classic_and_h2h(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    mgr = league_svc.register_manager(
        db,
        display_name="AggFan",
        password="secret12",
        email="agg@example.com",
        team_name="Agg FC",
    )
    _fill_squad(db, mgr.id)
    classic = league_svc.create_league(db, "Classic Desk", mgr, league_type="classic")
    h2h = league_svc.create_league(db, "H2H Desk", mgr, league_type="h2h")
    db.add(
        LeagueNewsEdition(
            league_id=classic.id,
            edition_type="post_gw",
            gameweek_number=1,
            content_json=json.dumps(
                {
                    "title": "Classic tapa",
                    "stories": [
                        {
                            "headline": "Classic haula",
                            "body": "Rompió todo.\n\nSegundo párrafo.",
                            "drama": 50,
                            "kind": "broke_out",
                            "gw_points": 18,
                        }
                    ],
                }
            ),
        )
    )
    db.add(
        LeagueNewsEdition(
            league_id=h2h.id,
            edition_type="post_gw",
            gameweek_number=1,
            content_json=json.dumps(
                {
                    "title": "H2H tapa",
                    "stories": [
                        {
                            "headline": "H2H papelón",
                            "body": "Quedó en offside.",
                            "drama": 40,
                            "kind": "blew_up",
                        }
                    ],
                }
            ),
        )
    )
    db.add(
        LeagueNewsEdition(
            league_id=None,
            edition_type="forecast",
            gameweek_number=2,
            content_json=json.dumps(
                {
                    "title": "Forecast GW2",
                    "stories": [
                        {
                            "headline": "Haaland vs soft FDR",
                            "body": "Rival regalado.",
                            "drama": 30,
                            "kind": "forecast_pick",
                            "fdr": 1,
                            "form": 8.2,
                        }
                    ],
                }
            ),
        )
    )
    db.commit()

    feed = news_svc.build_manager_news_feed(db, mgr.id)
    assert feed["featured"] is not None
    assert feed["featured"]["headline"] == "Classic haula"
    labels = {c["label"] for c in feed["cards"]}
    assert "Classic Desk" in labels
    assert "H2H Desk" in labels
    assert "FORECAST" in labels
    filters = {c["filter"] for c in feed["cards"]}
    assert "classic" in filters and "h2h" in filters and "forecast" in filters

    client = _client()
    client.post("/login", data={"login": "AggFan", "password": "secret12"}, follow_redirects=False)
    resp = client.get("/news")
    assert resp.status_code == 200
    html = resp.text
    assert "news-featured" in html
    assert "news-grid" in html
    assert "Classic haula" in html
    assert "H2H papelón" in html
    assert "FORECAST" in html
    assert 'data-filter="all"' in html
    assert 'data-filter="classic"' in html
    assert 'data-filter="h2h"' in html
    assert 'data-filter="forecast"' in html
    assert "news.js" in html
    assert 'id="newsDetail"' in html


def test_forecast_package_uses_real_fdr_signal(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    gw = db.query(Gameweek).filter(Gameweek.number == 2).one()
    club = db.query(Club).first()
    assert club is not None
    db.add(
        Fixture(
            fpl_id=99001,
            gameweek_number=2,
            home_club_code=club.code,
            away_club_code="ZZZ",
            home_difficulty=1,
            away_difficulty=4,
            finished=0,
        )
    )
    pl = (
        db.query(Player)
        .filter(Player.team_code == club.code, Player.status == "a")
        .first()
    )
    if pl is None:
        pl = db.query(Player).filter(Player.status == "a").first()
        assert pl is not None
        pl.team_code = club.code
    pl.season_stats_json = json.dumps({"form": "9.0", "threat": 400, "creativity": 300})
    db.commit()

    package = news_svc.build_forecast_package(db, gw)
    assert package["edition_type"] == "forecast"
    assert package["league_id"] is None
    assert package["stories"], "expected at least one forecast candidate"
    top = package["stories"][0]
    assert top.get("player_id")
    assert top.get("fdr") in (1, 2)
    assert "form" in top
