"""Shared FPL player catalog for Transfers / onboard (cached)."""

from __future__ import annotations

import json
import time
from typing import Any

from sqlalchemy.orm import Session

from app.models import Club, Gameweek, Player
from app.perf_trace import record_perf_event

# (monotonic_ts, version, players)
_CACHE: tuple[float, str, list[dict[str, Any]]] | None = None
# (monotonic_ts, version, current_gw_number)
_VERSION_CACHE: tuple[float, str, int] | None = None
# (monotonic_ts, from_gw, fdr_by_club)
_FDR_CACHE: tuple[float, int, dict[str, dict[str, Any]]] | None = None
_CACHE_TTL = 60.0


def _safe_float(stats: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(stats.get(key) or default)
    except (TypeError, ValueError):
        return default


def _season_kpis(player: Player) -> dict[str, Any]:
    try:
        stats = json.loads(getattr(player, "season_stats_json", None) or "{}")
    except json.JSONDecodeError:
        stats = {}
    if not isinstance(stats, dict):
        stats = {}
    form = _safe_float(stats, "form")
    try:
        total_points = int(_safe_float(stats, "total_points"))
    except (TypeError, ValueError):
        total_points = 0
    return {
        "form": form,
        "total_points": total_points,
        # ICT / defensive axes for transfer In-picker mini-radar
        "threat": _safe_float(stats, "threat"),
        "creativity": _safe_float(stats, "creativity"),
        "cbi": _safe_float(stats, "cbi"),
    }


def catalog_version(db: Session) -> str:
    """Fingerprint for client / HTTP cache (TTL-cached in-process)."""
    global _VERSION_CACHE
    now = time.monotonic()
    if _VERSION_CACHE is not None and (now - _VERSION_CACHE[0]) < _CACHE_TTL:
        return _VERSION_CACHE[1]
    count = db.query(Player).count()
    current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
    gw = current.number if current else 0
    version = f"{count}-{gw}"
    _VERSION_CACHE = (now, version, gw or 1)
    return version


def _resolve_from_gw(db: Session, *, force: bool = False) -> tuple[int, float]:
    """Current GW number for FDR/version — prefer version cache, else one SELECT."""
    global _VERSION_CACHE
    now = time.monotonic()
    if (
        not force
        and _VERSION_CACHE is not None
        and (now - _VERSION_CACHE[0]) < _CACHE_TTL
    ):
        return _VERSION_CACHE[2], 0.0
    t0 = time.perf_counter()
    current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
    from_gw = current.number if current else 1
    ms = (time.perf_counter() - t0) * 1000.0
    return from_gw, ms


def _cached_fdr_map(
    db: Session,
    *,
    from_gw: int,
    clubs: dict[str, Club] | None = None,
    force: bool = False,
) -> tuple[dict[str, dict[str, Any]], float]:
    """club_next_fdr_map with in-process TTL cache; reuse clubs when provided."""
    global _FDR_CACHE
    now = time.monotonic()
    if (
        not force
        and _FDR_CACHE is not None
        and _FDR_CACHE[1] == from_gw
        and (now - _FDR_CACHE[0]) < _CACHE_TTL
    ):
        return _FDR_CACHE[2], 0.0

    from app.services import fixtures as fixtures_svc

    t0 = time.perf_counter()
    fdr_by_club = fixtures_svc.club_next_fdr_map(db, from_gw=from_gw, clubs=clubs)
    ms = (time.perf_counter() - t0) * 1000.0
    _FDR_CACHE = (now, from_gw, fdr_by_club)
    return fdr_by_club, ms


def build_players_catalog(db: Session, *, force: bool = False) -> tuple[list[dict[str, Any]], str]:
    """Return (players, version). In-process cache for ~60s.

    Warm path: no DB (TTL hit). Cold rebuild: skip Player.COUNT — version uses
    ``len(players)``; FDR map is TTL-cached and reuses the clubs query.
    """
    global _CACHE, _VERSION_CACHE
    t_all = time.perf_counter()
    now = time.monotonic()

    # TTL-first: skip version DB hit entirely while the catalog is warm.
    if not force and _CACHE is not None and (now - _CACHE[0]) < _CACHE_TTL:
        record_perf_event(
            {
                "kind": "catalog",
                "url": "/api/players/catalog",
                "from_cache": True,
                "player_count": len(_CACHE[2]),
                "server_ms": round((time.perf_counter() - t_all) * 1000.0, 1),
                "spans": [
                    {"name": "catalog.version", "ms": 0.0},
                    {"name": "catalog.cache_hit", "ms": 0.0},
                ],
            }
        )
        return _CACHE[2], _CACHE[1]

    from app.kits import kit_for
    from app.services.fpl_sync import availability_flag

    from_gw, version_ms = _resolve_from_gw(db, force=force)

    t0 = time.perf_counter()
    clubs = {c.code: c for c in db.query(Club).all()}
    clubs_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    players = db.query(Player).order_by(Player.position, Player.price.desc()).all()
    players_query_ms = (time.perf_counter() - t0) * 1000.0
    player_count = len(players)

    version = f"{player_count}-{from_gw}"
    _VERSION_CACHE = (now, version, from_gw)

    fdr_by_club, fdr_ms = _cached_fdr_map(db, from_gw=from_gw, clubs=clubs, force=force)

    t0 = time.perf_counter()
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
    build_loop_ms = (time.perf_counter() - t0) * 1000.0
    _CACHE = (now, version, payload)
    total_ms = (time.perf_counter() - t_all) * 1000.0
    spans = [
        {"name": "catalog.version", "ms": round(version_ms, 1)},
        {"name": "catalog.clubs_query", "ms": round(clubs_ms, 1)},
        {"name": "catalog.players_query", "ms": round(players_query_ms, 1), "n": player_count},
        {"name": "catalog.fdr_map", "ms": round(fdr_ms, 1)},
        {
            "name": "catalog.build_loop",
            "ms": round(build_loop_ms, 1),
            "n": player_count,
            "per_player_ms": round(build_loop_ms / player_count, 3) if player_count else 0,
        },
    ]
    record_perf_event(
        {
            "kind": "catalog",
            "url": "/api/players/catalog",
            "from_cache": False,
            "player_count": player_count,
            "server_ms": round(total_ms, 1),
            "spans": spans,
        }
    )
    return payload, version


def clear_players_catalog_cache() -> None:
    global _CACHE, _VERSION_CACHE, _FDR_CACHE
    _CACHE = None
    _VERSION_CACHE = None
    _FDR_CACHE = None
