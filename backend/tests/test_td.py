"""Technical Director window behaviour."""

from app.db import Base, SessionLocal, engine
from app.models import Manager
from app.services.seed import seed_if_empty
from app.services import td as td_svc


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_if_empty(db)
    finally:
        db.close()


def test_td_can_start_anytime_then_locks_for_three_gw():
    db = SessionLocal()
    try:
        manager = Manager(display_name="TDTester", pin="1234", team_name="TD FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        assert td_svc.can_select_td(db, manager.id, 7) is True
        pick = td_svc.set_td_pick(db, manager_id=manager.id, club_code="LIV", gw_number=7)
        assert pick.start_gw == 7
        assert pick.end_gw == 9
        assert td_svc.can_select_td(db, manager.id, 8) is False

        try:
            td_svc.set_td_pick(db, manager_id=manager.id, club_code="ARS", gw_number=8)
            assert False, "should be locked mid-window"
        except td_svc.TDError:
            pass

        assert td_svc.can_select_td(db, manager.id, 10) is True
        nxt = td_svc.set_td_pick(db, manager_id=manager.id, club_code="ARS", gw_number=10)
        assert nxt.start_gw == 10 and nxt.end_gw == 12
    finally:
        db.close()
