"""Chip + deadline smoke tests."""

from datetime import datetime, timedelta, timezone

from app.db import Base, SessionLocal, engine
from app.models import Gameweek, Manager
from app.services import chips as chips_svc
from app.services import deadline as deadline_svc
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
