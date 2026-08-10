"""Chip plays — Wildcard, Triple Captain, Bench Boost (cancel before deadline)."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import ChipPlay, ChipState, Gameweek
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


def play_chip(db: Session, *, manager_id: int, gameweek_id: int, chip: str) -> ChipPlay:
    chip = (chip or "").strip().lower()
    if chip not in {"wildcard", "triple_captain", "bench_boost"}:
        raise ChipError("That chip isn’t available yet")

    gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).one()
    _require_open(gw)
    state = ensure_chip_state(db, manager_id)

    already = active_chip(db, manager_id, gameweek_id)
    if already:
        raise ChipError(f"Already playing {CHIP_LABELS.get(already.chip, already.chip)} this GW")

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

    play = ChipPlay(
        manager_id=manager_id,
        gameweek_id=gameweek_id,
        chip=chip,
        meta_json=json.dumps({}),
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

    db.delete(play)
    db.commit()


# Back-compat
def play_wildcard(db: Session, *, manager_id: int, gameweek_id: int) -> ChipPlay:
    return play_chip(db, manager_id=manager_id, gameweek_id=gameweek_id, chip="wildcard")
