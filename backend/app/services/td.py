"""Technical Director pick logic.

TD is NOT a chip (Wildcard stays separate).
You may start a TD assignment anytime you don't already have one active.
Once set, that club scores for exactly 3 consecutive gameweeks, then you can pick again.
You may change the pick until the first deadline of that window (pre-season / before kickoff).
You may not pick the same club twice in a row.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.config import settings
from app.kits import badge_url
from app.models import Club, ClubResult, TechnicalDirectorPick
from app.services import deadline as deadline_svc

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


def previous_td_club(db: Session, manager_id: int, *, exclude_id: int | None = None) -> str | None:
    """Club from the most recent finished TD window (not the active one if excluded)."""
    q = db.query(TechnicalDirectorPick).filter(TechnicalDirectorPick.manager_id == manager_id)
    if exclude_id is not None:
        q = q.filter(TechnicalDirectorPick.id != exclude_id)
    prev = q.order_by(TechnicalDirectorPick.end_gw.desc()).first()
    return prev.club_code if prev else None


def can_select_td(db: Session, manager_id: int, gw_number: int) -> bool:
    """True when manager can start a new TD window (none active)."""
    return active_td(db, manager_id, gw_number) is None


def can_change_td(db: Session, manager_id: int, gw) -> bool:
    """
    Can pick or re-pick TD.
    - No active window → can select
    - Active window starting this GW and deadline not passed → can change club
    """
    from app.models import Gameweek

    gw_number = gw.number if isinstance(gw, Gameweek) else int(gw)
    active = active_td(db, manager_id, gw_number)
    if active is None:
        return True
    if active.start_gw != gw_number:
        return False
    if isinstance(gw, Gameweek):
        return deadline_svc.can_edit(gw)
    return True


def set_td_pick(db: Session, *, manager_id: int, club_code: str, gw_number: int) -> TechnicalDirectorPick:
    from app.services import squad as squad_svc

    club = db.query(Club).filter(Club.code == club_code.upper()).one_or_none()
    if not club:
        raise TDError("Unknown club")

    gw = squad_svc.current_gameweek(db)
    # Prefer the GW being set for; use current for deadline checks
    current = active_td(db, manager_id, gw_number)
    if current:
        if current.start_gw != gw_number or not deadline_svc.can_edit(gw):
            raise TDError(
                f"TD already active ({current.club_code}) until GW{current.end_gw}. "
                "Pick again after that window ends."
            )
        banned = previous_td_club(db, manager_id, exclude_id=current.id)
        if banned and banned == club.code:
            raise TDError(f"Pick a different club than last time ({banned})")
        if current.club_code == club.code:
            return current
        db.delete(current)
        db.flush()
    else:
        banned = previous_td_club(db, manager_id)
        if banned and banned == club.code:
            raise TDError(f"Pick a different club than last time ({banned})")

    start, end = window_for_start(gw_number)
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


def td_view(db: Session, manager_id: int, gw_number: int, *, gameweek_id: int | None = None) -> dict:
    """Template/API helper for Squad/XI pitch TD corner."""
    from app.services import fixtures as fixtures_svc

    pick = active_td(db, manager_id, gw_number)
    club = None
    if pick:
        club = db.query(Club).filter(Club.code == pick.club_code).one_or_none()
    banned = previous_td_club(db, manager_id, exclude_id=pick.id if pick else None)

    fixture_line = None
    fixture_fdr = None
    if pick:
        matches = fixtures_svc.fixtures_for_gameweek(db, gw_number=gw_number)
        for m in matches:
            if m["home"]["code"] == pick.club_code:
                fixture_line = f"{m['away']['code']} (H)"
                fixture_fdr = m["home"]["difficulty"]
                break
            if m["away"]["code"] == pick.club_code:
                fixture_line = f"{m['home']['code']} (A)"
                fixture_fdr = m["away"]["difficulty"]
                break

    points = None
    if pick and gameweek_id is not None:
        points = td_points_for_gw(
            db, manager_id=manager_id, gw_number=gw_number, gameweek_id=gameweek_id
        )

    return {
        "pick": pick,
        "club_code": pick.club_code if pick else None,
        "club_name": club.name if club else (pick.club_code if pick else None),
        "badge": badge_url(club.code, kit_code=club.kit_code) if club else None,
        "start_gw": pick.start_gw if pick else None,
        "end_gw": pick.end_gw if pick else None,
        "banned_club": banned,
        "fixture_line": fixture_line,
        "fixture_fdr": fixture_fdr,
        "points": points,
    }


def td_home_banner(db: Session, manager_id: int, gw_number: int) -> dict | None:
    """Visible Home reminder when the DT window is ending or already expired."""
    active = active_td(db, manager_id, gw_number)
    if active and int(active.end_gw) == int(gw_number):
        return {
            "level": "warn",
            "club_code": active.club_code,
            "end_gw": active.end_gw,
            "message": (
                f"Your DT window ends after this GW — pick a new club "
                f"(can't repeat {active.club_code}) before the next deadline."
            ),
        }
    latest = latest_td(db, manager_id)
    if latest and int(latest.end_gw) < int(gw_number) and active is None:
        return {
            "level": "urgent",
            "club_code": latest.club_code,
            "end_gw": latest.end_gw,
            "message": "Your DT pick has expired — choose a new club now.",
        }
    return None


# Back-compat aliases used by routes
def current_td(db: Session, manager_id: int, gw_number: int) -> Optional[TechnicalDirectorPick]:
    return active_td(db, manager_id, gw_number)


def block_bounds(gw_number: int) -> tuple[int, int]:
    return window_for_start(gw_number)
