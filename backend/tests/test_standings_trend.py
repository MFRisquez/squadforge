"""Standings helpers: GW points trend sparkline data."""

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import (
    Gameweek,
    League,
    Manager,
    ManagerGameweekScore,
    Membership,
    OwnedPlayer,
    Player,
    TransferState,
)
from app.services import standings as standings_svc


def setup_module():
    settings.reset_db_on_startup = False
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def _reset_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def test_gw_points_trend_order_and_limit():
    _reset_db()
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


def test_classic_standings_batch_matches_expected_fields():
    """Batch standings path returns the same field shapes/values for a small league."""
    _reset_db()
    db = SessionLocal()
    try:
        a = Manager(display_name="Alpha Mgr", email="a@test.local", password_hash="x", team_name="Alpha")
        b = Manager(display_name="Beta Mgr", email="b@test.local", password_hash="x", team_name="Beta")
        db.add_all([a, b])
        db.flush()
        gws = []
        for n in range(1, 7):
            gw = Gameweek(number=n, name=f"GW{n}", is_current=1 if n == 6 else 0)
            db.add(gw)
            gws.append(gw)
        db.flush()
        current = gws[-1]
        # Alpha scores high; Beta scores low — Alpha ranks 1 by total.
        for i, gw in enumerate(gws):
            db.add(
                ManagerGameweekScore(
                    manager_id=a.id,
                    gameweek_id=gw.id,
                    squad_points=float(20 + i),
                    td_points=0,
                    total=float(20 + i),
                )
            )
            db.add(
                ManagerGameweekScore(
                    manager_id=b.id,
                    gameweek_id=gw.id,
                    squad_points=float(5 + i),
                    td_points=0,
                    total=float(5 + i),
                )
            )
        league = League(name="Batch League", invite_code="BATCH1", league_type="classic", owner_id=a.id)
        db.add(league)
        db.flush()
        db.add_all(
            [
                Membership(league_id=league.id, manager_id=a.id),
                Membership(league_id=league.id, manager_id=b.id),
            ]
        )
        p1 = Player(external_id="ba1", name="P1", position="MID", team_code="ARS", price=5.0)
        p2 = Player(external_id="bb1", name="P2", position="MID", team_code="CHE", price=6.0)
        db.add_all([p1, p2])
        db.flush()
        db.add_all(
            [
                OwnedPlayer(manager_id=a.id, player_id=p1.id),
                OwnedPlayer(manager_id=b.id, player_id=p2.id),
            ]
        )
        db.add_all(
            [
                TransferState(manager_id=a.id, free_transfers=2, last_banked_gw=6),
                TransferState(manager_id=b.id, free_transfers=1, last_banked_gw=6),
            ]
        )
        db.commit()

        rows = standings_svc.classic_standings(db, league, current)
        assert [r["manager"].id for r in rows] == [a.id, b.id]
        assert rows[0]["rank"] == 1
        assert rows[1]["rank"] == 2
        assert rows[0]["team_name"] == "Alpha"
        assert rows[0]["gw_points"] == 25.0
        assert rows[0]["total_points"] == sum(20 + i for i in range(6))
        assert rows[0]["trend"] == [20.0, 21.0, 22.0, 23.0, 24.0, 25.0]
        assert rows[0]["form"]
        assert rows[0]["players_owned"] == 1
        assert rows[0]["squad_value"] == 5.0
        assert rows[0]["ft_left"] == 2
        assert rows[0]["prev_rank"] is not None
        assert "_totals_by_number" not in rows[0]
        single = standings_svc._manager_row_base(db, a, current)
        assert single["total_points"] == rows[0]["total_points"]
        assert single["trend"] == rows[0]["trend"]
        assert single["gw_points"] == rows[0]["gw_points"]
    finally:
        db.close()
