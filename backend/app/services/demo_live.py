"""Helpers to exercise the phone app as if a gameweek is already live.

Stores the real deadline so testing can be reverted without wiping the DB.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Fixture, Gameweek, League, Manager, Membership, Player, SquadPick
from app.services import live_scoring as live_svc
from app.services import squad as squad_svc


def _encode_backup(gw: Gameweek, payload: dict[str, Any]) -> None:
    base = (gw.name or f"Gameweek {gw.number}").split("\x1e", 1)[0]
    gw.name = f"{base}\x1eDEMO_LIVE:{json.dumps(payload)}"


def _decode_backup(gw: Gameweek) -> dict[str, Any] | None:
    raw = gw.name or ""
    if "\x1eDEMO_LIVE:" not in raw:
        return None
    try:
        return json.loads(raw.split("\x1eDEMO_LIVE:", 1)[1])
    except Exception:
        return None


def _clear_backup(gw: Gameweek) -> None:
    raw = gw.name or ""
    gw.name = raw.split("\x1e", 1)[0] or f"Gameweek {gw.number}"


def is_live_demo_active(db: Session) -> bool:
    gw = squad_svc.current_gameweek(db)
    return _decode_backup(gw) is not None


def _pick_affordable_squad(db: Session) -> list[int]:
    """Build a legal 15 under budget from the catalogue."""
    need = dict(squad_svc.REQUIRED)
    selected: list[Player] = []
    club_n: Counter[str] = Counter()
    spend = 0.0

    by_pos: dict[str, list[Player]] = {"GK": [], "DEF": [], "MID": [], "ATT": []}
    for p in db.query(Player).order_by(Player.price.desc(), Player.name).all():
        if p.position in by_pos:
            by_pos[p.position].append(p)

    for pos, count in need.items():
        pool = by_pos[pos]
        mid = pool[len(pool) // 5 :] if len(pool) > 10 else pool
        for p in mid + pool:
            if sum(1 for s in selected if s.position == pos) >= count:
                break
            if any(s.id == p.id for s in selected):
                continue
            if club_n[p.team_code] >= settings.max_per_club:
                continue
            if spend + p.price > settings.budget + 1e-6:
                continue
            selected.append(p)
            club_n[p.team_code] += 1
            spend += p.price

    if len(selected) != settings.squad_size:
        selected = []
        club_n = Counter()
        spend = 0.0
        for pos, count in need.items():
            for p in sorted(by_pos[pos], key=lambda x: (x.price, x.name)):
                if sum(1 for s in selected if s.position == pos) >= count:
                    break
                if club_n[p.team_code] >= settings.max_per_club:
                    continue
                if spend + p.price > settings.budget + 1e-6:
                    continue
                selected.append(p)
                club_n[p.team_code] += 1
                spend += p.price

    if len(selected) != settings.squad_size:
        raise squad_svc.SquadError("Could not auto-build a demo squad from the player list")
    squad_svc.validate_composition(selected)
    return [p.id for p in selected]


def ensure_manager_squad_and_xi(db: Session, manager: Manager) -> dict[str, Any]:
    """If the manager has no 15 / XI, auto-fill so live demo screens are usable."""
    gw = squad_svc.current_gameweek(db)
    owned = squad_svc.owned_players(db, manager.id)
    created_squad = False
    if len(owned) != settings.squad_size:
        ids = _pick_affordable_squad(db)
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=ids, gw_number=gw.number)
        owned = squad_svc.owned_players(db, manager.id)
        created_squad = True

    memberships = db.query(Membership).filter(Membership.manager_id == manager.id).count()
    joined_league = False
    if memberships == 0:
        league = db.query(League).filter(League.invite_code == "FORGE1").one_or_none()
        if league:
            db.add(Membership(league_id=league.id, manager_id=manager.id))
            db.commit()
            joined_league = True

    existing = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == manager.id, SquadPick.gameweek_id == gw.id)
        .count()
    )
    created_xi = False
    if existing < settings.squad_size:
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(owned)
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starters,
            captain_id=captain,
            vice_id=vice,
        )
        created_xi = True

    if not manager.team_name:
        manager.team_name = f"{manager.display_name}'s XI"
        db.commit()

    return {
        "created_squad": created_squad,
        "created_xi": created_xi,
        "joined_league": joined_league,
        "owned": len(owned),
    }


def _mark_fixtures_live(db: Session, gw_number: int) -> int:
    rows = db.query(Fixture).filter(Fixture.gameweek_number == gw_number).all()
    for i, fx in enumerate(rows):
        if i % 3 == 0:
            fx.started = 1
            fx.finished = 1
            fx.home_score = 1 + (i % 3)
            fx.away_score = i % 2
        elif i % 3 == 1:
            fx.started = 1
            fx.finished = 0
            fx.home_score = i % 2
            fx.away_score = 0
        else:
            fx.started = 0
            fx.finished = 0
            fx.home_score = None
            fx.away_score = None
    db.commit()
    return len(rows)


def start_live_demo(db: Session, manager: Manager) -> dict[str, Any]:
    """Lock the current GW as if deadline passed, fill squad if needed, invent live scores."""
    gw = squad_svc.current_gameweek(db)
    if _decode_backup(gw):
        ready = ensure_manager_squad_and_xi(db, manager)
        scoring = live_svc.run_gameweek_scoring(db, prefer_live=False, force_demo=True)
        return {"already_active": True, "ready": ready, "scoring": scoring, "gameweek": gw.number}

    backup = {
        "deadline_at": gw.deadline_at,
        "status": gw.status,
        "fixture_snapshot": [
            {
                "id": fx.id,
                "started": fx.started,
                "finished": fx.finished,
                "home_score": fx.home_score,
                "away_score": fx.away_score,
            }
            for fx in db.query(Fixture).filter(Fixture.gameweek_number == gw.number).all()
        ],
    }
    _encode_backup(gw, backup)

    past = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    gw.deadline_at = past
    gw.status = "live"
    db.commit()

    ready = ensure_manager_squad_and_xi(db, manager)
    fixtures = _mark_fixtures_live(db, gw.number)
    scoring = live_svc.run_gameweek_scoring(db, prefer_live=False, force_demo=True)
    return {
        "already_active": False,
        "ready": ready,
        "fixtures_updated": fixtures,
        "scoring": scoring,
        "gameweek": gw.number,
    }


def stop_live_demo(db: Session) -> dict[str, Any]:
    """Restore deadline + fixture state from before start_live_demo."""
    gw = squad_svc.current_gameweek(db)
    backup = _decode_backup(gw)
    if not backup:
        return {"restored": False, "reason": "no_demo_active"}

    gw.deadline_at = backup.get("deadline_at")
    gw.status = backup.get("status") or "upcoming"
    snap = {row["id"]: row for row in backup.get("fixture_snapshot") or []}
    for fx in db.query(Fixture).filter(Fixture.gameweek_number == gw.number).all():
        row = snap.get(fx.id)
        if not row:
            continue
        fx.started = row.get("started") or 0
        fx.finished = row.get("finished") or 0
        fx.home_score = row.get("home_score")
        fx.away_score = row.get("away_score")
    _clear_backup(gw)
    db.commit()
    return {"restored": True, "gameweek": gw.number, "deadline_at": gw.deadline_at}
