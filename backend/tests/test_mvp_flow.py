"""MVP flow with ownership + lineup + live FPL seed."""

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Player
from app.services.seed import seed_demo_fallback, ensure_demo_league
from app.services import squad as squad_svc


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # Deterministic offline catalogue for CI/smoke (no network in tests)
        seed_demo_fallback(db)
        ensure_demo_league(db)
        # Expand demo players to a full legal market
        if db.query(Player).count() < 15:
            seed_demo_fallback(db)
        # Add more priced players so transfers have targets
        existing = db.query(Player).count()
        if existing < 30:
            for i in range(3):
                db.add(
                    Player(
                        external_id=f"xgk-{i}",
                        name=f"Extra GK {i}",
                        position="GK",
                        team_code="TOT",
                        price=4.0,
                    )
                )
            for i in range(8):
                db.add(
                    Player(
                        external_id=f"xdef-{i}",
                        name=f"Extra DEF {i}",
                        position="DEF",
                        team_code="NEW",
                        price=4.0 + (i % 3) * 0.5,
                    )
                )
            for i in range(8):
                db.add(
                    Player(
                        external_id=f"xmid-{i}",
                        name=f"Extra MID {i}",
                        position="MID",
                        team_code="BHA",
                        price=4.5 + (i % 3) * 0.5,
                    )
                )
            for i in range(5):
                db.add(
                    Player(
                        external_id=f"xatt-{i}",
                        name=f"Extra ATT {i}",
                        position="ATT",
                        team_code="WHU",
                        price=4.5 + (i % 3) * 0.5,
                    )
                )
            db.commit()
    finally:
        db.close()


def test_home_login_squad_lineup_transfer():
    client = TestClient(app)
    assert client.get("/").status_code == 200

    r = client.post(
        "/login",
        data={"display_name": "Manuel", "pin": "1234", "team_name": "Forge FC"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    r = client.post("/league/join", data={"invite_code": "FORGE1"}, follow_redirects=False)
    assert r.status_code == 303

    db = SessionLocal()
    try:
        by_pos = {}
        for p in db.query(Player).order_by(Player.price).all():
            by_pos.setdefault(p.position, []).append(p)
        squad = by_pos["GK"][:2] + by_pos["DEF"][:5] + by_pos["MID"][:5] + by_pos["ATT"][:3]
        player_ids = [p.id for p in squad]
        out_player = squad[2]
        # someone not in squad same position ideally
        replacement = next(p for p in by_pos["DEF"] if p.id not in player_ids)
    finally:
        db.close()

    r = client.post(
        "/team/save",
        data={"player_id": [str(i) for i in player_ids]},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:400]

    # lineup page loads
    assert client.get("/lineup").status_code == 200

    starters = player_ids[:1] + player_ids[2:5] + player_ids[7:11] + player_ids[12:15]
    # ensure 11
    starters = starters[:11]
    r = client.post(
        "/lineup/save",
        data={
            "starter_id": [str(i) for i in starters],
            "captain_id": str(starters[-1]),
            "vice_id": str(starters[0]),
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:500]

    # transfers now live on /team
    r = client.get("/transfers", follow_redirects=False)
    assert r.status_code == 303
    assert "/team" in r.headers.get("location", "")
    assert client.get("/team").status_code == 200
    r = client.post(
        "/transfers/make",
        data={"player_out_id": out_player.id, "player_in_id": replacement.id},
        follow_redirects=False,
    )
    assert r.status_code == 303, r.text[:500]
