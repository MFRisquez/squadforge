"""Gameweek deadline helpers (FPL-style lock after deadline)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models import Gameweek


def parse_deadline(gw: Gameweek) -> Optional[datetime]:
    raw = getattr(gw, "deadline_at", None)
    if not raw:
        return None
    if isinstance(raw, datetime):
        dt = raw
    else:
        try:
            text = str(raw).replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def deadline_passed(gw: Gameweek, *, now: datetime | None = None) -> bool:
    """True when edits should be locked for this GW."""
    # Finished GWs are always locked
    if (gw.status or "").lower() == "finished":
        return True
    dl = parse_deadline(gw)
    if not dl:
        # No deadline stored yet — only lock finished
        return False
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now >= dl


def can_edit(gw: Gameweek) -> bool:
    return not deadline_passed(gw)


def can_edit_captain(gw: Gameweek) -> bool:
    """After deadline, C/V can still move until the gameweek is finished."""
    if (gw.status or "").lower() == "finished":
        return False
    return deadline_passed(gw)


def deadline_label(gw: Gameweek) -> str:
    dl = parse_deadline(gw)
    if not dl:
        return "Deadline TBA"
    # Show local-ish UTC string short
    return dl.astimezone(timezone.utc).strftime("%a %d %b · %H:%M UTC")


def get_gameweek(db: Session, number: int | None = None) -> Gameweek:
    if number:
        gw = db.query(Gameweek).filter(Gameweek.number == number).one_or_none()
        if gw:
            return gw
    from app.services import squad as squad_svc

    return squad_svc.current_gameweek(db)
