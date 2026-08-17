"""League create/join and manager helpers."""

from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import ChipState, H2HMatch, League, Manager, Membership, PasswordResetToken
from app.services import passwords as pw
from app.services.seed import invite_code

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LeagueError(ValueError):
    pass


def _norm_email(email: str) -> str:
    return (email or "").strip().lower()


def register_manager(
    db: Session,
    *,
    display_name: str,
    password: str,
    email: str,
    team_name: str,
) -> Manager:
    name = display_name.strip()
    mail = _norm_email(email)
    team = (team_name or "").strip()
    if len(name) < 2:
        raise LeagueError("Pick a user name with at least 2 characters.")
    if len(password) < 6:
        raise LeagueError("Password needs at least 6 characters.")
    if not EMAIL_RE.match(mail):
        raise LeagueError("That email doesn't look right — try again.")
    if len(team) < 2:
        team = f"{name}'s XI"

    if db.query(Manager).filter(Manager.display_name == name).one_or_none():
        raise LeagueError("That user name is taken — try another.")
    if db.query(Manager).filter(Manager.email == mail).one_or_none():
        raise LeagueError("That email already has an account — sign in instead.")

    manager = Manager(
        display_name=name,
        email=mail,
        password_hash=pw.hash_password(password),
        pin="",
        team_name=team,
    )
    db.add(manager)
    db.flush()
    db.add(ChipState(manager_id=manager.id))
    db.commit()
    db.refresh(manager)
    return manager


def authenticate_manager(db: Session, *, login: str, password: str) -> Manager:
    key = (login or "").strip()
    if not key or not password:
        raise LeagueError("Enter your user name or email, and your password.")

    manager = db.query(Manager).filter(Manager.display_name == key).one_or_none()
    if not manager and "@" in key:
        manager = db.query(Manager).filter(Manager.email == key.lower()).one_or_none()
    if not manager:
        raise LeagueError("No account with that name or email — create one to play.")

    if manager.password_hash:
        if not pw.verify_password(password, manager.password_hash):
            raise LeagueError("That password isn't right — try again.")
        return manager

    # Legacy PIN accounts: accept PIN once, then upgrade to hashed password
    if manager.pin and pw.verify_password(password, manager.pin):
        manager.password_hash = pw.hash_password(password)
        manager.pin = ""
        db.commit()
        db.refresh(manager)
        return manager

    raise LeagueError("That password isn't right — try again.")


def request_password_reset(db: Session, email: str) -> tuple[Manager | None, str | None]:
    """Create a reset token when the email exists. Unknown emails return (None, None)."""
    mail = _norm_email(email)
    if not EMAIL_RE.match(mail):
        raise LeagueError("That email doesn't look right — try again.")
    manager = db.query(Manager).filter(Manager.email == mail).one_or_none()
    if not manager:
        return None, None
    raw = pw.new_reset_token()
    db.add(
        PasswordResetToken(
            manager_id=manager.id,
            token_hash=pw.hash_token(raw),
            expires_at=pw.reset_expiry(hours=2).replace(tzinfo=None),
        )
    )
    db.commit()
    return manager, raw


def reset_password_with_token(db: Session, *, token: str, new_password: str) -> Manager:
    if len(new_password) < 6:
        raise LeagueError("Password needs at least 6 characters.")
    token_hash = pw.hash_token(token)
    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == token_hash, PasswordResetToken.used_at.is_(None))
        .one_or_none()
    )
    if not row:
        raise LeagueError("That reset link isn't valid anymore — request a new one.")
    expires = row.expires_at
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) > expires:
        raise LeagueError("That reset link expired — request a fresh one.")
    manager = db.query(Manager).filter(Manager.id == row.manager_id).one_or_none()
    if not manager:
        raise LeagueError("We couldn't find that account.")
    manager.password_hash = pw.hash_password(new_password)
    manager.pin = ""
    row.used_at = datetime.utcnow()
    db.commit()
    db.refresh(manager)
    return manager


def get_or_create_manager(db: Session, display_name: str, pin: str, team_name: str = "") -> Manager:
    """Backward-compatible helper for older tests — prefer register/authenticate."""
    name = display_name.strip()
    existing = db.query(Manager).filter(Manager.display_name == name).one_or_none()
    if existing:
        return authenticate_manager(db, login=name, password=pin)
    pwd = pin if len(pin) >= 6 else f"{pin}00xx"
    slug = re.sub(r"[^a-z0-9]+", ".", name.lower()).strip(".") or "user"
    return register_manager(
        db,
        display_name=name,
        password=pwd,
        email=f"{slug}@example.local",
        team_name=team_name.strip() or f"{name}'s XI",
    )


def create_league(
    db: Session,
    name: str,
    manager: Manager,
    league_type: str = "classic",
) -> League:
    lt = (league_type or "classic").strip().lower()
    if lt not in {"classic", "h2h"}:
        raise LeagueError("Choose Classic or Head-to-Head.")
    league = League(
        name=name.strip() or "Private League",
        invite_code=invite_code(),
        league_type=lt,
        owner_id=manager.id,
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
        raise LeagueError("Choose Classic or Head-to-Head.")
    members = db.query(Membership).filter(Membership.league_id == league.id).count()
    if lt == "h2h" and members % 2 != 0:
        raise LeagueError("Head-to-Head needs an even number of managers (2, 4, 6…).")
    league.league_type = lt
    db.commit()
    db.refresh(league)
    return league


def join_league(db: Session, code: str, manager: Manager) -> League:
    league = db.query(League).filter(League.invite_code == code.strip().upper()).one_or_none()
    if not league:
        raise LeagueError("That invite code didn't match any league.")
    already = (
        db.query(Membership)
        .filter(Membership.league_id == league.id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not already:
        members = db.query(Membership).filter(Membership.league_id == league.id).count()
        if members >= 12:
            raise LeagueError("This league is full (12 managers max for now).")
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


def backfill_null_league_owners(db: Session) -> int:
    """Assign owner_id on legacy leagues where it is NULL.

    Uses the earliest Membership (joined_at, then id) so Delete league works again.
    Returns how many leagues were updated.
    """
    orphans = db.query(League).filter(League.owner_id.is_(None)).all()
    updated = 0
    for league in orphans:
        first = (
            db.query(Membership)
            .filter(Membership.league_id == league.id)
            .order_by(Membership.joined_at.asc(), Membership.id.asc())
            .first()
        )
        if not first:
            continue
        league.owner_id = first.manager_id
        updated += 1
    if updated:
        db.commit()
    return updated


def delete_league(db: Session, league: League, requesting_manager_id: int) -> None:
    """Remove a league and its league-scoped rows (memberships + H2H fixtures)."""
    if league.owner_id != requesting_manager_id:
        raise LeagueError("Only the league creator can delete it")
    db.query(H2HMatch).filter(H2HMatch.league_id == league.id).delete(synchronize_session=False)
    db.query(Membership).filter(Membership.league_id == league.id).delete(synchronize_session=False)
    db.delete(league)
    db.commit()


def leave_league(db: Session, league: League, manager_id: int) -> None:
    """Drop one manager's membership. Owners must delete the league instead."""
    if manager_id == league.owner_id:
        raise LeagueError("The league creator can't leave — delete the league instead")
    row = (
        db.query(Membership)
        .filter(Membership.league_id == league.id, Membership.manager_id == manager_id)
        .one_or_none()
    )
    if not row:
        raise LeagueError("You're not in this league.")
    db.delete(row)
    db.commit()
