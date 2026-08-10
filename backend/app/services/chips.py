"""Chip plays — Wildcard stays a separate chip from Technical Director."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models import ChipPlay, ChipState, Gameweek


class ChipError(ValueError):
    pass


def ensure_chip_state(db: Session, manager_id: int) -> ChipState:
    state = db.query(ChipState).filter(ChipState.manager_id == manager_id).one_or_none()
    if state:
        return state
    state = ChipState(manager_id=manager_id)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def play_wildcard(db: Session, *, manager_id: int, gameweek_id: int) -> ChipPlay:
    """Unlimited free transfers feel for this GW — consumed when manager chooses."""
    gw = db.query(Gameweek).filter(Gameweek.id == gameweek_id).one()
    state = ensure_chip_state(db, manager_id)

    already = (
        db.query(ChipPlay)
        .filter(ChipPlay.manager_id == manager_id, ChipPlay.gameweek_id == gameweek_id)
        .one_or_none()
    )
    if already:
        raise ChipError(f"Already playing {already.chip} this GW")

    unlocked = 1 if gw.number < 20 else 2
    used = (
        db.query(ChipPlay)
        .filter(ChipPlay.manager_id == manager_id, ChipPlay.chip == "wildcard")
        .count()
    )
    if used >= unlocked or state.wildcard_remaining <= 0:
        raise ChipError("No Wildcard left (2nd unlocks from GW20)")

    state.wildcard_remaining = max(0, state.wildcard_remaining - 1)
    play = ChipPlay(
        manager_id=manager_id,
        gameweek_id=gameweek_id,
        chip="wildcard",
        meta_json=json.dumps({}),
    )
    db.add(play)
    db.commit()
    db.refresh(play)
    return play
