"""Standings helpers: GW points trend sparkline data."""

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Gameweek, Manager, ManagerGameweekScore
from app.services import standings as standings_svc


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_gw_points_trend_order_and_limit():
    db = SessionLocal()
    try:
        mgr = Manager(display_name="Trend Tester", email="trend@test.local", password_hash="x")
        db.add(mgr)
        db.flush()
        gws = []
        for n in range(1, 9):
            gw = Gameweek(number=n, name=f"GW{n}", deadline_at=None, is_current=1 if n == 8 else 0)
            db.add(gw)
            gws.append(gw)
        db.flush()
        for i, gw in enumerate(gws):
            db.add(
                ManagerGameweekScore(
                    manager_id=mgr.id,
                    gameweek_id=gw.id,
                    squad_points=float(10 + i),
                    td_points=0,
                    total=float(10 + i),
                )
            )
        db.commit()

        trend = standings_svc.gw_points_trend(db, mgr.id, last_n=6)
        assert trend == [12.0, 13.0, 14.0, 15.0, 16.0, 17.0]
        assert standings_svc._trend_is_rising(trend) is True
        assert standings_svc.trend_polyline(trend)
        assert standings_svc.trend_polyline([5.0]) == ""
    finally:
        db.close()
