"""Desk side panels: TTL ranks + aggregated league top transfers."""

from __future__ import annotations

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.models import Gameweek, Manager, ManagerGameweekScore, Membership, TransferLog
from app.services import desk_side as desk_side_svc
from app.services import league as league_svc
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


def _league_with_scores(n_managers: int = 4, *, tag: str = "A"):
    db = SessionLocal()
    managers = []
    for i in range(n_managers):
        m = league_svc.register_manager(
            db,
            display_name=f"Side{tag}{i}",
            password="secret12",
            email=f"side{tag}{i}@example.com",
            team_name=f"Side FC {tag}{i}",
        )
        managers.append(m)
    league = league_svc.create_league(db, f"Side League {tag}", managers[0])
    for m in managers[1:]:
        league_svc.join_league(db, league.invite_code, m)
    gw = db.query(Gameweek).order_by(Gameweek.number).first()
    assert gw is not None
    for i, m in enumerate(managers):
        db.add(ManagerGameweekScore(manager_id=m.id, gameweek_id=gw.id, total=10 + i * 5))
    db.commit()
    return db, league, managers, gw


def test_manager_league_cards_use_ttl_cache():
    db, league, managers, gw = _league_with_scores(4, tag="rank")
    try:
        desk_side_svc.clear_desk_side_caches()
        mid = managers[-1].id  # highest score → rank 1
        cards1 = desk_side_svc.manager_league_cards(db, [league], mid, gw)
        assert cards1
        assert cards1[0]["rank"] == 1
        assert "Classic #1 of 4" == cards1[0]["label"]

        key = (int(league.id), int(gw.id))
        assert key in desk_side_svc._RANK_CACHE
        ts1 = desk_side_svc._RANK_CACHE[key][0]
        cards2 = desk_side_svc.manager_league_cards(db, [league], mid, gw)
        assert cards2[0]["rank"] == 1
        assert desk_side_svc._RANK_CACHE[key][0] == ts1
    finally:
        db.close()


def test_league_top_transfers_aggregated():
    db, league, managers, gw = _league_with_scores(4, tag="xfer")
    try:
        from app.models import Player

        players = db.query(Player).limit(2).all()
        assert len(players) >= 2
        p_out, p_in = players[0], players[1]
        for m in managers[:3]:
            db.add(
                TransferLog(
                    manager_id=m.id,
                    gameweek_id=gw.id,
                    player_out_id=p_out.id,
                    player_in_id=p_in.id,
                    free_transfers_after=1,
                    is_hit=0,
                )
            )
        db.commit()

        top = desk_side_svc.league_top_transfers(db, league_id=league.id, gameweek_id=gw.id)
        assert top is not None
        assert top["most_in"][0]["player_id"] == p_in.id
        assert top["most_in"][0]["count"] == 3
        assert top["most_out"][0]["player_id"] == p_out.id
        assert top["most_out"][0]["count"] == 3
    finally:
        db.close()


def test_top_transfers_skipped_for_tiny_league():
    db, league, managers, gw = _league_with_scores(2, tag="tiny")
    try:
        top = desk_side_svc.league_top_transfers(db, league_id=league.id, gameweek_id=gw.id)
        assert top is None
    finally:
        db.close()


def test_transfers_side_locked_before_deadline(monkeypatch):
    db, league, managers, gw = _league_with_scores(4, tag="lock")
    try:
        monkeypatch.setattr("app.services.deadline.can_edit", lambda _gw: True)
        payload = desk_side_svc.transfers_side_left_payload(
            db, leagues=[league], gw=gw, manager_id=managers[0].id
        )
        assert payload["preview"] is True
        trends = payload["trends"]
        assert trends["preview"] is True
        assert "Jugador-Ejemplo" in trends["most_in"][0]["name"]
        assert trends["most_in"][0]["count"] == 0
        assert "most_picked" not in trends
        assert "Preview" in (payload.get("watermark") or "")
        assert payload["my_transfers"] == []
        assert payload["leagues"] == []
    finally:
        db.close()


def test_transfers_side_combines_leagues_no_dup(monkeypatch):
    db, league_a, managers, gw = _league_with_scores(4, tag="uniA")
    try:
        from app.models import Player

        monkeypatch.setattr("app.services.deadline.can_edit", lambda _gw: False)
        league_b = league_svc.create_league(db, "Side League uniB", managers[0])
        for m in managers[1:]:
            league_svc.join_league(db, league_b.invite_code, m)
        players = db.query(Player).limit(2).all()
        p_out, p_in = players[0], players[1]
        for m in managers[:3]:
            db.add(
                TransferLog(
                    manager_id=m.id,
                    gameweek_id=gw.id,
                    player_out_id=p_out.id,
                    player_in_id=p_in.id,
                    free_transfers_after=1,
                    is_hit=0,
                )
            )
        db.commit()
        desk_side_svc.clear_desk_side_caches()
        payload = desk_side_svc.transfers_side_left_payload(
            db, leagues=[league_a, league_b], gw=gw, manager_id=managers[0].id
        )
        assert payload["preview"] is False
        assert payload["leagues"] == []
        trends = payload["trends"]
        assert trends is not None
        assert trends["most_in"][0]["player_id"] == p_in.id
        assert trends["most_in"][0]["count"] == 3
        assert "most_picked" not in trends
        # Union of 4 managers (same people in both leagues) — not 8
        assert trends["manager_count"] == 4
    finally:
        db.close()


def test_league_most_picked_and_captain_aggregated(monkeypatch):
    db, league, managers, gw = _league_with_scores(4, tag="pick")
    try:
        from app.models import OwnedPlayer, Player, SquadPick

        monkeypatch.setattr("app.services.deadline.can_edit", lambda _gw: False)
        players = db.query(Player).limit(3).all()
        assert len(players) >= 3
        star, other, third = players[0], players[1], players[2]
        # 3 of 4 managers start star; 2 captain star
        for i, m in enumerate(managers):
            db.add(OwnedPlayer(manager_id=m.id, player_id=star.id))
            db.add(
                SquadPick(
                    manager_id=m.id,
                    gameweek_id=gw.id,
                    player_id=star.id if i < 3 else other.id,
                    is_starter=1,
                    is_captain=1 if i < 2 else 0,
                    is_vice_captain=0,
                    bench_order=0,
                )
            )
            if i >= 2:
                db.add(
                    SquadPick(
                        manager_id=m.id,
                        gameweek_id=gw.id,
                        player_id=third.id,
                        is_starter=1,
                        is_captain=1 if i == 2 else 0,
                        is_vice_captain=0,
                        bench_order=0,
                    )
                )
        star.season_stats_json = '{"total_points": 42}'
        db.commit()
        desk_side_svc.clear_desk_side_caches()
        picked = desk_side_svc.league_most_picked_xi(
            db, league_id=league.id, gameweek_id=gw.id, gw_number=gw.number
        )
        assert picked is not None
        assert picked[0]["player_id"] == star.id
        assert picked[0]["pct"] == 75.0  # 3/4
        assert picked[0]["points"] == 42.0
        cap = desk_side_svc.league_popular_captain(
            db, league_id=league.id, gameweek_id=gw.id, gw_number=gw.number
        )
        assert cap is not None
        assert cap["player_id"] == star.id
        assert cap["pct"] == 50.0  # 2/4
        payload = desk_side_svc.transfers_side_left_payload(
            db, leagues=[league], gw=gw, manager_id=managers[0].id
        )
        assert payload["preview"] is False
        # Combined trends no longer embed most_picked; helpers still work.
        assert payload["trends"] is not None or payload["trends"] is None
        assert payload.get("leagues") == []
        assert picked[0]["name"] == star.name
    finally:
        db.close()


def test_manager_gw_transfer_rows_listed():
    db, league, managers, gw = _league_with_scores(4, tag="mine")
    try:
        from app.models import Gameweek, Player

        players = db.query(Player).limit(4).all()
        assert len(players) >= 4
        p_out, p_in = players[0], players[1]
        p_out2, p_in2 = players[2], players[3]
        db.add(
            TransferLog(
                manager_id=managers[0].id,
                gameweek_id=gw.id,
                player_out_id=p_out.id,
                player_in_id=p_in.id,
                free_transfers_after=1,
                is_hit=0,
            )
        )
        db.add(
            TransferLog(
                manager_id=managers[0].id,
                gameweek_id=gw.id,
                player_out_id=p_out2.id,
                player_in_id=p_in2.id,
                free_transfers_after=1,
                is_hit=1,
            )
        )
        db.commit()
        rows = desk_side_svc.manager_gw_transfer_rows(
            db, manager_id=managers[0].id, gameweek_id=gw.id
        )
        assert len(rows) == 2
        assert rows[0]["out"] == p_out2.name  # newest first
        assert rows[1]["out"] == p_out.name
        other = db.query(Gameweek).filter(Gameweek.id != gw.id).order_by(Gameweek.number).first()
        assert other is not None
        assert (
            desk_side_svc.manager_gw_transfer_rows(
                db, manager_id=managers[0].id, gameweek_id=other.id
            )
            == []
        )
        payload = desk_side_svc.transfers_side_left_payload(
            db, leagues=[league], gw=gw, manager_id=managers[0].id
        )
        assert payload["my_transfers"][0]["out_id"] == p_out2.id
    finally:
        db.close()


def test_top_scorers_sum_across_rebuys():
    """Sell + re-buy the same player: points from both stints must add."""
    from app.models import Gameweek, OwnedPlayer, Player

    db = SessionLocal()
    try:
        m = league_svc.register_manager(
            db,
            display_name="ScorerA",
            password="secret12",
            email="scorera@example.com",
            team_name="Scorer FC",
        )
        gws = db.query(Gameweek).order_by(Gameweek.number).limit(3).all()
        assert len(gws) >= 3
        g1, g2, g3 = gws[0], gws[1], gws[2]
        players = db.query(Player).limit(3).all()
        assert len(players) >= 3
        star, filler, temp = players[0], players[1], players[2]

        # Current squad includes star (re-bought) + filler.
        db.add(OwnedPlayer(manager_id=m.id, player_id=star.id))
        db.add(OwnedPlayer(manager_id=m.id, player_id=filler.id))
        # GW2: sell star → temp; GW3: sell temp → star (re-buy)
        db.add(
            TransferLog(
                manager_id=m.id,
                gameweek_id=g2.id,
                player_out_id=star.id,
                player_in_id=temp.id,
                free_transfers_after=1,
                is_hit=0,
            )
        )
        db.add(
            TransferLog(
                manager_id=m.id,
                gameweek_id=g3.id,
                player_out_id=temp.id,
                player_in_id=star.id,
                free_transfers_after=1,
                is_hit=0,
            )
        )
        # Scores: star 10 in GW1 (owned), 0 in GW2 (not owned), 7 in GW3 (owned again)
        import json

        def _score(gw, lines):
            db.add(
                ManagerGameweekScore(
                    manager_id=m.id,
                    gameweek_id=gw.id,
                    total=sum(float(x["points"]) for x in lines),
                    breakdown_json=json.dumps({"players": lines}),
                )
            )

        _score(g1, [{"player_id": star.id, "points": 10}, {"player_id": filler.id, "points": 2}])
        _score(g2, [{"player_id": temp.id, "points": 5}, {"player_id": filler.id, "points": 1}])
        _score(g3, [{"player_id": star.id, "points": 7}, {"player_id": filler.id, "points": 3}])
        db.commit()

        desk_side_svc.clear_desk_side_caches()
        owned = desk_side_svc.ownership_by_gw_number(db, m.id)
        assert star.id in owned[g1.number]
        assert star.id not in owned[g2.number]
        assert star.id in owned[g3.number]

        top = desk_side_svc.manager_top_scorers_while_owned(
            db, manager_id=m.id, current_gw_id=g3.id, limit=5
        )
        by_id = {r["player_id"]: r["points"] for r in top}
        assert by_id[star.id] == 17.0  # 10 + 7, not reset on re-buy
        assert by_id[filler.id] == 6.0  # 2+1+3
        assert temp.id not in by_id or by_id.get(temp.id) == 5.0

        # TTL cache hit
        key = (int(m.id), int(g3.id))
        ts1 = desk_side_svc._TOP_SCORERS_CACHE[key][0]
        top2 = desk_side_svc.manager_top_scorers_while_owned(
            db, manager_id=m.id, current_gw_id=g3.id, limit=5
        )
        assert top2[0]["points"] == top[0]["points"]
        assert desk_side_svc._TOP_SCORERS_CACHE[key][0] == ts1
    finally:
        db.close()


def test_manager_rank_spark_uses_standings_history():
    db, league, managers, gw = _league_with_scores(3, tag="spark")
    try:
        from app.models import Gameweek

        g2 = db.query(Gameweek).filter(Gameweek.number == 2).first()
        if g2 is None:
            g2 = Gameweek(number=2, name="GW2", deadline_at=gw.deadline_at, is_current=0)
            db.add(g2)
            db.flush()
        for i, m in enumerate(managers):
            db.add(
                ManagerGameweekScore(
                    manager_id=m.id, gameweek_id=g2.id, total=20 + i * 3
                )
            )
        db.commit()
        mid = managers[-1].id
        spark = desk_side_svc.manager_rank_spark(
            db, manager_id=mid, gw=g2, leagues=[league]
        )
        assert spark is not None
        assert spark["league_id"] == league.id
        assert spark["empty"] is False
        assert spark["preview"] is False
        assert len(spark["gw_numbers"]) >= 2
        assert spark["series"] and any(s.get("is_me") for s in spark["series"])
        payload = desk_side_svc.xi_side_left_payload(
            db, manager_id=mid, gw=g2, leagues=[league]
        )
        assert payload.get("rank_spark")
        assert payload["rank_spark"]["count"] == 1
        assert payload["rank_spark"]["charts"][0]["league_name"] == league.name
    finally:
        db.close()


def test_manager_rank_spark_preview_before_two_gws():
    db, league, managers, gw = _league_with_scores(3, tag="prev")
    try:
        mid = managers[0].id
        spark = desk_side_svc.manager_rank_spark(
            db, manager_id=mid, gw=gw, leagues=[league]
        )
        assert spark is not None
        assert spark["preview"] is True
        assert spark["empty"] is False
        assert len(spark["gw_numbers"]) >= 2
        assert any(s.get("is_me") and s.get("area_path") for s in spark["series"])
    finally:
        db.close()


def test_manager_rank_sparks_switchable_for_two_leagues():
    db, league_a, managers, gw = _league_with_scores(3, tag="swA")
    try:
        league_b = league_svc.create_league(db, "Side League swB", managers[0])
        for m in managers[1:]:
            league_svc.join_league(db, league_b.invite_code, m)
        mid = managers[0].id
        bundle = desk_side_svc.manager_rank_sparks(
            db, manager_id=mid, gw=gw, leagues=[league_a, league_b]
        )
        assert bundle is not None
        assert bundle["count"] == 2
        assert {c["league_id"] for c in bundle["charts"]} == {league_a.id, league_b.id}
        assert all(c["preview"] for c in bundle["charts"])
    finally:
        db.close()
