"""Transfers commit via Save (JSON), not Confirm swap."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Gameweek, Player
from app.services import league as league_svc
from app.services import squad as squad_svc
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
        for i, code in enumerate(("BOU", "CRY", "EVE", "FUL")):
            db.add(
                Player(
                    external_id=f"save-xfer-def-{i}",
                    name=f"SaveXfer DEF {i}",
                    position="DEF",
                    team_code=code,
                    price=4.0,
                )
            )
        db.commit()
    finally:
        db.close()


def _legal_15(db):
    by_pos: dict[str, list] = {}
    for p in db.query(Player).order_by(Player.price).all():
        if (p.external_id or "").startswith("save-xfer-"):
            continue
        by_pos.setdefault(p.position, []).append(p)
    return by_pos["GK"][:2] + by_pos["DEF"][:5] + by_pos["MID"][:5] + by_pos["ATT"][:3]


def _client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def test_team_html_has_no_confirm_swap_button():
    html = open("app/web/templates/team.html", encoding="utf-8").read()
    assert "Confirm swap" not in html
    assert 'id="saveSquadBtn"' in html
    assert 'id="clearSwap"' in html


def test_squadboard_save_commits_pending_transfer():
    src = open("app/web/static/squadboard.js", encoding="utf-8").read()
    assert "pendingTransferReady" in src
    assert "/transfers/make?format=json" in src
    assert "Use Confirm swap for transfers this week" not in src
    assert "Save to confirm" in src


def test_transfers_make_json_returns_ft_left():
    db = SessionLocal()
    try:
        manager = league_svc.register_manager(
            db,
            display_name="SaveXferUser",
            password="secret12",
            email="savexfer@example.com",
            team_name="Save FC",
        )
        squad = _legal_15(db)
        squad_svc.save_ownership(
            db, manager_id=manager.id, player_ids=[p.id for p in squad], gw_number=1
        )
        gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
        gw2.deadline_at = (
            (datetime.now(timezone.utc) + timedelta(days=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        gw2.is_current = 1
        db.query(Gameweek).filter(Gameweek.number == 1).update({"is_current": 0})
        db.commit()
        squad_svc.bank_free_transfers(db, manager.id, 2)
        out_p = next(p for p in squad if p.position == "DEF")
        owned = {p.id for p in squad}
        in_p = (
            db.query(Player)
            .filter(Player.external_id.like("save-xfer-def-%"), ~Player.id.in_(owned))
            .first()
        )
        assert in_p is not None
        out_id = out_p.id
        in_id = in_p.id
    finally:
        db.close()

    client = _client()
    r = client.post(
        "/login",
        data={"login": "SaveXferUser", "password": "secret12"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    res = client.post(
        "/transfers/make?format=json",
        data={"player_out_id": out_id, "player_in_id": in_id},
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    assert body["ft_left"] == 0
    assert body.get("is_hit") is False
    assert body.get("out")
    assert body.get("in")
