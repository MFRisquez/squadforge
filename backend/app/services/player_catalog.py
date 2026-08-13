"""Shared FPL player catalog for Transfers / onboard (cached)."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models import Club, Gameweek, Player

_CACHE: tuple[float, str, list[dict[str, Any]]] | None = None
_CACHE_TTL = 60.0


def _season_kpis(player: Player) -> dict[str, Any]:
    try:
        stats = json.loads(getattr(player, "season_stats_json", None) or "{}")
    except json.JSONDecodeError:
        stats = {}
    if not isinstance(stats, dict):
        stats = {}
    try:
        form = float(stats.get("form") or 0)
    except (TypeError, ValueError):
        form = 0.0
    try:
        total_points = int(float(stats.get("total_points") or 0))
    except (TypeError, ValueError):
        total_points = 0
    return {"form": form, "total_points": total_points}


def catalog_version(db: Session) -> str:
    """Cheap fingerprint for client / HTTP cache."""
    count = db.query(Player).count()
    current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
    gw = current.number if current else 0
    return f"{count}-{gw}"


def build_players_catalog(db: Session, *, force: bool = False) -> tuple[list[dict[str, Any]], str]:
    """Return (players, version). In-process cache for ~60s."""
    global _CACHE
    version = catalog_version(db)
    now = time.monotonic()
    if (
        not force
        and _CACHE is not None
        and _CACHE[1] == version
        and (now - _CACHE[0]) < _CACHE_TTL
    ):
        return _CACHE[2], version

    from app.kits import kit_for
    from app.services import fixtures as fixtures_svc
    from app.services.fpl_sync import availability_flag

    clubs = {c.code: c for c in db.query(Club).all()}
    players = db.query(Player).order_by(Player.position, Player.price.desc()).all()
    current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
    from_gw = current.number if current else 1
    fdr_by_club = fixtures_svc.club_next_fdr_map(db, from_gw=from_gw)
    payload = [
        {
            "id": p.id,
            "name": p.name,
            "position": p.position,
            "team": p.team_code,
            "club": getattr(clubs.get(p.team_code), "name", None) or p.team_code,
            "price": p.price,
            "status": getattr(p, "status", "a") or "a",
            "chance": getattr(p, "chance_of_playing", None),
            "news": getattr(p, "news", "") or "",
            "availability": availability_flag(
                getattr(p, "status", "a") or "a",
                getattr(p, "chance_of_playing", None),
            ),
            "fdr": fdr_by_club.get(p.team_code),
            **_season_kpis(p),
            **kit_for(
                p.team_code,
                position=p.position,
                kit_code=getattr(clubs.get(p.team_code), "kit_code", None),
                photo=getattr(p, "photo", "") or "",
                player_id=p.id,
            ),
        }
        for p in players
    ]
    _CACHE = (now, version, payload)
    return payload, version


def clear_players_catalog_cache() -> None:
    global _CACHE
    _CACHE = None
