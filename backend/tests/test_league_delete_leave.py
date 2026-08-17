"""League delete / leave behaviour."""

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import ChipState, Gameweek, H2HMatch, League, Membership
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
    # https_only session cookies require an https base URL in TestClient
    return TestClient(app, base_url="https://testserver")


def _two_managers(db):
    owner = league_svc.register_manager(
        db,
        display_name="Owner",
        password="secret12",
        email="owner@example.com",
        team_name="Owner XI",
    )
    guest = league_svc.register_manager(
        db,
        display_name="Guest",
        password="secret12",
        email="guest@example.com",
        team_name="Guest XI",
    )
    return owner, guest


def test_delete_league_removes_memberships_and_h2h_only(db):
    owner, guest = _two_managers(db)
    league = league_svc.create_league(db, "Forge", owner, league_type="h2h")
    league_svc.join_league(db, league.invite_code, guest)
    gw = db.query(Gameweek).first()
    assert gw is not None
    db.add(
        H2HMatch(
            league_id=league.id,
            gameweek_id=gw.id,
            home_manager_id=owner.id,
            away_manager_id=guest.id,
        )
    )
    db.commit()
    lid = league.id

    with pytest.raises(league_svc.LeagueError, match="Only the league creator"):
        league_svc.delete_league(db, league, guest.id)

    league_svc.delete_league(db, league, owner.id)
    assert db.query(League).filter(League.id == lid).one_or_none() is None
    assert db.query(Membership).filter(Membership.league_id == lid).count() == 0
    assert db.query(H2HMatch).filter(H2HMatch.league_id == lid).count() == 0
    # Manager-scoped rows survive (ChipState created at register)
    assert db.query(ChipState).filter(ChipState.manager_id == owner.id).count() == 1
    assert db.query(ChipState).filter(ChipState.manager_id == guest.id).count() == 1


def test_leave_league_blocks_owner_and_drops_guest(db):
    owner, guest = _two_managers(db)
    league = league_svc.create_league(db, "Forge", owner)
    league_svc.join_league(db, league.invite_code, guest)

    with pytest.raises(league_svc.LeagueError, match="can't leave"):
        league_svc.leave_league(db, league, owner.id)

    league_svc.leave_league(db, league, guest.id)
    assert (
        db.query(Membership)
        .filter(Membership.league_id == league.id, Membership.manager_id == guest.id)
        .one_or_none()
        is None
    )
    assert (
        db.query(Membership)
        .filter(Membership.league_id == league.id, Membership.manager_id == owner.id)
        .one_or_none()
        is not None
    )


def test_delete_and_leave_http_routes(db):
    owner, guest = _two_managers(db)
    league = league_svc.create_league(db, "WhatsApp Cup", owner)
    league_svc.join_league(db, league.invite_code, guest)
    lid = league.id

    client = _client()
    # Guest leaves
    assert (
        client.post(
            "/login",
            data={"login": "Guest", "password": "secret12"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    r = client.post(f"/league/{lid}/leave", follow_redirects=False)
    assert r.status_code == 303
    assert "/leagues" in r.headers["location"]
    assert (
        db.query(Membership)
        .filter(Membership.league_id == lid, Membership.manager_id == guest.id)
        .one_or_none()
        is None
    )

    # Owner deletes
    assert (
        client.post(
            "/login",
            data={"login": "Owner", "password": "secret12"},
            follow_redirects=False,
        ).status_code
        == 303
    )
    r = client.post(f"/league/{lid}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert "/leagues" in r.headers["location"]
    assert db.query(League).filter(League.id == lid).one_or_none() is None


def test_league_page_shows_delete_or_leave(db):
    owner, guest = _two_managers(db)
    league = league_svc.create_league(db, "UI League", owner)
    league_svc.join_league(db, league.invite_code, guest)
    client = _client()

    client.post("/login", data={"login": "Owner", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{league.id}").text
    assert "Delete league" in html
    assert "Leave league" not in html
    assert "This deletes the league for everyone" in html

    client.post("/login", data={"login": "Guest", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{league.id}").text
    assert "Leave league" in html
    assert "Delete league" not in html


def test_leave_confirm_safe_with_apostrophe_league_name(db):
    """Apostrophe in league name must not break JS/HTML (use tojson data attr)."""
    import json
    import re

    owner, guest = _two_managers(db)
    league = league_svc.create_league(db, "Manu's Cup", owner)
    league_svc.join_league(db, league.invite_code, guest)
    client = _client()

    client.post("/login", data={"login": "Guest", "password": "secret12"}, follow_redirects=False)
    html = client.get(f"/league/{league.id}").text

    # Must not use the broken inline confirm('Leave Manu's Cup?') pattern
    assert "confirm('Leave " not in html
    assert 'class="js-leave-league"' in html or "class='js-leave-league'" in html

    m = re.search(r'data-league-name=(".*?"|\'.*?\')', html)
    assert m, "expected data-league-name attribute on leave form"
    attr = m.group(1)
    # Attribute is well-formed JSON from |tojson (quotes are the delimiters)
    if attr.startswith('"'):
        body = attr[1:-1]
        name = json.loads(f'"{body}"')
    else:
        name = json.loads(attr[1:-1] if attr[0] in "'\"" else attr)
    assert name == "Manu's Cup"
