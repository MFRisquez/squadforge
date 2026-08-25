"""Legacy league accordion removed — News lives on /news."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
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


def test_league_no_longer_embeds_news_accordion(db, monkeypatch):
    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    mgr = league_svc.register_manager(
        db,
        display_name="NewsFan",
        password="secret12",
        email="news@example.com",
        team_name="News FC",
    )
    league = league_svc.create_league(db, "News Desk", mgr, league_type="classic")
    client = _client()
    client.post("/login", data={"login": "NewsFan", "password": "secret12"}, follow_redirects=False)
    resp = client.get(f"/league/{league.id}")
    assert resp.status_code == 200
    assert "league-news-panel" not in resp.text
