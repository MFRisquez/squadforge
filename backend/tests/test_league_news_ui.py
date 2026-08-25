"""Fase 3: League News accordion on the league page."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import LeagueNewsEdition
from app.services import league as league_svc
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


def test_league_news_accordion_renders(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    mgr = league_svc.register_manager(
        db,
        display_name="NewsFan",
        password="secret12",
        email="news@example.com",
        team_name="News FC",
    )
    league = league_svc.create_league(db, "News Desk", mgr, league_type="classic")
    db.add(
        LeagueNewsEdition(
            league_id=league.id,
            edition_type="post_gw",
            gameweek_number=1,
            content_json=json.dumps(
                {
                    "title": "Fecha 1: explotó el chat",
                    "kicker": "Hubo papelón y festejo",
                    "lede": "Arrancó la liga.\n\nEl grupo ya está que arde.",
                    "stories": [
                        {
                            "headline": "Manuel mete plena",
                            "body": "Primera.\n\nSegunda.",
                            "player_id": None,
                        }
                    ],
                }
            ),
        )
    )
    db.commit()

    client = _client()
    client.post("/login", data={"login": "NewsFan", "password": "secret12"}, follow_redirects=False)
    resp = client.get(f"/league/{league.id}")
    assert resp.status_code == 200
    html = resp.text
    assert "league-news-panel" in html
    assert "Fecha 1: explotó el chat" in html
    assert "Manuel mete plena" in html
    assert 'id="leagueNewsToggle"' in html
    assert 'id="leagueNewsBody"' in html


def test_league_news_panel_shows_when_enabled_without_edition(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    mgr = league_svc.register_manager(
        db,
        display_name="EmptyNews",
        password="secret12",
        email="empty@example.com",
        team_name="Empty FC",
    )
    league = league_svc.create_league(db, "Empty Desk", mgr, league_type="classic")
    # Avoid sync Gemini call on page load
    from app.services import league_news as news_svc
    from unittest.mock import patch

    with patch.object(news_svc, "ensure_league_news", return_value={"ok": True, "generated": []}):
        client = _client()
        client.post("/login", data={"login": "EmptyNews", "password": "secret12"}, follow_redirects=False)
        resp = client.get(f"/league/{league.id}")
    assert resp.status_code == 200
    assert "league-news-panel" in resp.text
    assert "Todavía no hay crónica" in resp.text
