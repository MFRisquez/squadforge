"""Live GW demo helpers for phone testing."""

from app.db import SessionLocal
from app.models import Manager
from app.services import demo_live as demo_svc
from app.services import squad as squad_svc


def test_live_demo_start_stop_roundtrip():
    db = SessionLocal()
    try:
        manager = db.query(Manager).filter(Manager.display_name == "TestAgent").one_or_none()
        if not manager:
            manager = Manager(display_name="DemoPhoneTester", pin="1234", team_name="Demo XI")
            db.add(manager)
            db.commit()
            db.refresh(manager)

        demo_svc.stop_live_demo(db)
        assert demo_svc.is_live_demo_active(db) is False

        started = demo_svc.start_live_demo(db, manager)
        assert started["gameweek"] >= 1
        assert demo_svc.is_live_demo_active(db) is True
        assert len(squad_svc.owned_players(db, manager.id)) == 15

        gw = squad_svc.current_gameweek(db)
        assert (gw.status or "").lower() == "live"

        stopped = demo_svc.stop_live_demo(db)
        assert stopped.get("restored") is True
        assert demo_svc.is_live_demo_active(db) is False
    finally:
        demo_svc.stop_live_demo(db)
        db.close()
