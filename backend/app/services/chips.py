"""Chip plays — WC, FH, TC, BB, Super Sub (cancel before deadline)."""

from __future__ import annotations

import json
from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import ChipPlay, ChipState, Gameweek, OwnedPlayer, SquadPick
from app.services.deadline import can_edit


class ChipError(ValueError):
    pass


CHIP_LABELS = {
    "wildcard": "Wildcard",
    "triple_captain": "Triple Captain",
    "bench_boost": "Bench Boost",
    "free_hit": "Free Hit",
    "super_sub": "Super Sub",
}

CHIP_SHORT = {
    "wildcard": "WC",
    "triple_captain": "TC",
    "bench_boost": "BB",
    "free_hit": "FH",
    "super_sub": "SS",
}

PLAYABLE = {"wildcard", "triple_captain", "bench_boost", "free_hit", "super_sub"}


def ensure_chip_state(db: Session, manager_id: int) -> ChipState:
    state = db.query(ChipState).filter(ChipState.manager_id == manager_id).one_or_none()
    if state:
        return state
    state = ChipState(manager_id=manager_id)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def active_chip(db: Session, manager_id: int, gameweek_id: int) -> ChipPlay | None:
    return (
        db.query(ChipPlay)
        .filter(ChipPlay.manager_id == manager_id, ChipPlay.gameweek_id == gameweek_id)
        .one_or_none()
    )


def _require_open(gw: Gameweek) -> None:
    if not can_edit(gw):
        raise ChipError("Deadline passed — chips are locked for this GW")


def _owned_ids(db: Session, manager_id: int) -> list[int]:
    rows = db.query(OwnedPlayer).filter(OwnedPlayer.manager_id == manager_id).all()
    return [r.player_id for r in rows]


def restore_ownership_from_ids(
    db: Session,
    *,
    manager_id: int,
    player_ids: list[int],
    acquired_gw: int,
) -> None:
    """Replace current ownership with a saved Free Hit snapshot."""
    from app.models import Player
    from app.services import squad as squad_svc

    if len(set(player_ids)) != len(player_ids):
        raise ChipError("Corrupt Free Hit snapshot")
    found = db.query(Player).filter(Player.id.in_(player_ids)).all()
    if len(found) != len(player_ids):
        raise ChipError("Free Hit snapshot players missing from catalogue")
    by_id = {p.id: p for p in found}
    ordered = [by_id[i] for i in player_ids]
    squad_svc.validate_composition(ordered)

    db.query(OwnedPlayer).filter(OwnedPlayer.manager_id == manager_id).delete()
    for pid in player_ids:
        db.add(OwnedPlayer(manager_id=manager_id, player_id=pid, acquired_gw=acquired_gw))


def _rebuild_lineup_for_gw(db: Session, *, manager_id: int, gameweek_id: int) -> None:
    from app.services import squad as squad_svc

    owned = squad_svc.owned_players(db, manager_id)
    if len(owned) != settings.squad_size:
        return
    starters, _, captain, vice = squad_svc.default_lineup_from_owned(owned)
    squad_svc.save_lineup(
        db,
        manager_id=manager_id,
        gameweek_id=gameweek_id,
        starter_ids=starters,
        captain_id=captain,
        vice_id=vice,
    )


def play_chip(
    db: Session,
    *,
    manager_id: int,
    gameweek_id: int,
    chip: str,
    player_id: Optional[int] = None,
) -> ChipPlay:
    chip = (chip or "").strip().lower()
    if chip not in PLAYABLE:
        raise ChipError("That chip isn’t available yet")

    gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).one()
    _require_open(gw)
    state = ensure_chip_state(db, manager_id)

    already = active_chip(db, manager_id, gameweek_id)
    if already:
        raise ChipError(f"Already playing {CHIP_LABELS.get(already.chip, already.chip)} this GW")

    meta: dict = {}

    if chip == "wildcard":
        unlocked = 1 if gw.number < 20 else 2
        used = (
            db.query(ChipPlay)
            .filter(ChipPlay.manager_id == manager_id, ChipPlay.chip == "wildcard")
            .count()
        )
        if used >= unlocked or state.wildcard_remaining <= 0:
            raise ChipError("No Wildcard left (2nd unlocks from GW20)")
        state.wildcard_remaining = max(0, state.wildcard_remaining - 1)
    elif chip == "triple_captain":
        if state.triple_captain_remaining <= 0:
            raise ChipError("No Triple Captain left")
        state.triple_captain_remaining = max(0, state.triple_captain_remaining - 1)
    elif chip == "bench_boost":
        if state.bench_boost_remaining <= 0:
            raise ChipError("No Bench Boost left")
        state.bench_boost_remaining = max(0, state.bench_boost_remaining - 1)
    elif chip == "free_hit":
        if state.free_hit_remaining <= 0:
            raise ChipError("No Free Hit left")
        owned_ids = _owned_ids(db, manager_id)
        if len(owned_ids) != settings.squad_size:
            raise ChipError("Save a full 15 before playing Free Hit")
        state.free_hit_remaining = max(0, state.free_hit_remaining - 1)
        meta = {"snapshot": owned_ids, "restored": False, "gw_number": gw.number}
    elif chip == "super_sub":
        if state.super_sub_remaining <= 0:
            raise ChipError("No Super Sub left")
        if not player_id:
            raise ChipError("Pick a bench player for Super Sub")
        owned_ids = set(_owned_ids(db, manager_id))
        if player_id not in owned_ids:
            raise ChipError("Super Sub must be in your squad")
        picks = (
            db.query(SquadPick)
            .filter(SquadPick.manager_id == manager_id, SquadPick.gameweek_id == gameweek_id)
            .all()
        )
        if not picks:
            raise ChipError("Set your lineup before playing Super Sub")
        starters = {p.player_id for p in picks if p.is_starter}
        if player_id in starters:
            raise ChipError("Super Sub must be a bench player (not in the XI)")
        if any(p.player_id == player_id and (p.is_captain or getattr(p, "is_vice_captain", 0)) for p in picks):
            raise ChipError("Super Sub can’t be captain or vice")
        state.super_sub_remaining = max(0, state.super_sub_remaining - 1)
        meta = {"player_id": int(player_id)}

    play = ChipPlay(
        manager_id=manager_id,
        gameweek_id=gameweek_id,
        chip=chip,
        meta_json=json.dumps(meta),
    )
    db.add(play)
    db.commit()
    db.refresh(play)
    return play


def cancel_chip(db: Session, *, manager_id: int, gameweek_id: int) -> None:
    """Cancel active chip before deadline and restore remaining count."""
    gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).one()
    _require_open(gw)
    play = active_chip(db, manager_id, gameweek_id)
    if not play:
        raise ChipError("No chip to cancel")

    state = ensure_chip_state(db, manager_id)
    if play.chip == "wildcard":
        state.wildcard_remaining += 1
    elif play.chip == "triple_captain":
        state.triple_captain_remaining += 1
    elif play.chip == "bench_boost":
        state.bench_boost_remaining += 1
    elif play.chip == "free_hit":
        state.free_hit_remaining += 1
        meta = {}
        try:
            meta = json.loads(play.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        snapshot = meta.get("snapshot") or []
        if snapshot:
            restore_ownership_from_ids(
                db,
                manager_id=manager_id,
                player_ids=[int(x) for x in snapshot],
                acquired_gw=gw.number,
            )
            db.flush()
            _rebuild_lineup_for_gw(db, manager_id=manager_id, gameweek_id=gameweek_id)
    elif play.chip == "super_sub":
        state.super_sub_remaining += 1

    db.delete(play)
    db.commit()


def restore_free_hits_if_needed(db: Session, *, manager_id: int, current_gw: Gameweek) -> int:
    """After a Free Hit GW ends, put the original 15 back (FPL-style)."""
    plays = (
        db.query(ChipPlay)
        .filter(ChipPlay.manager_id == manager_id, ChipPlay.chip == "free_hit")
        .all()
    )
    restored_n = 0
    for play in plays:
        try:
            meta = json.loads(play.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if meta.get("restored"):
            continue
        play_gw = db.query(Gameweek).filter(Gameweek.id == play.gameweek_id).one_or_none()
        if not play_gw or play_gw.number >= current_gw.number:
            continue
        snapshot = meta.get("snapshot") or []
        if not snapshot:
            meta["restored"] = True
            play.meta_json = json.dumps(meta)
            continue
        restore_ownership_from_ids(
            db,
            manager_id=manager_id,
            player_ids=[int(x) for x in snapshot],
            acquired_gw=current_gw.number,
        )
        meta["restored"] = True
        play.meta_json = json.dumps(meta)
        # Clear any current-GW picks built from the temp FH squad, then default
        db.query(SquadPick).filter(
            SquadPick.manager_id == manager_id,
            SquadPick.gameweek_id == current_gw.id,
        ).delete()
        db.flush()
        _rebuild_lineup_for_gw(db, manager_id=manager_id, gameweek_id=current_gw.id)
        restored_n += 1
    if restored_n:
        db.commit()
    return restored_n


# Back-compat
def play_wildcard(db: Session, *, manager_id: int, gameweek_id: int) -> ChipPlay:
    return play_chip(db, manager_id=manager_id, gameweek_id=gameweek_id, chip="wildcard")
