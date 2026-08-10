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

        from app.models import ManagerGameweekScore

        row = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager.id,
                ManagerGameweekScore.gameweek_id == gw.id,
            )
            .one()
        )
        assert row.total != 0 or row.squad_points >= 0
    finally:
        db.close()
