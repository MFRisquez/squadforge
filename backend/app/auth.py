"""Tiny cookie-session helpers."""

from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Manager, OwnedPlayer


def current_manager(request: Request, db: Session) -> Manager | None:
    mid = request.session.get("manager_id")
    if not mid:
        return None
    return db.query(Manager).filter(Manager.id == mid).one_or_none()


def require_manager(request: Request, db: Session) -> Manager:
    manager = current_manager(request, db)
    if not manager:
        raise HTTPException(status_code=401, detail="Please sign in")
    return manager


def login_manager(request: Request, manager: Manager) -> None:
    request.session["manager_id"] = manager.id


def logout_manager(request: Request) -> None:
    request.session.clear()


def manager_has_complete_squad(db: Session, manager_id: int) -> bool:
    """True when the manager has saved a full 15 (2·5·5·3)."""
    n = db.query(OwnedPlayer).filter(OwnedPlayer.manager_id == manager_id).count()
    return n >= settings.squad_size
