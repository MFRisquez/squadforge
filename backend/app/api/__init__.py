from __future__ import annotations

import threading
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


@router.get("/debug/live-ingest")
def debug_live_ingest(token: str = "") -> dict:
    """Temporary: diagnose why XI points stay 0 during live matches."""
    if token != "probe-9855-live-ingest":
        return {"ok": False, "error": "forbidden"}
    from datetime import datetime, timezone

    from app.models import Fixture, MatchEvent, Player, PlayerPoints
    from app.services import deadline as deadline_svc
    from app.services import live_scoring as live_svc
    from app.services import squad as squad_svc
    from app.config import settings

    db = SessionLocal()
    try:
        gw = squad_svc.current_gameweek(db)
        dl = deadline_svc.parse_deadline(gw)
        passed = deadline_svc.deadline_passed(gw)
        live_fx = [
            {
                "id": fx.id,
                "home": fx.home_club_code,
                "away": fx.away_club_code,
                "started": bool(fx.started),
                "finished": bool(fx.finished),
                "score": [fx.home_score, fx.away_score],
            }
            for fx in db.query(Fixture).filter(Fixture.gameweek_number == int(gw.number)).all()
            if fx.started and not fx.finished
        ]
        # FPL fetch from this host
        fpl_ok = None
        fpl_err = None
        mbeumo_fpl_mins = None
        try:
            live = live_svc._http_get(live_svc.FPL_EVENT_LIVE.format(gw=gw.number))
            els = live.get("elements") or []
            fpl_ok = {"elements": len(els)}
            for e in els:
                if int(e.get("id") or 0) == 427:
                    mbeumo_fpl_mins = (e.get("stats") or {}).get("minutes")
                    break
        except Exception as exc:
            fpl_err = str(exc)

        # Run scoring directly (bypass maybe_score deadline gate)
        summary = live_svc.run_gameweek_scoring(db, prefer_live=True, force_demo=False)

        def player_snap(name_sub: str):
            out = []
            for p in db.query(Player).filter(Player.name.ilike(f"%{name_sub}%")).limit(3).all():
                rows = (
                    db.query(MatchEvent)
                    .filter(MatchEvent.gameweek_id == gw.id, MatchEvent.player_id == p.id)
                    .all()
                )
                metrics = {r.metric: {"value": float(r.value), "source": r.source} for r in rows}
                pts = (
                    db.query(PlayerPoints)
                    .filter(
                        PlayerPoints.gameweek_id == gw.id,
                        PlayerPoints.player_id == p.id,
                        PlayerPoints.formula_version == settings.formula_version,
                    )
                    .one_or_none()
                )
                out.append(
                    {
                        "id": p.id,
                        "name": p.name,
                        "external_id": p.external_id,
                        "team": p.team_code,
                        "minutes": metrics.get("minutes"),
                        "tackles": metrics.get("tackles"),
                        "points": float(pts.total) if pts else None,
                    }
                )
            return out

        return {
            "ok": True,
            "now": datetime.now(timezone.utc).isoformat(),
            "gw": gw.number,
            "gw_status": gw.status,
            "deadline_at": gw.deadline_at,
            "deadline_parsed": dl.isoformat() if dl else None,
            "deadline_passed": passed,
            "live_fixtures": live_fx,
            "fpl_ok": fpl_ok,
            "fpl_err": fpl_err,
            "mbeumo_fpl_mins": mbeumo_fpl_mins,
            "score_summary": {
                "ingest": summary.get("ingest"),
                "players_scored": summary.get("players_scored"),
                "managers_scored": summary.get("managers_scored"),
            },
            "players": {
                "Mbeumo": player_snap("Mbeumo"),
                "McBurnie": player_snap("McBurnie"),
                "Calafiori": player_snap("Calafiori"),
                "Ndiaye": player_snap("Ndiaye"),
                "Ballard": player_snap("Ballard"),
            },
        }
    finally:
        db.close()



class SoftNavPerfBody(BaseModel):
    url: str = Field(default="", max_length=512)
    fetch_ms: float = Field(default=0, ge=0)
    scripts_ms: float = Field(default=0, ge=0)
    total_ms: float = Field(default=0, ge=0)
    from_cache: bool = False
    server_perf: Optional[dict] = None


@router.post("/client-perf")
def client_perf(body: SoftNavPerfBody) -> dict:
    """Browser soft-nav timings (fetch vs scripts). Temporary measurement hook."""
    import logging
    import time

    from app.perf_trace import record_perf_event

    log = logging.getLogger("squadforge.client_perf")
    entry = {
        "kind": "softnav",
        "ts": time.time(),
        "url": body.url,
        "fetch_ms": body.fetch_ms,
        "scripts_ms": body.scripts_ms,
        "total_ms": body.total_ms,
        "from_cache": body.from_cache,
    }
    if body.server_perf:
        entry["server_perf"] = body.server_perf
    record_perf_event(entry)
    log.info(
        "softnav url=%s fetch_ms=%.1f scripts_ms=%.1f total_ms=%.1f from_cache=%s server_perf=%s",
        body.url,
        body.fetch_ms,
        body.scripts_ms,
        body.total_ms,
        body.from_cache,
        body.server_perf,
    )
    return {"ok": True}


@router.get("/client-perf")
def client_perf_list(limit: int = 40) -> dict:
    """Recent soft-nav / server / catalog timings (newest last)."""
    from app.perf_trace import list_perf_events, perf_event_count

    events = list_perf_events(limit)
    return {"ok": True, "count": perf_event_count(), "events": events}


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
    """Pull latest FPL fixture scores/stats, then return the selected GW list.

    Also kicks fantasy live scoring (minutes → PlayerPoints) so Lineup/League
    stay in sync without waiting only for the 120s daemon.
    """
    import threading

    db = SessionLocal()
    try:
        from app.services import squad as squad_svc

        if gw is None:
            current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
            gw_number = current.number if current else 1
        else:
            gw_number = int(gw)
        try:
            # Current GW only (~10) — never re-upsert the full 380-fixture season
            # on every Refresh tap / poll.
            info = fixtures_svc.refresh_fixtures(db, scope="gw", gw_number=gw_number)
        except Exception as exc:
            info = {"fixtures": 0, "error": str(exc)}

        squad_svc.maybe_advance_finished_gameweek(db)
        matches = fixtures_svc.fixtures_for_gameweek(db, gw_number=gw_number)
        try:
            matches = fixtures_svc.enrich_live_scorer_minutes(db, matches)
        except Exception:  # noqa: BLE001 — poll must still return scores
            pass
        return {
            "gw": gw_number,
            "synced": info,
            "fixtures": matches,
        }
    finally:
        db.close()
        # Score after closing the list DB so we don't hold the connection.
        def _score() -> None:
            from app.services.auto_score import maybe_score_locked_gw

            maybe_score_locked_gw(force=True)

        threading.Thread(target=_score, daemon=True).start()


@router.get("/xi/live-points")
def api_xi_live_points(request: Request, gw: Optional[int] = None) -> dict:
    """Pollable live PlayerPoints + fixture-started map for the locked Lineup.

    Kick scoring in a background thread — never block the sole uvicorn worker on
    a full FPL ingest (that was a common Render 502 under live GW traffic).
    """
    import json

    from app.auth import current_manager
    from app.config import settings
    from app.models import Fixture, ManagerGameweekScore, PlayerPoints
    from app.services import deadline as deadline_svc
    from app.services import squad as squad_svc
    from app.services.auto_score import maybe_score_locked_gw

    should_score = False
    gw_number: Optional[int] = int(gw) if gw is not None else None
    db = SessionLocal()
    try:
        manager = current_manager(request, db)
        if not manager:
            return {"ok": False, "error": "auth"}
        try:
            gameweek = deadline_svc.get_gameweek(db, gw_number)
        except Exception:
            return {"ok": False, "error": "gameweek"}
        current = squad_svc.current_gameweek(db)
        should_score = gameweek.id == current.id and deadline_svc.deadline_passed(current)
        manager_id = manager.id
        gameweek_id = gameweek.id
        gameweek_number = int(gameweek.number)
    finally:
        db.close()

    if should_score:
        threading.Thread(
            target=lambda: maybe_score_locked_gw(force=True),
            daemon=True,
            name="xi-live-points-score",
        ).start()

    db = SessionLocal()
    try:
        points: dict[str, float] = {}
        breakdowns: dict[str, dict] = {}
        for row in (
            db.query(PlayerPoints)
            .filter(
                PlayerPoints.gameweek_id == gameweek_id,
                PlayerPoints.formula_version == settings.formula_version,
            )
            .all()
        ):
            points[str(row.player_id)] = float(row.total or 0)
            try:
                bd = json.loads(row.breakdown_json or "{}")
            except Exception:
                bd = {}
            if isinstance(bd, dict):
                breakdowns[str(row.player_id)] = {
                    str(k): float(v or 0) for k, v in bd.items()
                }
        started_clubs: set[str] = set()
        live_clubs: set[str] = set()
        for fx in db.query(Fixture).filter(Fixture.gameweek_number == gameweek_number).all():
            if fx.finished:
                if fx.home_club_code:
                    started_clubs.add(fx.home_club_code)
                if fx.away_club_code:
                    started_clubs.add(fx.away_club_code)
            elif fx.started:
                if fx.home_club_code:
                    started_clubs.add(fx.home_club_code)
                    live_clubs.add(fx.home_club_code)
                if fx.away_club_code:
                    started_clubs.add(fx.away_club_code)
                    live_clubs.add(fx.away_club_code)
        owned = squad_svc.owned_players(db, manager_id)
        fixture_started = {str(p.id): p.team_code in started_clubs for p in owned}
        fixture_live = {str(p.id): p.team_code in live_clubs for p in owned}
        score = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager_id,
                ManagerGameweekScore.gameweek_id == gameweek_id,
            )
            .one_or_none()
        )
        return {
            "ok": True,
            "gw": gameweek_number,
            "points": points,
            "breakdowns": breakdowns,
            "fixtureStarted": fixture_started,
            "fixtureLive": fixture_live,
            "gwTotal": float(score.total) if score else None,
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


@router.get("/xi/side-kpis")
def api_xi_side_kpis(request: Request, gw: Optional[int] = None) -> dict:
    """Deferred XI left-rail KPIs (top scorers + position charts).

    Kept off the initial /lineup HTML so soft-nav paints the pitch first.
    Phones never show the rail — skip the heavy desk_side work entirely.
    """
    from app.auth import current_manager
    from app.desk_viewport import request_wants_desk_side
    from app.services import deadline as deadline_svc

    if not request_wants_desk_side(request):
        return {"ok": True, "skipped": "mobile", "top_scorers": [], "rank_spark": None}

    from app.services import desk_side as desk_side_svc
    from app.services import league as league_svc

    db = SessionLocal()
    try:
        manager = current_manager(request, db)
        if not manager:
            return {"ok": False, "error": "auth"}
        try:
            gameweek = deadline_svc.get_gameweek(db, int(gw) if gw is not None else None)
        except Exception:
            return {"ok": False, "error": "gameweek"}
        leagues = league_svc.manager_leagues(db, manager.id)
        payload = desk_side_svc.xi_side_kpis_payload(
            db, manager_id=manager.id, gw=gameweek, leagues=leagues
        )
        return {"ok": True, "gw": int(gameweek.number), **payload}
    finally:
        db.close()


@router.get("/league/{league_id}/h2h-rival")
def api_h2h_rival(league_id: int, request: Request, gw: Optional[int] = None) -> dict:
    """Deferred YOU VS RIVAL dual XI — kept off initial /league HTML.

    Same freeze rules as the opponent page: pre-deadline current GW uses the
    previous locked squad (or unavailable on GW1).
    """
    from app.auth import current_manager
    from app.models import Membership
    from app.services import deadline as deadline_svc
    from app.services import squad as squad_svc
    from app.services import standings as standings_svc

    db = SessionLocal()
    try:
        manager = current_manager(request, db)
        if not manager:
            return {"ok": False, "error": "auth"}
        membership = (
            db.query(Membership)
            .filter(
                Membership.league_id == league_id,
                Membership.manager_id == manager.id,
            )
            .one_or_none()
        )
        if not membership:
            return {"ok": False, "error": "forbidden"}
        league = membership.league
        if getattr(league, "league_type", "classic") != "h2h":
            return {"ok": False, "error": "not_h2h"}
        try:
            gameweek = deadline_svc.get_gameweek(db, int(gw) if gw is not None else None)
        except Exception:
            return {"ok": False, "error": "gameweek"}
        current = squad_svc.current_gameweek(db)
        if gameweek.id != current.id:
            edits_locked = True
        else:
            edits_locked = not deadline_svc.can_edit(current)
        snap = standings_svc.my_h2h_rival_snapshot(
            db,
            league,
            gameweek,
            manager.id,
            edits_locked=edits_locked,
            current_gw_id=current.id,
        )
        if snap is None:
            return {"ok": False, "error": "empty"}
        return {"ok": True, "gw": int(gameweek.number), "rival": snap}
    finally:
        db.close()
