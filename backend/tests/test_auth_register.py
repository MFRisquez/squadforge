"""Registration, login, and password recovery."""

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Manager
from app.services import league as league_svc
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
    finally:
        db.close()


def test_register_without_team_name_uses_fallback():
    db = SessionLocal()
    try:
        manager = league_svc.register_manager(
            db,
            display_name="NoTeamUser",
            password="pass1234",
            email="noteam@example.com",
            team_name="",
        )
        assert manager.team_name == "NoTeamUser's XI"
    finally:
        db.close()


def test_register_rejects_password_mismatch():
    client = TestClient(app)
    r = client.post(
        "/register",
        data={
            "display_name": "MismatchUser",
            "password": "pass1234",
            "password_confirm": "pass9999",
            "email": "mismatch@example.com",
            "team_name": "",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "Passwords don" in r.text and "match" in r.text
    db = SessionLocal()
    try:
        assert db.query(Manager).filter(Manager.display_name == "MismatchUser").one_or_none() is None
    finally:
        db.close()


def test_register_login_forgot_reset():
    client = TestClient(app)

    r = client.post(
        "/register",
        data={
            "display_name": "AuthUser",
            "password": "pass1234",
            "password_confirm": "pass1234",
            "email": "authuser@example.com",
            "team_name": "Auth FC",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    client.post("/logout")

    bad = client.post(
        "/login",
        data={"login": "AuthUser", "password": "wrong"},
        follow_redirects=False,
    )
    assert bad.status_code == 400

    ok = client.post(
        "/login",
        data={"login": "authuser@example.com", "password": "pass1234"},
        follow_redirects=False,
    )
    assert ok.status_code == 303
    client.post("/logout")

    forgot = client.post(
        "/forgot-password",
        data={"email": "authuser@example.com"},
        follow_redirects=True,
    )
    assert forgot.status_code == 200
    assert "reset-password?token=" in forgot.text

    # Extract token from the page
    import re

    m = re.search(r"/reset-password\?token=([^\"'<\s]+)", forgot.text)
    assert m
    token = m.group(1)

    reset = client.post(
        "/reset-password",
        data={"token": token, "password": "newpass9", "password_confirm": "newpass9"},
        follow_redirects=False,
    )
    assert reset.status_code == 303

    old = client.post(
        "/login",
        data={"login": "AuthUser", "password": "pass1234"},
        follow_redirects=False,
    )
    assert old.status_code == 400

    neu = client.post(
        "/login",
        data={"login": "AuthUser", "password": "newpass9"},
        follow_redirects=False,
    )
    assert neu.status_code == 303
