from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from app.scoring import score_player
from app.sync import demo_metrics_for_positions
from app.db import SessionLocal
from app.models import Gameweek, Player
from app.services import fixtures as fixtures_svc
from app.services import player_photos as photos_svc
from app.services import player_profile as profile_svc

router = APIRouter(prefix="/api")


class ScoreRequest(BaseModel):
    position: str = Field(description="GK, DEF, MID, or ATT")
    metrics: dict = Field(default_factory=dict)
    owners_count: Optional[int] = Field(
        default=None, description="How many managers in the league own this player"
    )
    league_size: Optional[int] = Field(default=None, description="Managers in the private league")


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "squadforge"}


@router.post("/score")
def score_endpoint(body: ScoreRequest) -> dict:
    """Try a formula live — useful while we tune weights together."""
    result = score_player(
        body.position,
        body.metrics,
        owners_count=body.owners_count,
        league_size=body.league_size,
    )
    return {
        "total": result.total,
        "breakdown": result.breakdown,
        "formula_version": result.formula_version,
        "position": result.position,
    }


@router.get("/demo-scores")
def demo_scores() -> dict:
    """One fake player per position so you can see points immediately."""
    out = {}
    for position, metrics in demo_metrics_for_positions().items():
        result = score_player(position, metrics)
        out[position] = {
            "metrics": metrics,
            "total": result.total,
            "breakdown": result.breakdown,
            "formula_version": result.formula_version,
        }
    return out


@router.get("/players/catalog")
def players_catalog() -> Response:
    """Full Free Agents catalog for Transfers / onboard (browser-cached)."""
    from fastapi.responses import JSONResponse

    from app.services.player_catalog import build_players_catalog

    db = SessionLocal()
    try:
        players, version = build_players_catalog(db)
        etag = f'W/"{version}"'
        return JSONResponse(
            content={"ok": True, "version": version, "players": players},
            headers={
                "Cache-Control": "private, max-age=60, stale-while-revalidate=300",
                "ETag": etag,
            },
        )
    finally:
        db.close()


@router.get("/players/{player_id}/photo")
def player_photo(player_id: int) -> Response:
    """Best available headshot (cached). Falls back to FotMob when PL CDN 403s."""
    db = SessionLocal()
    try:
        player = db.query(Player).filter(Player.id == int(player_id)).one_or_none()
        if not player:
            return Response(status_code=404)
        found = photos_svc.fetch_best_photo(player)
        if not found:
            return Response(status_code=404)
        data, ctype = found
        return Response(
            content=data,
            media_type=ctype,
            headers={
                "Cache-Control": "public, max-age=86400",
            },
        )
    finally:
        db.close()


@router.get("/players/{player_id}/fixtures")
def player_next_fixtures(player_id: int, n: int = 3) -> dict:
    """Next N fixtures for a player’s club with FDR mapped to 1–4."""
    limit = max(1, min(6, int(n or 3)))
    db = SessionLocal()
    try:
        items = fixtures_svc.next_fixtures_for_player(db, player_id=player_id, limit=limit)
        return {"player_id": player_id, "fixtures": items}
    finally:
        db.close()


@router.get("/players/{player_id}")
def player_card(player_id: int, mode: str = "season", gw: Optional[int] = None) -> dict:
    """Player detail: mode=season (Squad) or match (Lineup / locked GW)."""
    db = SessionLocal()
    try:
        gameweek_id = None
        if gw is not None:
            row = db.query(Gameweek).filter(Gameweek.number == int(gw)).one_or_none()
            gameweek_id = row.id if row else None
        profile = profile_svc.player_profile(
            db,
            player_id=player_id,
            mode="match" if mode == "match" else "season",
            gameweek_id=gameweek_id,
        )
        if not profile:
            return {"error": "not_found"}
        return profile
    finally:
        db.close()


@router.get("/clubs")
def api_clubs(exclude: Optional[str] = None) -> dict:
    """Club list for Technical Director picker."""
    from app.services import club_profile as club_svc

    db = SessionLocal()
    try:
        return {"ok": True, "clubs": club_svc.clubs_list(db, exclude=exclude)}
    finally:
        db.close()


@router.get("/clubs/{club_code}")
def api_club_detail(club_code: str, gw: Optional[int] = None) -> dict:
    """Club sheet: table stats, top scorers, next fixtures."""
    from app.services import club_profile as club_svc

    db = SessionLocal()
    try:
        from_gw = int(gw) if gw is not None else None
        if from_gw is None:
            current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
            from_gw = current.number if current else 1
        profile = club_svc.club_profile(db, club_code, from_gw=from_gw)
        if not profile:
            return {"error": "not_found"}
        return profile
    finally:
        db.close()


@router.get("/fixtures")
def api_fixtures(gw: Optional[int] = None) -> dict:
    db = SessionLocal()
    try:
        if gw is None:
            current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
            gw_number = current.number if current else 1
        else:
            gw_number = int(gw)
        return {"gw": gw_number, "fixtures": fixtures_svc.fixtures_for_gameweek(db, gw_number=gw_number)}
    finally:
        db.close()


@router.post("/fixtures/refresh")
def api_fixtures_refresh(gw: Optional[int] = None) -> dict:
    """Pull latest FPL fixture scores/stats, then return the selected GW list."""
    db = SessionLocal()
    try:
        try:
            info = fixtures_svc.refresh_fixtures(db)
        except Exception as exc:
            info = {"fixtures": 0, "error": str(exc)}
        if gw is None:
            current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
            gw_number = current.number if current else 1
        else:
            gw_number = int(gw)
        return {
            "gw": gw_number,
            "synced": info,
            "fixtures": fixtures_svc.fixtures_for_gameweek(db, gw_number=gw_number),
        }
    finally:
        db.close()


@router.get("/fixtures/{fixture_id}")
def api_fixture_detail(request: Request, fixture_id: int) -> dict:
    """Fast match sheet: local score/events/my_players only (no PulseLive)."""
    import logging
    import time

    from app.auth import current_manager
    from app.services import squad as squad_svc

    log = logging.getLogger("squadforge.fixtures")
    t0 = time.perf_counter()
    db = SessionLocal()
    try:
        owned = None
        manager = current_manager(request, db)
        if manager:
            owned = squad_svc.owned_players(db, manager.id)
        detail = fixtures_svc.fixture_detail(
            db, fixture_id=fixture_id, owned_players=owned
        )
        if not detail:
            return {"error": "not_found"}
        return detail
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        log.info("fixture_detail id=%s ms=%.1f", fixture_id, ms)
        db.close()


@router.get("/fixtures/{fixture_id}/preview")
def api_fixture_preview(fixture_id: int) -> dict:
    """Slow match-sheet enrichment: team news + PulseLive venue/formations."""
    import logging
    import time

    log = logging.getLogger("squadforge.fixtures")
    t0 = time.perf_counter()
    db = SessionLocal()
    try:
        preview = fixtures_svc.fixture_sheet_preview(db, fixture_id=fixture_id)
        if not preview:
            return {"error": "not_found"}
        return preview
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        log.info("fixture_preview id=%s ms=%.1f", fixture_id, ms)
        db.close()
