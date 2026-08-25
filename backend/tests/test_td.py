"""Technical Director window behaviour."""

from app.db import Base, SessionLocal, engine
from app.models import Gameweek, Manager
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


def test_td_cannot_repeat_consecutive_club_but_can_later():
    db = SessionLocal()
    try:
        manager = Manager(display_name="TDRepeat", pin="1234", team_name="Repeat FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        td_svc.set_td_pick(db, manager_id=manager.id, club_code="LIV", gw_number=1)
        assert td_svc.can_select_td(db, manager.id, 4) is True
        try:
            td_svc.set_td_pick(db, manager_id=manager.id, club_code="LIV", gw_number=4)
            assert False, "same club twice in a row"
        except td_svc.TDError:
            pass
        td_svc.set_td_pick(db, manager_id=manager.id, club_code="ARS", gw_number=4)
        # After ARS window, LIV is allowed again
        nxt = td_svc.set_td_pick(db, manager_id=manager.id, club_code="LIV", gw_number=7)
        assert nxt.club_code == "LIV"
    finally:
        db.close()


def test_td_can_change_before_first_deadline():
    db = SessionLocal()
    try:
        manager = Manager(display_name="TDChange", pin="1234", team_name="Change FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        # Far-future deadline so can_edit is true (seed may have marked GW1 finished).
        db.query(Gameweek).update({"is_current": 0})
        gw.deadline_at = "2099-08-21T17:30:00Z"
        gw.status = "live"
        gw.is_current = 1
        from app.models import Fixture

        db.query(Fixture).filter(Fixture.gameweek_number == 1).update({"finished": 0})
        db.commit()

        first = td_svc.set_td_pick(db, manager_id=manager.id, club_code="LIV", gw_number=1)
        assert first.club_code == "LIV"
        assert td_svc.can_change_td(db, manager.id, gw) is True
        second = td_svc.set_td_pick(db, manager_id=manager.id, club_code="ARS", gw_number=1)
        assert second.club_code == "ARS"
        assert second.start_gw == 1
    finally:
        db.close()


def test_td_home_banner_warns_on_final_gw_and_urgent_when_expired():
    db = SessionLocal()
    try:
        manager = Manager(display_name="TDBanner", pin="1234", team_name="Banner FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        pick = td_svc.set_td_pick(db, manager_id=manager.id, club_code="LIV", gw_number=5)
        assert pick.end_gw == 7
        assert td_svc.td_home_banner(db, manager.id, 5) is None
        assert td_svc.td_home_banner(db, manager.id, 6) is None
        warn = td_svc.td_home_banner(db, manager.id, 7)
        assert warn is not None
        assert warn["level"] == "warn"
        assert "LIV" in warn["message"]
        assert "ends after this GW" in warn["message"]

        urgent = td_svc.td_home_banner(db, manager.id, 8)
        assert urgent is not None
        assert urgent["level"] == "urgent"
        assert "expired" in urgent["message"].lower()
    finally:
        db.close()
