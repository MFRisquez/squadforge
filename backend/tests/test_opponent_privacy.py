"""Opponent squad privacy — never leak live XIs before the deadline."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.main import app
from app.models import Gameweek, Player, SquadPick
from app.services import league as league_svc
from app.services import squad as squad_svc
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


def _legal_15(db):
    """Build a 2/5/5/3 squad within club + budget limits (FPL catalogue)."""
    from collections import Counter

    need = {"GK": 2, "DEF": 5, "MID": 5, "ATT": 3}
    picked: list[Player] = []
    club_counts: Counter[str] = Counter()
    spend = 0.0
    by_pos: dict[str, list] = {}
    for p in db.query(Player).order_by(Player.price.asc(), Player.id.asc()).all():
        by_pos.setdefault(p.position, []).append(p)
    for pos, count in need.items():
        for p in by_pos.get(pos, []):
            if need[pos] <= 0:
                break
            if club_counts[p.team_code] >= settings.max_per_club:
                continue
            if spend + p.price > settings.budget + 1e-6:
                continue
            picked.append(p)
            club_counts[p.team_code] += 1
            spend += p.price
            need[pos] -= 1
    assert sum(need.values()) == 0, f"could not build legal 15: remaining={need}"
    return picked


def test_gw1_before_deadline_hides_opponent_squad():
    """GW1 has no previous GW — pre-deadline peek must not expose any foreign picks."""
    db = SessionLocal()
    try:
        me = league_svc.register_manager(
            db,
            display_name="PeekMe",
            password="secret12",
            email="peekme@example.com",
            team_name="My XI",
        )
        rival = league_svc.register_manager(
            db,
            display_name="PeekRival",
            password="secret12",
            email="peekrival@example.com",
            team_name="Rival XI",
        )
        league = league_svc.create_league(db, "Privacy League", me, league_type="h2h")
        league_svc.join_league(db, league.invite_code, rival)

        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        db.query(Gameweek).update({"is_current": 0})
        gw1.is_current = 1
        gw1.status = "upcoming"
        gw1.deadline_at = (
            (datetime.now(timezone.utc) + timedelta(days=3))
            .isoformat()
            .replace("+00:00", "Z")
        )
        # Seed/FPL sync may have marked GW1 fixtures finished — keep us on GW1.
        from app.models import Fixture

        db.query(Fixture).filter(Fixture.gameweek_number == 1).update({"finished": 0})
        db.commit()

        squad = _legal_15(db)
        ids = [p.id for p in squad]
        secret_names = [p.name for p in squad]
        squad_svc.save_ownership(db, manager_id=rival.id, player_ids=ids, gw_number=1)
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(squad)
        squad_svc.save_lineup(
            db,
            manager_id=rival.id,
            gameweek_id=gw1.id,
            starter_ids=starters,
            captain_id=captain,
            vice_id=vice,
        )
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == rival.id, SquadPick.gameweek_id == gw1.id)
            .all()
        )
        assert len(picks) == 15
        lid = league.id
        rival_id = rival.id
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "PeekMe", "password": "secret12"}, follow_redirects=False)
    r = client.get(f"/league/{lid}/opponent/{rival_id}?gw=1")
    assert r.status_code == 200
    html = r.text

    assert "Squads reveal once the GW1 deadline passes" in html
    assert "Squad not available yet" in html
    assert "Not revealed yet" in html
    # No pitch / compare rail with their players
    assert 'id="opponentPitch"' not in html
    for name in secret_names:
        assert name not in html, f"leaked opponent player: {name}"


def test_gw1_after_deadline_shows_opponent_squad():
    """Once GW1 deadline passes, locked squads are visible."""
    db = SessionLocal()
    try:
        me = league_svc.register_manager(
            db,
            display_name="PostMe",
            password="secret12",
            email="postme@example.com",
            team_name="Post My XI",
        )
        rival = league_svc.register_manager(
            db,
            display_name="PostRival",
            password="secret12",
            email="postrival@example.com",
            team_name="Post Rival XI",
        )
        league = league_svc.create_league(db, "Post Privacy League", me, league_type="classic")
        league_svc.join_league(db, league.invite_code, rival)

        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        db.query(Gameweek).update({"is_current": 0})
        gw1.is_current = 1
        gw1.status = "live"
        gw1.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(hours=2))
            .isoformat()
            .replace("+00:00", "Z")
        )
        from app.models import Fixture

        db.query(Fixture).filter(Fixture.gameweek_number == 1).update({"finished": 0})
        db.commit()

        squad = _legal_15(db)
        ids = [p.id for p in squad]
        marker = squad[0].name
        squad_svc.save_ownership(db, manager_id=rival.id, player_ids=ids, gw_number=1)
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(squad)
        squad_svc.save_lineup(
            db,
            manager_id=rival.id,
            gameweek_id=gw1.id,
            starter_ids=starters,
            captain_id=captain,
            vice_id=vice,
        )
        lid = league.id
        rival_id = rival.id
    finally:
        db.close()

    client = _client()
    client.post("/login", data={"login": "PostMe", "password": "secret12"}, follow_redirects=False)
    r = client.get(f"/league/{lid}/opponent/{rival_id}?gw=1")
    assert r.status_code == 200
    html = r.text
    assert "Squads reveal once the GW1 deadline passes" not in html
    assert marker in html
    assert 'id="opponentPitch"' in html
