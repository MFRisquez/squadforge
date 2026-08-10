"""League create/join and manager helpers."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import ChipState, League, Manager, Membership
from app.services.seed import invite_code


class LeagueError(ValueError):
    pass


def get_or_create_manager(db: Session, display_name: str, pin: str, team_name: str = "") -> Manager:
    name = display_name.strip()
    if len(name) < 2:
        raise LeagueError("Name too short")
    if len(pin) < 4:
        raise LeagueError("PIN must be at least 4 characters")

    existing = db.query(Manager).filter(Manager.display_name == name).one_or_none()
    if existing:
        if existing.pin != pin:
            raise LeagueError("Wrong PIN for that name")
        if team_name and not existing.team_name:
            existing.team_name = team_name.strip()
            db.commit()
        return existing

    manager = Manager(display_name=name, pin=pin, team_name=team_name.strip() or f"{name}'s XI")
    db.add(manager)
    db.flush()
    db.add(ChipState(manager_id=manager.id))
    db.commit()
    db.refresh(manager)
    return manager


def create_league(
    db: Session,
    name: str,
    manager: Manager,
    league_type: str = "classic",
) -> League:
    lt = (league_type or "classic").strip().lower()
    if lt not in {"classic", "h2h"}:
        raise LeagueError("League type must be classic or h2h")
    league = League(
        name=name.strip() or "Private League",
        invite_code=invite_code(),
        league_type=lt,
    )
    db.add(league)
    db.flush()
    db.add(Membership(league_id=league.id, manager_id=manager.id))
    db.commit()
    db.refresh(league)
    return league


def set_league_type(db: Session, league: League, league_type: str) -> League:
    lt = league_type.strip().lower()
    if lt not in {"classic", "h2h"}:
        raise LeagueError("League type must be classic or h2h")
    members = db.query(Membership).filter(Membership.league_id == league.id).count()
    if lt == "h2h" and members % 2 != 0:
        raise LeagueError("Head-to-Head needs an even number of managers (2, 4, 6…)")
    league.league_type = lt
    db.commit()
    db.refresh(league)
    return league


def join_league(db: Session, code: str, manager: Manager) -> League:
    league = db.query(League).filter(League.invite_code == code.strip().upper()).one_or_none()
    if not league:
        raise LeagueError("Invite code not found")
    already = (
        db.query(Membership)
        .filter(Membership.league_id == league.id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not already:
        members = db.query(Membership).filter(Membership.league_id == league.id).count()
        if members >= 12:
            raise LeagueError("League is full (max 12 for now)")
        db.add(Membership(league_id=league.id, manager_id=manager.id))
        db.commit()
    return league


def manager_leagues(db: Session, manager_id: int) -> list[League]:
    rows = (
        db.query(League)
        .join(Membership)
        .filter(Membership.manager_id == manager_id)
        .all()
    )
    return rows
