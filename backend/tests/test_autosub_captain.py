"""Autosubs + captain armband wait for fixture finished (not early kickoffs)."""

from __future__ import annotations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Fixture, Gameweek, Player, SquadPick
from app.services import league as league_svc
from app.services import live_scoring as live_svc
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


def _xi_picks(db, manager_id: int, gw_id: int, players: list[Player], captain_id: int, vice_id: int):
    starters = players[:11]
    bench = players[11:15]
    for i, pl in enumerate(starters):
        db.add(
            SquadPick(
                manager_id=manager_id,
                gameweek_id=gw_id,
                player_id=pl.id,
                is_starter=1,
                is_captain=1 if pl.id == captain_id else 0,
                is_vice_captain=1 if pl.id == vice_id else 0,
                bench_order=0,
            )
        )
    for i, pl in enumerate(bench):
        db.add(
            SquadPick(
                manager_id=manager_id,
                gameweek_id=gw_id,
                player_id=pl.id,
                is_starter=0,
                is_captain=0,
                is_vice_captain=0,
                bench_order=i + 1,
            )
        )
    db.commit()


def test_autosub_waits_until_starter_fixture_finished():
    db = SessionLocal()
    try:
        mgr = league_svc.register_manager(
            db,
            display_name="AutoSubMgr",
            password="secret12",
            email="autosub@example.com",
            team_name="Autosub FC",
        )
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        by_pos: dict[str, list[Player]] = {"GK": [], "DEF": [], "MID": [], "ATT": []}
        for p in db.query(Player).order_by(Player.id).all():
            by_pos.setdefault(p.position, []).append(p)
        squad = (
            by_pos["GK"][:2]
            + by_pos["DEF"][:5]
            + by_pos["MID"][:5]
            + by_pos["ATT"][:3]
        )
        assert len(squad) == 15
        starter_ids, _, captain_id, vice_id = squad_svc.default_lineup_from_owned(squad)
        starters = [p for p in squad if p.id in starter_ids]
        bench = [p for p in squad if p.id not in starter_ids]
        assert len(starters) == 11 and len(bench) >= 1
        # Same-position swap always keeps a legal XI shape.
        blank = next(p for p in starters if p.position == "MID")
        bench_in = next(p for p in bench if p.position == "MID")
        blank.team_code = "BLN"
        bench_in.team_code = "BNC"
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        db.add(
            Fixture(
                fpl_id=88001,
                gameweek_number=1,
                home_club_code="BLN",
                away_club_code="OTH",
                started=0,
                finished=0,
            )
        )
        db.add(
            Fixture(
                fpl_id=88002,
                gameweek_number=1,
                home_club_code="BNC",
                away_club_code="XYZ",
                started=1,
                finished=1,
            )
        )
        ordered = starters + bench
        _xi_picks(db, mgr.id, gw.id, ordered, captain_id=captain_id, vice_id=vice_id)
        owned = squad
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == mgr.id, SquadPick.gameweek_id == gw.id)
            .all()
        )
        minutes = {p.id: 0.0 for p in squad}
        minutes[bench_in.id] = 90.0

        effective, _, _ = live_svc._apply_autosubs(
            db, owned=owned, picks=picks, minutes=minutes, gw_number=1
        )
        assert blank.id in effective
        assert bench_in.id not in effective

        fx = db.query(Fixture).filter(Fixture.fpl_id == 88001).one()
        fx.started = 1
        fx.finished = 1
        db.commit()
        effective2, _, _ = live_svc._apply_autosubs(
            db, owned=owned, picks=picks, minutes=minutes, gw_number=1
        )
        assert blank.id not in effective2
        assert bench_in.id in effective2
    finally:
        db.close()


def test_captain_armband_waits_for_captain_fixture_finished():
    minutes = {10: 0.0, 20: 90.0}
    # Vice already played, captain not finished → captain keeps armband
    assert (
        squad_svc.effective_captain_id(
            10, 20, minutes, captain_fixture_finished=False
        )
        == 10
    )
    # Captain finished blank → vice gets armband
    assert (
        squad_svc.effective_captain_id(
            10, 20, minutes, captain_fixture_finished=True
        )
        == 20
    )
    # Captain played → keeps armband even if fixture finished
    assert (
        squad_svc.effective_captain_id(
            10, 20, {10: 60.0, 20: 90.0}, captain_fixture_finished=True
        )
        == 10
    )


def test_h2h_show_scores_after_deadline_even_if_status_upcoming():
    from datetime import datetime, timedelta, timezone

    from app.services import standings as standings_svc

    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="ShowA",
            password="secret12",
            email="showa@example.com",
            team_name="Show A",
        )
        b = league_svc.register_manager(
            db,
            display_name="ShowB",
            password="secret12",
            email="showb@example.com",
            team_name="Show B",
        )
        league = league_svc.create_league(db, "Show Cup", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        gw.status = "upcoming"
        gw.deadline_at = (
            (datetime.now(timezone.utc) - timedelta(minutes=5))
            .isoformat()
            .replace("+00:00", "Z")
        )
        db.commit()
        cards = standings_svc.h2h_fixture_cards(db, league, gw)
        assert cards
        assert cards[0]["show_scores"] is True
    finally:
        db.close()


def test_resolve_h2h_keeps_live_points_while_pending():
    from app.models import H2HMatch, ManagerGameweekScore
    from app.services import standings as standings_mod

    db = SessionLocal()
    try:
        a = league_svc.register_manager(
            db,
            display_name="PtsPendA",
            password="secret12",
            email="ptspenda@example.com",
            team_name="Pts Pend A",
        )
        b = league_svc.register_manager(
            db,
            display_name="PtsPendB",
            password="secret12",
            email="ptspendb@example.com",
            team_name="Pts Pend B",
        )
        league = league_svc.create_league(db, "Pts Pending", a, league_type="h2h")
        league_svc.join_league(db, league.invite_code, b)
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        db.query(Fixture).filter(Fixture.gameweek_number == 1).update(
            {"started": 0, "finished": 0}
        )
        standings_mod.ensure_h2h_pairings(db, league, gw)
        db.add(ManagerGameweekScore(manager_id=a.id, gameweek_id=gw.id, total=7))
        db.add(ManagerGameweekScore(manager_id=b.id, gameweek_id=gw.id, total=3))
        db.commit()
        live_svc.resolve_h2h(db, gw)
        for m in db.query(H2HMatch).filter(H2HMatch.league_id == league.id).all():
            assert m.result == "pending"
            assert float(m.home_points) + float(m.away_points) == 10.0
    finally:
        db.close()
