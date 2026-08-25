"""User polls must not force full GW scoring (egress hot path).

``GET /api/xi/live-points`` is polled ~every 30s per client. Calling
``maybe_score_locked_gw(force=True)`` bypassed MIN_INTERVAL_SEC and forced a
GW fixture sweep every time — the dominant Supabase egress contributor under
live match traffic.

``POST /api/fixtures/refresh`` may soft-kick scoring with force=False only.
"""

from __future__ import annotations

import inspect
import time
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.api import api_fixtures_refresh, api_xi_live_points
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
    finally:
        db.close()


def test_live_points_source_does_not_kick_scoring():
    src = inspect.getsource(api_xi_live_points)
    # Docstring may mention the banned call; body must not invoke it.
    body = src.split('"""', 2)[-1]
    assert "maybe_score_locked_gw" not in body
    assert "force=True" not in body
    assert "threading.Thread" not in body
    assert "import threading" not in body


def test_fixtures_refresh_soft_kick_only():
    src = inspect.getsource(api_fixtures_refresh)
    assert "maybe_score_locked_gw(force=False)" in src
    assert "maybe_score_locked_gw(force=True)" not in src


def _login(client: TestClient) -> None:
    name = f"LivePoll{int(time.time() * 1000) % 100000}"
    client.post(
        "/register",
        data={
            "display_name": name,
            "password": "secret12",
            "password_confirm": "secret12",
            "email": f"{name.lower()}@example.com",
            "team_name": f"{name} FC",
        },
        follow_redirects=False,
    )
    client.post(
        "/login",
        data={"login": name, "password": "secret12"},
        follow_redirects=False,
    )


def test_live_points_endpoint_does_not_call_maybe_score():
    client = TestClient(app, base_url="https://testserver")
    _login(client)
    calls: list[dict] = []

    def _spy(*, force: bool = False):
        calls.append({"force": force})
        return None

    with patch("app.services.auto_score.maybe_score_locked_gw", side_effect=_spy):
        res = client.get("/api/xi/live-points")
    assert res.status_code == 200
    body = res.json()
    assert body.get("ok") is True
    assert "points" in body
    assert calls == [], "live-points must be read-only (no scoring kick)"


def test_fixtures_refresh_kicks_score_without_force():
    client = TestClient(app, base_url="https://testserver")
    calls: list[dict] = []

    def _spy(*, force: bool = False):
        calls.append({"force": force})
        return None

    with patch(
        "app.services.fixtures.refresh_fixtures",
        return_value={"fixtures": 0, "scope": "gw"},
    ):
        with patch("app.services.auto_score.maybe_score_locked_gw", side_effect=_spy):
            res = client.post("/api/fixtures/refresh")
            # Soft kick runs on a daemon thread after response — wait briefly.
            deadline = time.time() + 2.0
            while not calls and time.time() < deadline:
                time.sleep(0.05)
    assert res.status_code == 200
    assert calls, "fixtures refresh should soft-kick scoring"
    assert all(c["force"] is False for c in calls)
