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


def _build_xi_squad(db) -> tuple[list[Player], list[Player], list[Player], int, int]:
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
    return squad, starters, bench, captain_id, vice_id


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
        squad, starters, bench, captain_id, vice_id = _build_xi_squad(db)
        # Same-position swap always keeps a legal XI shape.
        blank = next(p for p in starters if p.position == "MID")
        bench_in = next(p for p in bench if p.position == "MID")
        blank.team_code = "BLN"
        bench_in.team_code = "BNC"
        # Other squad players: finished blanks so they aren't autosub candidates.
        for i, pl in enumerate(p for p in squad if p.id not in {blank.id, bench_in.id}):
            pl.team_code = f"X{i:02d}"
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        db.add(
            Fixture(
                fpl_id=88001,
                gameweek_number=1,
                home_club_code="BLN",
                away_club_code="OTH",
                kickoff_at="2026-08-16T14:00:00Z",
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
                kickoff_at="2026-08-14T19:00:00Z",
                started=1,
                finished=1,
            )
        )
        fid = 88010
        for pl in squad:
            if pl.id in {blank.id, bench_in.id}:
                continue
            db.add(
                Fixture(
                    fpl_id=fid,
                    gameweek_number=1,
                    home_club_code=pl.team_code,
                    away_club_code="ZZZ",
                    kickoff_at="2026-08-14T19:00:00Z",
                    started=1,
                    finished=1,
                )
            )
            fid += 1
        db.commit()
        ordered = starters + bench
        _xi_picks(db, mgr.id, gw.id, ordered, captain_id=captain_id, vice_id=vice_id)
        owned = squad
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == mgr.id, SquadPick.gameweek_id == gw.id)
            .all()
        )
        # Other starters already played; only blank is still at 0' (fixture pending).
        minutes = {p.id: 90.0 for p in squad}
        minutes[blank.id] = 0.0
        minutes[bench_in.id] = 90.0
        for pl in bench:
            if pl.id != bench_in.id:
                minutes[pl.id] = 0.0

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


def test_autosub_skips_sunday_starter_while_friday_match_done():
    """GW split Fri–Sun: Sunday XI with 0' must not be autosubbed on Friday night."""
    db = SessionLocal()
    try:
        mgr = league_svc.register_manager(
            db,
            display_name="FriSunMgr",
            password="secret12",
            email="frisun@example.com",
            team_name="Fri Sun FC",
        )
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        squad, starters, bench, captain_id, vice_id = _build_xi_squad(db)
        sunday_starter = next(p for p in starters if p.position == "MID")
        friday_bench = next(p for p in bench if p.position == "MID")
        sunday_starter.team_code = "SUN"
        friday_bench.team_code = "FRI"
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        # Friday: finished — bench already has minutes.
        db.add(
            Fixture(
                fpl_id=88101,
                gameweek_number=1,
                home_club_code="FRI",
                away_club_code="OTH",
                kickoff_at="2026-08-14T19:00:00Z",
                started=1,
                finished=1,
            )
        )
        # Sunday: not kicked off — starter still at 0'.
        db.add(
            Fixture(
                fpl_id=88102,
                gameweek_number=1,
                home_club_code="SUN",
                away_club_code="XYZ",
                kickoff_at="2026-08-16T14:00:00Z",
                started=0,
                finished=0,
            )
        )
        db.commit()
        ordered = starters + bench
        _xi_picks(db, mgr.id, gw.id, ordered, captain_id=captain_id, vice_id=vice_id)
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == mgr.id, SquadPick.gameweek_id == gw.id)
            .all()
        )
        # Rest of XI already played; only Sunday starter is still at 0'.
        minutes = {p.id: 90.0 for p in squad}
        minutes[sunday_starter.id] = 0.0

        effective, _, _ = live_svc._apply_autosubs(
            db, owned=squad, picks=picks, minutes=minutes, gw_number=1
        )
        assert sunday_starter.id in effective, "Sunday starter must stay in XI pre-kickoff"
        assert friday_bench.id not in effective
    finally:
        db.close()


def test_autosub_friday_blank_takes_sunday_bench_before_kickoff():
    """Friday blank (0') is replaced by Sunday bench even while Sunday is still 0'."""
    db = SessionLocal()
    try:
        mgr = league_svc.register_manager(
            db,
            display_name="BlankFriMgr",
            password="secret12",
            email="blankfri@example.com",
            team_name="Blank Fri FC",
        )
        gw = db.query(Gameweek).filter(Gameweek.number == 1).one()
        squad, starters, bench, captain_id, vice_id = _build_xi_squad(db)
        friday_blank = next(p for p in starters if p.position == "MID")
        sunday_bench = next(p for p in bench if p.position == "MID")
        # Another Friday bench who finished blank — must be skipped.
        other_bench = next(p for p in bench if p.position != "MID" and p.id != sunday_bench.id)
        friday_blank.team_code = "FRB"
        sunday_bench.team_code = "SUN"
        other_bench.team_code = "FRX"
        for i, pl in enumerate(
            p for p in squad if p.id not in {friday_blank.id, sunday_bench.id, other_bench.id}
        ):
            pl.team_code = f"Z{i:02d}"
        db.query(Fixture).filter(Fixture.gameweek_number == 1).delete()
        db.add(
            Fixture(
                fpl_id=88201,
                gameweek_number=1,
                home_club_code="FRB",
                away_club_code="OTH",
                kickoff_at="2026-08-14T19:00:00Z",
                started=1,
                finished=1,
            )
        )
        db.add(
            Fixture(
                fpl_id=88202,
                gameweek_number=1,
                home_club_code="FRX",
                away_club_code="AAA",
                kickoff_at="2026-08-14T19:00:00Z",
                started=1,
                finished=1,
            )
        )
        db.add(
            Fixture(
                fpl_id=88203,
                gameweek_number=1,
                home_club_code="SUN",
                away_club_code="XYZ",
                kickoff_at="2026-08-16T14:00:00Z",
                started=0,
                finished=0,
            )
        )
        fid = 88210
        for pl in squad:
            if pl.id in {friday_blank.id, sunday_bench.id, other_bench.id}:
                continue
            db.add(
                Fixture(
                    fpl_id=fid,
                    gameweek_number=1,
                    home_club_code=pl.team_code,
                    away_club_code="ZZZ",
                    kickoff_at="2026-08-14T19:00:00Z",
                    started=1,
                    finished=1,
                )
            )
            fid += 1
        db.commit()
        ordered = starters + bench
        _xi_picks(db, mgr.id, gw.id, ordered, captain_id=captain_id, vice_id=vice_id)
        # Bench order: finished blank first (must be skipped), then Sunday MID.
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == mgr.id, SquadPick.gameweek_id == gw.id)
            .all()
        )
        by_pid = {p.player_id: p for p in picks}
        by_pid[other_bench.id].bench_order = 1
        by_pid[sunday_bench.id].bench_order = 2
        order = 3
        for p in picks:
            if not p.is_starter and p.player_id not in {other_bench.id, sunday_bench.id}:
                p.bench_order = order
                order += 1
        db.commit()
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == mgr.id, SquadPick.gameweek_id == gw.id)
            .all()
        )
        minutes = {p.id: 90.0 for p in squad}
        minutes[friday_blank.id] = 0.0
        minutes[sunday_bench.id] = 0.0
        minutes[other_bench.id] = 0.0

        effective, _, _ = live_svc._apply_autosubs(
            db, owned=squad, picks=picks, minutes=minutes, gw_number=1
        )
        assert friday_blank.id not in effective
        assert sunday_bench.id in effective
        assert other_bench.id not in effective
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
