"""Chip + deadline smoke tests."""

from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal, engine
from app.models import Gameweek, Manager, Player
from app.services import chips as chips_svc
from app.services import deadline as deadline_svc
from app.services import squad as squad_svc
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
    finally:
        db.close()


def test_play_tc_bb_and_cancel():
    db = SessionLocal()
    try:
        manager = Manager(display_name="Chipper", pin="2222", team_name="Chip FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.deadline_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        db.commit()

        play = chips_svc.play_chip(db, manager_id=manager.id, gameweek_id=gw.id, chip="triple_captain")
        assert play.chip == "triple_captain"
        state = chips_svc.ensure_chip_state(db, manager.id)
        assert state.triple_captain_remaining == 0

        chips_svc.cancel_chip(db, manager_id=manager.id, gameweek_id=gw.id)
        state = chips_svc.ensure_chip_state(db, manager.id)
        assert state.triple_captain_remaining == 1

        chips_svc.play_chip(db, manager_id=manager.id, gameweek_id=gw.id, chip="bench_boost")
        assert chips_svc.active_chip(db, manager.id, gw.id).chip == "bench_boost"
    finally:
        db.close()


def test_deadline_lock():
    db = SessionLocal()
    try:
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.deadline_at = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
        db.commit()
        assert deadline_svc.deadline_passed(gw) is True
        assert deadline_svc.can_edit(gw) is False
    finally:
        db.close()


def _legal_15(db):
    by_pos: dict[str, list] = {}
    for p in db.query(Player).order_by(Player.price).all():
        by_pos.setdefault(p.position, []).append(p)
    return by_pos["GK"][:2] + by_pos["DEF"][:5] + by_pos["MID"][:5] + by_pos["ATT"][:3]


def test_free_hit_snapshot_unlimited_cancel_and_restore():
    db = SessionLocal()
    try:
        manager = Manager(display_name="FreeHitter", pin="3333", team_name="FH FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        squad = _legal_15(db)
        original_ids = [p.id for p in squad]
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=original_ids, gw_number=1)

        # Extra DEF target — add after locking original 15
        if db.query(Player).filter(Player.external_id == "fh-extra-def").one_or_none() is None:
            db.add(
                Player(
                    external_id="fh-extra-def",
                    name="FH Extra DEF",
                    position="DEF",
                    team_code="BOU",
                    price=4.0,
                )
            )
            db.commit()
        replacement = db.query(Player).filter(Player.external_id == "fh-extra-def").one()
        assert replacement.id not in original_ids

        gw2 = db.query(Gameweek).filter(Gameweek.number == 2).one()
        gw2.deadline_at = (datetime.now(timezone.utc) + timedelta(days=2)).isoformat().replace("+00:00", "Z")
        gw2.is_current = 1
        gw1 = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw1.is_current = 0
        db.commit()

        play = chips_svc.play_chip(db, manager_id=manager.id, gameweek_id=gw2.id, chip="free_hit")
        assert play.chip == "free_hit"
        state = chips_svc.ensure_chip_state(db, manager.id)
        assert state.free_hit_remaining == 0
        assert squad_svc.transfers_are_unlimited(db, manager.id, gw2) is True

        out_p = next(p for p in squad if p.position == "DEF")
        squad_svc.make_transfer(
            db,
            manager_id=manager.id,
            gameweek=gw2,
            player_out_id=out_p.id,
            player_in_id=replacement.id,
        )
        owned_ids = {p.id for p in squad_svc.owned_players(db, manager.id)}
        assert replacement.id in owned_ids
        assert out_p.id not in owned_ids

        # Cancel restores snapshot + chip count
        chips_svc.cancel_chip(db, manager_id=manager.id, gameweek_id=gw2.id)
        state = chips_svc.ensure_chip_state(db, manager.id)
        assert state.free_hit_remaining == 1
        assert chips_svc.active_chip(db, manager.id, gw2.id) is None
        restored = {p.id for p in squad_svc.owned_players(db, manager.id)}
        assert restored == set(original_ids)

        # Replay FH, transfer again, then advance GW — auto-restore original 15
        chips_svc.play_chip(db, manager_id=manager.id, gameweek_id=gw2.id, chip="free_hit")
        squad_svc.make_transfer(
            db,
            manager_id=manager.id,
            gameweek=gw2,
            player_out_id=out_p.id,
            player_in_id=replacement.id,
        )
        gw3 = db.query(Gameweek).filter(Gameweek.number == 3).one()
        gw3.is_current = 1
        gw2.is_current = 0
        db.commit()
        n = chips_svc.restore_free_hits_if_needed(db, manager_id=manager.id, current_gw=gw3)
        assert n == 1
        final = {p.id for p in squad_svc.owned_players(db, manager.id)}
        assert final == set(original_ids)
        # Chip is spent after completed FH (not returned on auto-restore)
        state = chips_svc.ensure_chip_state(db, manager.id)
        assert state.free_hit_remaining == 0
    finally:
        db.close()
