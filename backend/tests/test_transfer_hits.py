"""Transfer hits (−4) when free transfers are spent."""

from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal, engine
from app.models import Gameweek, Manager, Player
from app.services import squad as squad_svc
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
        for i, code in enumerate(("BOU", "CRY", "EVE", "FUL")):
            db.add(
                Player(
                    external_id=f"hit-def-{i}",
                    name=f"Hit DEF {i}",
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
        if (p.external_id or "").startswith("hit-"):
            continue
        by_pos.setdefault(p.position, []).append(p)
    return by_pos["GK"][:2] + by_pos["DEF"][:5] + by_pos["MID"][:5] + by_pos["ATT"][:3]


def test_hit_after_free_transfers_exhausted():
    db = SessionLocal()
    try:
        manager = Manager(display_name="Hitter", pin="4444", team_name="Hit FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        squad = _legal_15(db)
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=[p.id for p in squad], gw_number=1)

        gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
        gw2.deadline_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        gw2.is_current = 1
        db.query(Gameweek).filter(Gameweek.number == 1).update({"is_current": 0})
        db.commit()

        # Bank into GW2 → exactly 1 FT (not 2)
        state = squad_svc.bank_free_transfers(db, manager.id, 2)
        assert state.free_transfers == 1
        start_ft = state.free_transfers

        owned = {p.id for p in squad_svc.owned_players(db, manager.id)}
        out_pool = [p for p in squad if p.position == "DEF"]
        targets = (
            db.query(Player)
            .filter(Player.external_id.like("hit-def-%"), ~Player.id.in_(owned))
            .all()
        )
        assert len(targets) >= 2

        # Spend free transfers without hits
        for i in range(start_ft):
            out_p = out_pool[i]
            in_p = targets[i]
            squad_svc.make_transfer(
                db,
                manager_id=manager.id,
                gameweek=gw2,
                player_out_id=out_p.id,
                player_in_id=in_p.id,
            )
        state = squad_svc.get_transfer_state(db, manager.id)
        assert state.free_transfers == 0
        assert squad_svc.hit_transfers_this_gw(db, manager.id, gw2.id) == 0

        # Next transfer is a hit
        owned = {p.id for p in squad_svc.owned_players(db, manager.id)}
        out_p = next(p for p in squad_svc.owned_players(db, manager.id) if p.position == "DEF")
        in_p = next(p for p in targets if p.id not in owned)
        squad_svc.make_transfer(
            db,
            manager_id=manager.id,
            gameweek=gw2,
            player_out_id=out_p.id,
            player_in_id=in_p.id,
        )
        assert squad_svc.hit_transfers_this_gw(db, manager.id, gw2.id) == 1
        assert squad_svc.transfer_hit_points(db, manager.id, gw2.id) == -4.0
        state = squad_svc.get_transfer_state(db, manager.id)
        assert state.free_transfers == 0
    finally:
        db.close()


def test_one_free_transfer_per_gameweek_after_gw1():
    db = SessionLocal()
    try:
        manager = Manager(display_name="FTer", pin="5555", team_name="FT FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)
        s1 = squad_svc.bank_free_transfers(db, manager.id, 1)
        assert s1.free_transfers == 0
        s2 = squad_svc.bank_free_transfers(db, manager.id, 2)
        assert s2.free_transfers == 1
        s3 = squad_svc.bank_free_transfers(db, manager.id, 3)
        assert s3.free_transfers == 2
        # Legacy double-credit clamp
        s3.free_transfers = 9
        s3.last_banked_gw = 3
        db.commit()
        s3b = squad_svc.bank_free_transfers(db, manager.id, 3)
        assert s3b.free_transfers == 2
    finally:
        db.close()
