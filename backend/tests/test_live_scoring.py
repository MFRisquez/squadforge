"""Live / demo gameweek scoring pipeline."""

from app.db import Base, SessionLocal, engine
from app.models import Manager, Player
from app.services import live_scoring as live_svc
from app.services import squad as squad_svc
from app.services.seed import ensure_demo_league, seed_demo_fallback


def setup_module():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        seed_demo_fallback(db)
        ensure_demo_league(db)
        # Expand market a bit for transfers / ownership
        if db.query(Player).count() < 30:
            for i in range(4):
                db.add(
                    Player(
                        external_id=f"xdef-{i}",
                        name=f"Extra DEF {i}",
                        position="DEF",
                        team_code="NEW",
                        price=4.5,
                    )
                )
            for i in range(4):
                db.add(
                    Player(
                        external_id=f"xmid-{i}",
                        name=f"Extra MID {i}",
                        position="MID",
                        team_code="BHA",
                        price=5.0,
                    )
                )
            db.commit()
    finally:
        db.close()


def test_demo_scoring_writes_manager_total():
    db = SessionLocal()
    try:
        manager = Manager(display_name="Scorer", pin="1111", team_name="Pts FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        by_pos: dict[str, list[Player]] = {}
        for p in db.query(Player).order_by(Player.price).all():
            by_pos.setdefault(p.position, []).append(p)

        need = {"GK": 2, "DEF": 5, "MID": 5, "ATT": 3}
        squad: list[Player] = []
        club_counts: dict[str, int] = {}
        for pos, n in need.items():
            for p in by_pos.get(pos, []):
                if club_counts.get(p.team_code, 0) >= 3:
                    continue
                squad.append(p)
                club_counts[p.team_code] = club_counts.get(p.team_code, 0) + 1
                if sum(1 for x in squad if x.position == pos) >= n:
                    break
        assert len(squad) == 15, f"could only pick {len(squad)}"
        ids = [p.id for p in squad]
        gw = squad_svc.current_gameweek(db)
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=ids, gw_number=gw.number)
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(
            squad_svc.owned_players(db, manager.id)
        )
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starters,
            captain_id=captain,
            vice_id=vice,
        )

        summary = live_svc.run_gameweek_scoring(db, force_demo=True)
        assert summary["managers_scored"] >= 1
        assert summary["players_scored"] >= 1
        assert summary["ingest"]["source"] == "demo_sim"

        from app.models import ManagerGameweekScore, MatchEvent

        row = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager.id,
                ManagerGameweekScore.gameweek_id == gw.id,
            )
            .one()
        )
        assert row.total != 0 or row.squad_points >= 0
        assert (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.source == "demo_sim")
            .count()
            > 0
        )
        assert live_svc.is_demo_scoring_active(db, gw) is True
    finally:
        db.close()


def test_auto_scoring_never_falls_back_to_demo(monkeypatch):
    """Empty live ingest must not invent demo_sim points (auto-scorer / Refresh live)."""
    from app.models import MatchEvent

    db = SessionLocal()
    try:
        gw = squad_svc.current_gameweek(db)
        # Prior tests may have left demo_sim rows — clear so this asserts the auto path.
        live_svc.clear_demo_scoring_data(db, gameweek_id=gw.id)

        def _empty_live(_db, _gw):
            return {"source": "fpl_live", "players_updated": 0, "club_results": 0, "live_empty": True}

        monkeypatch.setattr(live_svc, "ingest_fpl_live", _empty_live)
        before = (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.source == "demo_sim")
            .count()
        )
        summary = live_svc.run_gameweek_scoring(db, prefer_live=True, force_demo=False)
        assert summary["ingest"].get("demo_skipped") is True
        assert summary["ingest"].get("fell_back_demo") is None
        assert summary["ingest"].get("source") != "demo_sim"
        after = (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.source == "demo_sim")
            .count()
        )
        assert before == 0
        assert after == 0
    finally:
        db.close()


def test_clear_demo_scoring_data_removes_fake_points():
    from app.models import ManagerGameweekScore, MatchEvent

    db = SessionLocal()
    try:
        gw = squad_svc.current_gameweek(db)
        live_svc.simulate_demo_metrics(db, gw)
        live_svc.score_players(db, gw)
        live_svc.score_managers(db, gw)
        assert (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.source == "demo_sim")
            .count()
            > 0
        )
        assert live_svc.is_demo_scoring_active(db, gw) is True

        cleared = live_svc.clear_demo_scoring_data(db, gameweek_id=gw.id)
        assert cleared["match_events_deleted"] > 0
        assert (
            db.query(MatchEvent)
            .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.source == "demo_sim")
            .count()
            == 0
        )
        assert (
            db.query(ManagerGameweekScore)
            .filter(ManagerGameweekScore.gameweek_id == gw.id)
            .count()
            == 0
        )
        assert live_svc.is_demo_scoring_active(db, gw) is False
    finally:
        db.close()


def test_super_sub_doubles_bench_player_who_played():
    import json
    from datetime import datetime, timedelta, timezone

    from app.models import ChipPlay, ManagerGameweekScore
    from app.services import chips as chips_svc

    db = SessionLocal()
    try:
        manager = Manager(display_name="SSScore", pin="5555", team_name="Double FC")
        db.add(manager)
        db.commit()
        db.refresh(manager)

        by_pos: dict[str, list[Player]] = {}
        for p in db.query(Player).order_by(Player.price).all():
            by_pos.setdefault(p.position, []).append(p)
        need = {"GK": 2, "DEF": 5, "MID": 5, "ATT": 3}
        squad: list[Player] = []
        club_counts: dict[str, int] = {}
        for pos, n in need.items():
            for p in by_pos.get(pos, []):
                if club_counts.get(p.team_code, 0) >= 3:
                    continue
                squad.append(p)
                club_counts[p.team_code] = club_counts.get(p.team_code, 0) + 1
                if sum(1 for x in squad if x.position == pos) >= n:
                    break
        assert len(squad) == 15
        ids = [p.id for p in squad]
        gw = squad_svc.current_gameweek(db)
        gw.deadline_at = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat().replace("+00:00", "Z")
        db.commit()
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=ids, gw_number=gw.number)
        owned = squad_svc.owned_players(db, manager.id)
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(owned)
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starters,
            captain_id=captain,
            vice_id=vice,
        )
        bench_id = next(i for i in ids if i not in starters)
        chips_svc.ensure_chip_state(db, manager.id)
        chips_svc.play_chip(
            db, manager_id=manager.id, gameweek_id=gw.id, chip="super_sub", player_id=bench_id
        )

        # Deterministic minutes so SS always "plays" (no demo RNG blanks)
        for pid in ids:
            live_svc._write_metrics(
                db,
                gameweek_id=gw.id,
                player_id=pid,
                metrics={
                    "minutes": 90.0,
                    "goals": 0.0,
                    "assists": 0.0,
                    "clean_sheets": 0.0,
                    "goals_conceded": 1.0,
                    "saves": 0.0,
                    "yellow_cards": 0.0,
                    "red_cards": 0.0,
                    "own_goals": 0.0,
                    "penalties_saved": 0.0,
                    "penalties_missed": 0.0,
                },
                source="test_ss",
            )
        db.commit()
        live_svc.score_players(db, gw)
        live_svc.score_managers(db, gw)

        row = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager.id,
                ManagerGameweekScore.gameweek_id == gw.id,
            )
            .one()
        )
        breakdown = json.loads(row.breakdown_json or "{}")
        assert breakdown.get("chip") == "super_sub"
        lines = breakdown.get("players") or []
        ss = [L for L in lines if L.get("player_id") == bench_id]
        assert ss, "super sub player should appear in score lines when they play"
        assert float(ss[0].get("mult") or 1) == 2.0
        assert ss[0].get("super_sub") is True
        assert (
            db.query(ChipPlay)
            .filter(ChipPlay.manager_id == manager.id, ChipPlay.chip == "super_sub")
            .count()
            == 1
        )
    finally:
        db.close()
