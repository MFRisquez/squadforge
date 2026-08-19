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
        assert payload["locked"] is True
        assert payload["leagues"] == []
        assert payload["my_transfers"] == []
    finally:
        db.close()


def test_manager_gw_transfer_rows_listed():
    db, league, managers, gw = _league_with_scores(4, tag="mine")
    try:
        from app.models import Player

        players = db.query(Player).limit(2).all()
        assert len(players) >= 2
        p_out, p_in = players[0], players[1]
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
        db.commit()
        rows = desk_side_svc.manager_gw_transfer_rows(
            db, manager_id=managers[0].id, gameweek_id=gw.id
        )
        assert len(rows) == 1
        assert rows[0]["out"] == p_out.name
        assert rows[0]["in"] == p_in.name
        payload = desk_side_svc.transfers_side_left_payload(
            db, leagues=[league], gw=gw, manager_id=managers[0].id
        )
        assert payload["my_transfers"][0]["out_id"] == p_out.id
    finally:
        db.close()
