"""Technical Director pick logic.

TD is NOT a chip (Wildcard stays separate).
You may start a TD assignment anytime you don't already have one active.
Once set, that club scores for exactly 3 consecutive gameweeks, then you can pick again.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Club, ClubResult, TechnicalDirectorPick

TD_POINTS = {"W": 3.0, "D": 1.0, "L": -1.0}


class TDError(ValueError):
    pass


def window_for_start(start_gw: int) -> tuple[int, int]:
    end = min(38, start_gw + settings.td_block_length - 1)
    return start_gw, end


def active_td(db: Session, manager_id: int, gw_number: int) -> Optional[TechnicalDirectorPick]:
    return (
        db.query(TechnicalDirectorPick)
        .filter(
            TechnicalDirectorPick.manager_id == manager_id,
            TechnicalDirectorPick.start_gw <= gw_number,
            TechnicalDirectorPick.end_gw >= gw_number,
        )
        .one_or_none()
    )


def latest_td(db: Session, manager_id: int) -> Optional[TechnicalDirectorPick]:
    return (
        db.query(TechnicalDirectorPick)
        .filter(TechnicalDirectorPick.manager_id == manager_id)
        .order_by(TechnicalDirectorPick.end_gw.desc())
        .first()
    )


def can_select_td(db: Session, manager_id: int, gw_number: int) -> bool:
    """Anytime — as long as there is no active 3-GW window covering this GW."""
    return active_td(db, manager_id, gw_number) is None


def set_td_pick(db: Session, *, manager_id: int, club_code: str, gw_number: int) -> TechnicalDirectorPick:
    club = db.query(Club).filter(Club.code == club_code.upper()).one_or_none()
    if not club:
        raise TDError("Unknown club")

    current = active_td(db, manager_id, gw_number)
    if current:
        raise TDError(
            f"TD already active ({current.club_code}) until GW{current.end_gw}. "
            "Pick again after that window ends."
        )

    start, end = window_for_start(gw_number)

    prev = latest_td(db, manager_id)
    if prev and prev.club_code == club.code:
        raise TDError("Pick a different club than your last TD assignment")

    pick = TechnicalDirectorPick(
        manager_id=manager_id,
        club_code=club.code,
        start_gw=start,
        end_gw=end,
    )
    db.add(pick)
    db.commit()
    db.refresh(pick)
    return pick


def td_points_for_gw(db: Session, *, manager_id: int, gw_number: int, gameweek_id: int) -> float:
    pick = active_td(db, manager_id, gw_number)
    if not pick:
        return 0.0
    results = (
        db.query(ClubResult)
        .filter(ClubResult.gameweek_id == gameweek_id, ClubResult.club_code == pick.club_code)
        .all()
    )
    return sum(TD_POINTS.get(r.result, 0.0) for r in results)


# Back-compat aliases used by routes
def current_td(db: Session, manager_id: int, gw_number: int) -> Optional[TechnicalDirectorPick]:
    return active_td(db, manager_id, gw_number)


def block_bounds(gw_number: int) -> tuple[int, int]:
    return window_for_start(gw_number)
