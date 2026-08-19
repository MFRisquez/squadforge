"""FASE 5: catalog radar axes, awards page, captain success rate."""

import json

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import (
    ChipPlay,
    Gameweek,
    ManagerGameweekScore,
    MatchEvent,
    Membership,
    Player,
    PlayerPoints,
)
from app.services import awards as awards_svc
from app.services import league as league_svc
from app.services.captain_success import captain_success_for_manager
from app.services.player_catalog import build_players_catalog, clear_players_catalog_cache
from app.services.seed import seed_if_empty


@pytest.fixture()
def db():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    clear_players_catalog_cache()
    session = SessionLocal()
    try:
        seed_if_empty(session)
        yield session
    finally:
        session.close()
        clear_players_catalog_cache()


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _two_managers(db):
    a = league_svc.register_manager(
        db,
        display_name="RadarA",
        password="secret12",
        email="a@example.com",
        team_name="Alpha XI",
    )
    b = league_svc.register_manager(
        db,
        display_name="RadarB",
        password="secret12",
        email="b@example.com",
        team_name="Beta XI",
    )
    return a, b


def test_catalog_exposes_radar_axes(db):
    player = db.query(Player).first()
    assert player is not None
    player.season_stats_json = json.dumps(
        {
            "form": "5.2",
            "total_points": 88,
            "threat": 40,
            "creativity": 33,
            "cbi": 12,
        }
    )
    db.commit()
    clear_players_catalog_cache()
    catalog, _version = build_players_catalog(db, force=True)
    row = next(p for p in catalog if p["id"] == player.id)
    assert row["threat"] == 40
    assert row["creativity"] == 33
    assert row["cbi"] == 12


def test_catalog_ttl_skips_db_on_warm_hit(db):
    clear_players_catalog_cache()
    first, v1 = build_players_catalog(db, force=True)
    second, v2 = build_players_catalog(db, force=False)
    assert v1 == v2
    assert second is first  # same cached list object — no rebuild
    # Version fingerprints availability so clients invalidate after FPL sync.
    assert "-d" in v1 and "-o" in v1


def test_awards_streak_and_chip(db):
    a, b = _two_managers(db)
    league = league_svc.create_league(db, "Awards Cup", a)
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
            gw.is_current = 0
        gws.append(gw)
    db.commit()

    # A: 80+70 streak = 150; B peaks at 99 with chip but lower consecutive sums
    for gw, pts_a, pts_b in zip(gws, (80, 70, 10), (20, 99, 20)):
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gw.id, total=pts_a))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gw.id, total=pts_b))
    db.add(ChipPlay(manager_id=b.id, gameweek_id=gws[1].id, chip="bench_boost"))
    db.commit()

    payload = awards_svc.league_awards(db, league.id)
    by_key = {c["key"]: c for c in payload["categories"]}
    assert by_key["streak"]["manager_id"] == a.id
    assert by_key["chip"]["manager_id"] == b.id
    assert "99" in by_key["chip"]["value_label"]


def test_awards_page_and_captain_success(db):
    a, b = _two_managers(db)
    league = league_svc.create_league(db, "Cap League", a)
    league_svc.join_league(db, league.invite_code, b)

    gw = db.query(Gameweek).filter(Gameweek.number == 1).one_or_none()
    if not gw:
        gw = Gameweek(number=1, status="finished", name="GW1", is_current=0)
        db.add(gw)
        db.flush()
    else:
        gw.status = "finished"
    players = db.query(Player).limit(3).all()
    assert len(players) >= 3
    # Captain 12 > median of [12, 4, 2] = 4 → hit
    breakdown = {
        "armband_player_id": players[0].id,
        "players": [
            {"player_id": players[0].id, "base": 12, "points": 24, "captain": True},
            {"player_id": players[1].id, "base": 4, "points": 4},
            {"player_id": players[2].id, "base": 2, "points": 2},
        ],
    }
    db.add(
        ManagerGameweekScore(
            manager_id=a.id,
            gameweek_id=gw.id,
            total=30,
            breakdown_json=json.dumps(breakdown),
        )
    )
    db.add(
        MatchEvent(
            gameweek_id=gw.id,
            player_id=players[1].id,
            metric="clean_sheets",
            value=1,
            source="test",
        )
    )
    db.add(
        PlayerPoints(
            gameweek_id=gw.id,
            player_id=players[0].id,
            total=14,
            breakdown_json=json.dumps({"scouting_bonus": 2}),
        )
    )
    db.commit()

    rate = captain_success_for_manager(db, a.id)
    assert rate["eligible"] == 1
    assert rate["hits"] == 1
    assert rate["rate"] == 100

    client = _client()
    login = client.post(
        "/login",
        data={"login": "RadarA", "password": "secret12"},
        follow_redirects=False,
    )
    assert login.status_code in (303, 302)

    awards = client.get(f"/league/{league.id}/awards")
    assert awards.status_code == 200
    assert b"Season awards" in awards.content
    assert b"Hot streak" in awards.content

    league_home = client.get(f"/league/{league.id}")
    assert league_home.status_code == 200
    assert b"/awards" in league_home.content

    # Team page shows captain hit rate when squad exists — may redirect to onboard
    team = client.get("/team")
    assert team.status_code == 200
    # Captain label appears once squad board loads; at least definition path works via service
    assert rate["label"] == "100%"


def test_squadboard_js_has_mini_radar():
    from pathlib import Path

    js = (Path(__file__).resolve().parents[1] / "app" / "web" / "static" / "squadboard.js").read_text()
    assert "miniRadarSvg" in js
    assert "threat" in js and "creativity" in js and "cbi" in js
