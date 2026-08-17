"""HTML routes for the phone-friendly MVP."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import current_manager, login_manager, logout_manager, manager_has_complete_squad
from app.config import settings
from app.db import get_db
from app.models import ChipState, Club, Gameweek, Membership, Player, SquadPick
from app.services import league as league_svc
from app.services import squad as squad_svc
from app.services import td as td_svc
from app.services.fpl_sync import sync_from_fpl
from app.services.seed import seed_if_empty

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "web" / "templates"))

_LOGIN_WINDOW_SEC = 15 * 60
_LOGIN_MAX_FAILURES = 5
_login_failures: dict[str, list[float]] = {}
_login_lock = threading.Lock()


def _client_ip(request: Request) -> str:
    forwarded = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    if request.client and request.client.host:
        return request.client.host
    return "unknown"


def _login_prune(failures: list[float], now: float) -> list[float]:
    cutoff = now - _LOGIN_WINDOW_SEC
    return [t for t in failures if t >= cutoff]


def _login_blocked(ip: str) -> bool:
    now = time.time()
    with _login_lock:
        recent = _login_prune(_login_failures.get(ip, []), now)
        _login_failures[ip] = recent
        return len(recent) >= _LOGIN_MAX_FAILURES


def _login_record_failure(ip: str) -> None:
    now = time.time()
    with _login_lock:
        recent = _login_prune(_login_failures.get(ip, []), now)
        recent.append(now)
        _login_failures[ip] = recent


def _login_clear_failures(ip: str) -> None:
    with _login_lock:
        _login_failures.pop(ip, None)

def _format_kickoff_zones(iso: str | None) -> str:
    """Short date + Mexico / US (ET) / Venezuela local times for fixture cards."""
    from markupsafe import Markup

    if not iso:
        return Markup('<span class="fx-status">TBC</span>')
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    try:
        raw = str(iso).replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return Markup(f'<span class="fx-status">{iso}</span>')

    local = dt.astimezone(ZoneInfo("America/Mexico_City"))
    date_part = f"{local.strftime('%a %b')} {local.day}"

    def _t(tz: str) -> str:
        return dt.astimezone(ZoneInfo(tz)).strftime("%H:%M")

    mx = _t("America/Mexico_City")
    us = _t("America/New_York")
    vz = _t("America/Caracas")
    return Markup(
        '<span class="fx-status">'
        f'<span class="fx-ko-date">{date_part}</span>'
        '<span class="fx-ko-zones">'
        f'<span class="fx-ko-z">Mx {mx}</span>'
        '<span class="fx-ko-bar" aria-hidden="true">|</span>'
        f'<span class="fx-ko-z">US {us}</span>'
        '<span class="fx-ko-bar" aria-hidden="true">|</span>'
        f'<span class="fx-ko-z">VZ {vz}</span>'
        "</span></span>"
    )


templates.env.filters["kickoff_zones"] = _format_kickoff_zones

_SHELL_NEXT_PREFIXES = (
    "/team",
    "/lineup",
    "/fixtures",
    "/home",
    "/rules",
    "/standings",
    "/league",
    "/onboard",
)


def _safe_next_path(raw: str | None, default: str = "/team") -> str:
    """Allow only same-app relative paths (no open redirects)."""
    path = (raw or "").strip() or default
    if not path.startswith("/") or path.startswith("//"):
        return default
    if "\\" in path or "://" in path:
        return default
    base = path.split("?", 1)[0].split("#", 1)[0]
    if not any(base == p or base.startswith(p + "/") for p in _SHELL_NEXT_PREFIXES):
        return default
    return path


def _redirect_with_query(path: str, **params: str) -> RedirectResponse:
    """Append query params safely (handles existing ? and encodes values)."""
    parts = urlsplit(path)
    q = dict(parse_qsl(parts.query, keep_blank_values=True))
    q.update({k: str(v) for k, v in params.items() if v is not None})
    dest = urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(q), parts.fragment))
    return RedirectResponse(dest, status_code=303)


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return (
        "application/json" in accept
        or request.query_params.get("format") == "json"
        or (request.headers.get("x-requested-with") or "").lower() == "fetch"
    )


def _resolve_gw(request: Request, db: Session):
    from app.services import deadline as deadline_svc

    raw = request.query_params.get("gw")
    number = int(raw) if raw and str(raw).isdigit() else None
    gw = deadline_svc.get_gameweek(db, number)
    current = squad_svc.current_gameweek(db)
    # Viewing a non-current GW is always locked for edits
    if gw.id != current.id:
        edits_locked = True
    else:
        edits_locked = not deadline_svc.can_edit(current)
    all_gws = db.query(Gameweek).order_by(Gameweek.number).all()
    numbers = [g.number for g in all_gws]
    idx = numbers.index(gw.number) if gw.number in numbers else 0
    prev_gw = numbers[idx - 1] if idx > 0 else None
    next_gw = numbers[idx + 1] if idx + 1 < len(numbers) else None
    return {
        "gw": gw,
        "current_gw": current,
        "edits_locked": edits_locked,
        "deadline_label": deadline_svc.deadline_label(gw),
        "prev_gw": prev_gw,
        "next_gw": next_gw,
        "all_gws": numbers,
        "current_gw_number": current.number,
    }


def _ctx(request: Request, db: Session, **extra):
    manager = current_manager(request, db)
    gw = None
    try:
        gw = squad_svc.current_gameweek(db)
    except Exception:
        pass
    leagues = league_svc.manager_leagues(db, manager.id) if manager else []
    has_squad = bool(manager and manager_has_complete_squad(db, manager.id))
    data = {
        "request": request,
        "app_name": settings.app_name,
        "manager": manager,
        "gw": gw,
        "budget": settings.budget,
        "nav_leagues": leagues,
        "has_complete_squad": has_squad,
        "error": None,
        "notice": None,
    }
    data.update(extra)
    return data


def _owned_payload(
    players: list[Player],
    db: Session | None = None,
    *,
    gw_number: int | None = None,
) -> list[dict]:
    from app.kits import kit_for
    from app.services import fixtures as fixtures_svc
    from app.services.fpl_sync import availability_flag

    clubs: dict[str, Club] = {}
    fdr_by_club: dict[str, dict] = {}
    if db is not None:
        clubs = {c.code: c for c in db.query(Club).all()}
        if gw_number:
            for match in fixtures_svc.fixtures_for_gameweek(db, gw_number=gw_number):
                fdr_by_club[match["home"]["code"]] = {
                    "opponent": match["away"]["code"],
                    "venue": "H",
                    "difficulty": match["home"]["difficulty"],
                    "gw": match["gw"],
                }
                fdr_by_club[match["away"]["code"]] = {
                    "opponent": match["home"]["code"],
                    "venue": "A",
                    "difficulty": match["away"]["difficulty"],
                    "gw": match["gw"],
                }
        else:
            current = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
            from_gw = current.number if current else 1
            fdr_by_club = fixtures_svc.club_next_fdr_map(db, from_gw=from_gw)

    return [
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


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    from app.services import demo_live as demo_svc

    manager = current_manager(request, db)
    if not manager:
        return templates.TemplateResponse(
            "login.html",
            _ctx(
                request,
                db,
                notice=request.query_params.get("notice"),
                error=request.query_params.get("error"),
            ),
        )
    if not manager_has_complete_squad(db, manager.id):
        return RedirectResponse("/onboard", status_code=303)
    leagues = league_svc.manager_leagues(db, manager.id)
    live_demo = False
    try:
        live_demo = demo_svc.is_live_demo_active(db)
    except Exception:
        live_demo = False
    return templates.TemplateResponse(
        "home.html",
        _ctx(
            request,
            db,
            leagues=leagues,
            formula_version=settings.formula_version,
            live_demo_active=live_demo,
            notice=request.query_params.get("notice"),
            error=request.query_params.get("error"),
        ),
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return RedirectResponse("/", status_code=303)


@router.post("/login")
def login_submit(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    ip = _client_ip(request)
    if _login_blocked(ip):
        return templates.TemplateResponse(
            "login.html",
            _ctx(
                request,
                db,
                error="Too many failed login attempts. Try again in 15 minutes.",
            ),
            status_code=429,
        )
    try:
        manager = league_svc.authenticate_manager(db, login=login, password=password)
    except league_svc.LeagueError as exc:
        _login_record_failure(ip)
        return templates.TemplateResponse(
            "login.html",
            _ctx(request, db, error=str(exc)),
            status_code=400,
        )
    _login_clear_failures(ip)
    login_manager(request, manager)
    if manager_has_complete_squad(db, manager.id):
        return RedirectResponse("/", status_code=303)
    return RedirectResponse("/onboard", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("register.html", _ctx(request, db))


@router.post("/register")
def register_submit(
    request: Request,
    display_name: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    email: str = Form(...),
    team_name: str = Form(""),
    db: Session = Depends(get_db),
):
    if password != password_confirm:
        return templates.TemplateResponse(
            "register.html",
            _ctx(request, db, error="Passwords don't match"),
            status_code=400,
        )
    try:
        manager = league_svc.register_manager(
            db,
            display_name=display_name,
            password=password,
            email=email,
            team_name=team_name,
        )
    except league_svc.LeagueError as exc:
        return templates.TemplateResponse(
            "register.html",
            _ctx(request, db, error=str(exc)),
            status_code=400,
        )
    login_manager(request, manager)
    return RedirectResponse("/onboard", status_code=303)


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("forgot_password.html", _ctx(request, db))


@router.post("/forgot-password")
def forgot_password_submit(
    request: Request,
    email: str = Form(...),
    db: Session = Depends(get_db),
):
    from app.services import mail as mail_svc

    try:
        manager, raw = league_svc.request_password_reset(db, email)
    except league_svc.LeagueError as exc:
        return templates.TemplateResponse(
            "forgot_password.html",
            _ctx(request, db, error=str(exc)),
            status_code=400,
        )

    # Always show a calm success message (no account enumeration)
    notice = "If that email is registered, a reset link is ready."
    reset_url = None
    if manager and raw:
        base = (settings.public_base_url or str(request.base_url)).rstrip("/")
        reset_url = f"{base}/reset-password?token={raw}"
        sent = mail_svc.send_password_reset_email(
            to_email=manager.email,
            reset_url=reset_url,
            display_name=manager.display_name,
        )
        if sent:
            notice = "Check your email for a password reset link."
            reset_url = None  # don't show raw link when mail was sent
        else:
            notice = "Email delivery isn’t configured yet — use the reset link below."

    return templates.TemplateResponse(
        "forgot_password.html",
        _ctx(request, db, notice=notice, reset_url=reset_url),
    )


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, db: Session = Depends(get_db), token: str = ""):
    if not token:
        return RedirectResponse("/forgot-password?error=Missing+reset+token", status_code=303)
    return templates.TemplateResponse(
        "reset_password.html",
        _ctx(request, db, token=token),
    )


@router.post("/reset-password")
def reset_password_submit(
    request: Request,
    token: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    db: Session = Depends(get_db),
):
    if password != password_confirm:
        return templates.TemplateResponse(
            "reset_password.html",
            _ctx(request, db, token=token, error="Passwords do not match"),
            status_code=400,
        )
    try:
        league_svc.reset_password_with_token(db, token=token, new_password=password)
    except league_svc.LeagueError as exc:
        return templates.TemplateResponse(
            "reset_password.html",
            _ctx(request, db, token=token, error=str(exc)),
            status_code=400,
        )
    return RedirectResponse("/login?notice=Password+updated+·+sign+in", status_code=303)


@router.post("/logout")
def logout(request: Request):
    logout_manager(request)
    return RedirectResponse("/", status_code=303)


@router.post("/league/create")
def create_league(
    request: Request,
    league_name: str = Form("Friends League"),
    league_type: str = Form("classic"),
    db: Session = Depends(get_db),
):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        league = league_svc.create_league(db, league_name, manager, league_type=league_type)
    except league_svc.LeagueError as exc:
        leagues = league_svc.manager_leagues(db, manager.id)
        return templates.TemplateResponse(
            "home.html",
            _ctx(
                request,
                db,
                leagues=leagues,
                error=str(exc),
                formula_version=settings.formula_version,
            ),
            status_code=400,
        )
    return RedirectResponse(f"/league/{league.id}", status_code=303)


@router.post("/league/join")
def join_league(
    request: Request,
    invite_code: str = Form(...),
    db: Session = Depends(get_db),
):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        league = league_svc.join_league(db, invite_code, manager)
    except league_svc.LeagueError as exc:
        leagues = league_svc.manager_leagues(db, manager.id)
        return templates.TemplateResponse(
            "home.html",
            _ctx(request, db, leagues=leagues, error=str(exc), formula_version=settings.formula_version),
            status_code=400,
        )
    return RedirectResponse(f"/league/{league.id}", status_code=303)


@router.get("/leagues", response_class=HTMLResponse)
def leagues_hub(request: Request, db: Session = Depends(get_db)):
    from app.services import standings as standings_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    leagues = league_svc.manager_leagues(db, manager.id)
    gw = squad_svc.current_gameweek(db)
    league_cards = []
    for league in leagues:
        rank, size = standings_svc.my_rank_in_league(db, league, manager.id, gw)
        league_cards.append(
            {
                "league": league,
                "my_rank": rank,
                "member_count": size,
            }
        )
    return templates.TemplateResponse(
        "leagues.html",
        _ctx(
            request,
            db,
            leagues=leagues,
            league_cards=league_cards,
            notice=request.query_params.get("notice"),
            error=request.query_params.get("error"),
        ),
    )


@router.get("/league/{league_id}", response_class=HTMLResponse)
def league_home(league_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services import standings as standings_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/", status_code=303)
    league = membership.league
    gw = squad_svc.current_gameweek(db)
    rank_history = {"gw_numbers": [], "series": [], "max_rank": 0}
    if getattr(league, "league_type", "classic") == "h2h":
        rows, _ = standings_svc.h2h_standings(db, league, gw)
        mode = "h2h"
    else:
        rows = standings_svc.classic_standings(db, league, gw)
        mode = "classic"
        rank_history = standings_svc.classic_rank_history(
            db, league, gw, me_id=manager.id
        )
    chips = db.query(ChipState).filter(ChipState.manager_id == manager.id).one_or_none()
    even = len(rows) % 2 == 0 and len(rows) >= 2
    return templates.TemplateResponse(
        "league.html",
        _ctx(
            request,
            db,
            league=league,
            rows=rows,
            mode=mode,
            me=manager,
            chips=chips,
            even_members=even,
            member_count=len(rows),
            gw=gw,
            rank_history=rank_history,
            notice=request.query_params.get("notice"),
            error=request.query_params.get("error"),
        ),
    )


@router.get("/league/{league_id}/awards", response_class=HTMLResponse)
def league_awards_page(league_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services import awards as awards_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/", status_code=303)
    league = membership.league
    payload = awards_svc.league_awards(db, league.id)
    return templates.TemplateResponse(
        "awards.html",
        _ctx(
            request,
            db,
            league=league,
            me=manager,
            awards=payload,
            notice=request.query_params.get("notice"),
            error=request.query_params.get("error"),
        ),
    )


@router.post("/league/{league_id}/type")
def league_set_type(
    league_id: int,
    request: Request,
    league_type: str = Form(...),
    db: Session = Depends(get_db),
):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/", status_code=303)
    try:
        league_svc.set_league_type(db, membership.league, league_type)
    except league_svc.LeagueError as exc:
        from app.services import standings as standings_svc

        league = membership.league
        gw = squad_svc.current_gameweek(db)
        rank_history = {"gw_numbers": [], "series": [], "max_rank": 0}
        if getattr(league, "league_type", "classic") == "h2h":
            rows, _ = standings_svc.h2h_standings(db, league, gw)
            mode = "h2h"
        else:
            rows = standings_svc.classic_standings(db, league, gw)
            mode = "classic"
            rank_history = standings_svc.classic_rank_history(
                db, league, gw, me_id=manager.id
            )
        return templates.TemplateResponse(
            "league.html",
            _ctx(
                request,
                db,
                league=league,
                rows=rows,
                mode=mode,
                me=manager,
                error=str(exc),
                even_members=len(rows) % 2 == 0 and len(rows) >= 2,
                member_count=len(rows),
                gw=gw,
                rank_history=rank_history,
            ),
            status_code=400,
        )
    return RedirectResponse(f"/standings/{league_id}", status_code=303)


@router.post("/league/{league_id}/delete")
def league_delete(league_id: int, request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/leagues", status_code=303)
    league = membership.league
    name = league.name
    try:
        league_svc.delete_league(db, league, manager.id)
    except league_svc.LeagueError as exc:
        return RedirectResponse(
            f"/league/{league_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/leagues?notice={quote(f'Deleted {name}.')}",
        status_code=303,
    )


@router.post("/league/{league_id}/leave")
def league_leave(league_id: int, request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/leagues", status_code=303)
    league = membership.league
    name = league.name
    try:
        league_svc.leave_league(db, league, manager.id)
    except league_svc.LeagueError as exc:
        return RedirectResponse(
            f"/league/{league_id}?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse(
        f"/leagues?notice={quote(f'Left {name}.')}",
        status_code=303,
    )


@router.get("/team", response_class=HTMLResponse)
def team_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    if not manager_has_complete_squad(db, manager.id):
        return RedirectResponse("/onboard", status_code=303)
    try:
        return _squad_board_response(request, db, manager, template_name="team.html")
    except squad_svc.SquadError as exc:
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)


@router.get("/onboard", response_class=HTMLResponse)
def onboard_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    if manager_has_complete_squad(db, manager.id):
        return RedirectResponse("/", status_code=303)
    return _squad_board_response(
        request,
        db,
        manager,
        template_name="onboard.html",
        notice=(
            request.query_params.get("notice")
            or "Pick your 15 (2 GK · 5 DEF · 5 MID · 3 ATT) within budget, then Save."
        ),
    )


def _squad_board_response(
    request: Request,
    db: Session,
    manager,
    *,
    template_name: str,
    notice: str | None = None,
):
    from app.models import TransferLog
    from app.services import chips as chips_svc
    from app.services import td as td_svc
    from app.services.captain_success import captain_success_for_manager
    from app.services.fpl_sync import availability_flag

    view = _resolve_gw(request, db)
    gw = view["gw"]
    captain_success = captain_success_for_manager(db, manager.id)
    ft_state = squad_svc.bank_free_transfers(db, manager.id, view["current_gw"].number)
    chips_svc.restore_free_hits_if_needed(db, manager_id=manager.id, current_gw=view["current_gw"])
    owned = squad_svc.owned_players(db, manager.id)
    spend = squad_svc.squad_spend(owned)
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == manager.id, SquadPick.gameweek_id == gw.id)
        .all()
    )
    by_id = {p.id: p for p in owned}
    pick_rows = []
    for pick in sorted(picks, key=lambda x: (0 if x.is_starter else 1, x.bench_order, x.id)):
        player = by_id.get(pick.player_id)
        if player:
            pick_rows.append({"pick": pick, "player": player})
    chips = chips_svc.ensure_chip_state(db, manager.id)
    active_chip = chips_svc.active_chip(db, manager.id, gw.id)
    td_info = td_svc.td_view(db, manager.id, gw.number, gameweek_id=gw.id)
    can_set_td = td_svc.can_change_td(db, manager.id, gw)
    clubs = db.query(Club).order_by(Club.name).all()
    td_club_choices = [c for c in clubs if c.code != td_info.get("banned_club")]
    unlimited = squad_svc.transfers_are_unlimited(db, manager.id, view["current_gw"])
    transfers_gw = (
        db.query(TransferLog)
        .filter(TransferLog.manager_id == manager.id, TransferLog.gameweek_id == gw.id)
        .count()
    )
    hits_gw = squad_svc.hit_transfers_this_gw(db, manager.id, gw.id)
    starters = [p.player_id for p in picks if p.is_starter]
    captain = next((p.player_id for p in picks if p.is_captain), None)
    vice = next((p.player_id for p in picks if getattr(p, "is_vice_captain", 0)), None)
    if len(owned) == settings.squad_size and not starters:
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(owned)
    bench_options = []
    for pick in sorted(picks, key=lambda x: (x.bench_order, x.id)):
        if pick.is_starter:
            continue
        player = by_id.get(pick.player_id)
        if player and not pick.is_captain and not getattr(pick, "is_vice_captain", 0):
            bench_options.append(player)
    flag_labels = {"out": "Out", "doubt": "Doubt", "ok": "OK"}
    squad_alerts = []
    for player in owned:
        flag = availability_flag(getattr(player, "status", "a"), getattr(player, "chance_of_playing", None))
        if flag not in ("out", "doubt"):
            continue
        squad_alerts.append(
            {
                "name": player.name,
                "club": player.team_code,
                "flag": flag,
                "flag_label": flag_labels.get(flag, flag.title()),
                "news": (getattr(player, "news", None) or "").strip(),
                "chance": getattr(player, "chance_of_playing", None),
            }
        )
    squad_alerts.sort(
        key=lambda a: (
            0 if a["flag"] == "out" else 1,
            a["chance"] if a["chance"] is not None else 999,
            a["name"],
        )
    )
    resolved_notice = notice
    if resolved_notice is None:
        resolved_notice = (
            request.query_params.get("notice")
            or ("Transfer done." if request.query_params.get("ok") else None)
        )
    return templates.TemplateResponse(
        template_name,
        _ctx(
            request,
            db,
            owned=owned,
            spend=spend,
            pick_rows=pick_rows,
            chips=chips,
            active_chip=active_chip,
            bench_options=bench_options,
            td=td_info.get("pick"),
            td_info=td_info,
            can_set_td=can_set_td,
            clubs=clubs,
            td_club_choices=td_club_choices,
            ft_left=ft_state.free_transfers,
            unlimited_transfers=unlimited,
            transfers_gw=transfers_gw,
            hits_gw=hits_gw,
            hit_cost=squad_svc.HIT_COST,
            players_json=[],  # loaded client-side from /api/players/catalog
            captain_success=captain_success,
            squad_alerts=squad_alerts,
            initial_squad={
                "selected": [p.id for p in owned],
                "budget": settings.budget,
                "maxPerClub": settings.max_per_club,
                "unlimited": unlimited and not view["edits_locked"],
                "hasSquad": len(owned) == settings.squad_size,
                "requireTd": template_name == "onboard.html" or len(owned) != settings.squad_size,
                "ft": ft_state.free_transfers,
                "hitCost": squad_svc.HIT_COST,
                "locked": view["edits_locked"],
                "starters": starters,
                "captain": captain,
                "vice": vice,
                "gw": gw.number,
            },
            player_count=db.query(Player).count(),
            ok=request.query_params.get("ok"),
            error=request.query_params.get("error") or request.query_params.get("chip_error"),
            notice=resolved_notice,
            **view,
        ),
    )


def _chip_state_payload(db: Session, manager_id: int, gw, *, cancelled_chip: str | None = None) -> dict:
    from app.services import chips as chips_svc

    state = chips_svc.ensure_chip_state(db, manager_id)
    active = chips_svc.active_chip(db, manager_id, gw.id)
    unlimited = squad_svc.transfers_are_unlimited(db, manager_id, gw)
    super_sub_player_id = None
    if active and active.chip == "super_sub":
        try:
            meta = json.loads(active.meta_json or "{}")
        except json.JSONDecodeError:
            meta = {}
        if meta.get("player_id") is not None:
            super_sub_player_id = int(meta["player_id"])
    return {
        "ok": True,
        "active_chip": active.chip if active else None,
        "active_label": chips_svc.CHIP_LABELS.get(active.chip, active.chip) if active else None,
        "super_sub_player_id": super_sub_player_id,
        "remaining": {
            "wildcard": int(state.wildcard_remaining or 0),
            "free_hit": int(state.free_hit_remaining or 0),
            "bench_boost": int(state.bench_boost_remaining or 0),
            "triple_captain": int(state.triple_captain_remaining or 0),
            "super_sub": int(state.super_sub_remaining or 0),
        },
        "unlimited_transfers": bool(unlimited),
        # Free Hit cancel restores the original 15 — client should refresh squad UI.
        "reload_squad": cancelled_chip == "free_hit",
    }


@router.post("/team/chip")
async def play_chip_from_squad(
    request: Request,
    chip: str = Form(...),
    player_id: Optional[int] = Form(None),
    next_path: str = Form("/team", alias="next"),
    db: Session = Depends(get_db),
):
    from app.services import chips as chips_svc
    from app.services.chips import ChipError

    wants_json = _wants_json(request)
    manager = current_manager(request, db)
    if not manager:
        if wants_json:
            return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    dest = _safe_next_path(next_path, "/team")
    try:
        chips_svc.play_chip(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            chip=chip,
            player_id=player_id,
        )
    except ChipError as exc:
        if wants_json:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return _redirect_with_query(dest, chip_error=str(exc))
    if wants_json:
        return JSONResponse(_chip_state_payload(db, manager.id, gw))
    return _redirect_with_query(dest, chip_ok="1")


@router.post("/team/chip/cancel")
async def cancel_chip_from_squad(
    request: Request,
    next_path: str = Form("/team", alias="next"),
    db: Session = Depends(get_db),
):
    from app.services import chips as chips_svc
    from app.services.chips import ChipError

    wants_json = _wants_json(request)
    manager = current_manager(request, db)
    if not manager:
        if wants_json:
            return JSONResponse({"ok": False, "error": "login_required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    dest = _safe_next_path(next_path, "/team")
    active = chips_svc.active_chip(db, manager.id, gw.id)
    cancelled = active.chip if active else None
    try:
        chips_svc.cancel_chip(db, manager_id=manager.id, gameweek_id=gw.id)
    except ChipError as exc:
        if wants_json:
            return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
        return _redirect_with_query(dest, chip_error=str(exc))
    if wants_json:
        return JSONResponse(_chip_state_payload(db, manager.id, gw, cancelled_chip=cancelled))
    return _redirect_with_query(dest, chip_ok="1")


@router.get("/team/edit", response_class=HTMLResponse)
def team_edit(request: Request, db: Session = Depends(get_db)):
    """Legacy URL — Squad & Transfers lives on /team."""
    return RedirectResponse("/team", status_code=303)


@router.post("/team/save")
async def team_save(request: Request, db: Session = Depends(get_db)):
    from app.services import deadline as deadline_svc

    wants_json = _wants_json(request)
    manager = current_manager(request, db)
    if not manager:
        if wants_json:
            return JSONResponse({"error": "login_required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    if not deadline_svc.can_edit(gw):
        if wants_json:
            return JSONResponse({"error": "Deadline passed — squad is locked"}, status_code=400)
        return RedirectResponse("/team?error=Deadline+passed+—+squad+is+locked", status_code=303)
    form = await request.form()
    player_ids = [int(x) for x in form.getlist("player_id")]
    gw = squad_svc.current_gameweek(db)
    try:
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=player_ids, gw_number=gw.number)
        owned = squad_svc.owned_players(db, manager.id)
        starters, _all, captain, vice = squad_svc.default_lineup_from_owned(owned)
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starters,
            captain_id=captain,
            vice_id=vice,
        )
    except squad_svc.SquadError as exc:
        if wants_json:
            return JSONResponse({"error": str(exc)}, status_code=400)
        clubs = db.query(Club).order_by(Club.name).all()
        from app.models import ChipPlay, TransferLog
        from app.services import chips as chips_svc
        from app.services import td as td_svc

        owned = squad_svc.owned_players(db, manager.id)
        ft_state = squad_svc.bank_free_transfers(db, manager.id, gw.number)
        unlimited = squad_svc.transfers_are_unlimited(db, manager.id, gw)
        return templates.TemplateResponse(
            "team.html",
            _ctx(
                request,
                db,
                owned=owned,
                spend=squad_svc.squad_spend(owned),
                pick_rows=[],
                chips=chips_svc.ensure_chip_state(db, manager.id),
                active_chip=db.query(ChipPlay)
                .filter(ChipPlay.manager_id == manager.id, ChipPlay.gameweek_id == gw.id)
                .one_or_none(),
                td=td_svc.current_td(db, manager.id, gw.number),
                can_set_td=td_svc.can_select_td(db, manager.id, gw.number),
                clubs=clubs,
                ft_left=ft_state.free_transfers,
                unlimited_transfers=unlimited,
                transfers_gw=0,
                hits_gw=0,
                hit_cost=squad_svc.HIT_COST,
                players_json=[],
                initial_squad={
                    "selected": player_ids,
                    "budget": settings.budget,
                    "maxPerClub": settings.max_per_club,
                    "unlimited": unlimited,
                    "hasSquad": False,
                    "ft": ft_state.free_transfers,
                    "hitCost": squad_svc.HIT_COST,
                },
                player_count=db.query(Player).count(),
                error=str(exc),
            ),
            status_code=400,
        )
    if wants_json:
        return JSONResponse({"ok": True, "saved": "squad", "player_ids": player_ids})
    if manager_has_complete_squad(db, manager.id):
        return RedirectResponse("/?notice=Squad+saved", status_code=303)
    return RedirectResponse("/team?notice=Squad+saved", status_code=303)


@router.post("/lineup/role")
async def lineup_role(request: Request, db: Session = Depends(get_db)):
    """JSON: move a squad player between XI and bench from the Squad detail sheet."""
    from app.services import deadline as deadline_svc

    manager = current_manager(request, db)
    if not manager:
        return JSONResponse({"error": "login"}, status_code=401)
    gw = squad_svc.current_gameweek(db)
    if not deadline_svc.can_edit(gw):
        return JSONResponse({"error": "Deadline passed"}, status_code=400)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "bad json"}, status_code=400)
    player_id = int(body.get("player_id") or 0)
    make_starter = bool(body.get("make_starter"))
    try:
        result = squad_svc.set_player_lineup_role(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            player_id=player_id,
            make_starter=make_starter,
        )
    except squad_svc.SquadError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, **result})


@router.get("/lineup", response_class=HTMLResponse)
def lineup_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    from app.services import chips as chips_svc

    try:
        view = _resolve_gw(request, db)
    except squad_svc.SquadError as exc:
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
    gw = view["gw"]
    squad_svc.bank_free_transfers(db, manager.id, view["current_gw"].number)
    chips_svc.restore_free_hits_if_needed(db, manager_id=manager.id, current_gw=view["current_gw"])
    owned = squad_svc.owned_players(db, manager.id)
    if len(owned) != settings.squad_size:
        return RedirectResponse("/onboard", status_code=303)
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == manager.id, SquadPick.gameweek_id == gw.id)
        .all()
    )
    starters = [p.player_id for p in picks if p.is_starter]
    captain = next((p.player_id for p in picks if p.is_captain), None)
    vice = next((p.player_id for p in picks if getattr(p, "is_vice_captain", 0)), None)
    if not starters:
        starters, _, captain, vice = squad_svc.default_lineup_from_owned(owned)
    if not vice or vice == captain:
        vice = next((s for s in starters if s != captain), captain)

    points_map: dict[str, float] = {}
    points_breakdown: dict[str, dict] = {}
    gw_total = None
    if view["edits_locked"]:
        from app.services.auto_score import maybe_score_locked_gw
        from app.models import ManagerGameweekScore, PlayerPoints
        import threading

        # Don't block navigation on scoring — refresh scores in the background.
        threading.Thread(target=lambda: maybe_score_locked_gw(), daemon=True).start()
        for row in (
            db.query(PlayerPoints)
            .filter(
                PlayerPoints.gameweek_id == gw.id,
                PlayerPoints.formula_version == settings.formula_version,
            )
            .all()
        ):
            points_map[str(row.player_id)] = float(row.total or 0)
            try:
                bd = json.loads(row.breakdown_json or "{}")
            except Exception:
                bd = {}
            if isinstance(bd, dict):
                points_breakdown[str(row.player_id)] = {
                    str(k): float(v or 0) for k, v in bd.items()
                }
        score = (
            db.query(ManagerGameweekScore)
            .filter(
                ManagerGameweekScore.manager_id == manager.id,
                ManagerGameweekScore.gameweek_id == gw.id,
            )
            .one_or_none()
        )
        if score:
            gw_total = float(score.total or 0)

    chips = chips_svc.ensure_chip_state(db, manager.id)
    active_chip = chips_svc.active_chip(db, manager.id, gw.id)
    starter_set = set(starters)
    bench_options = [p for p in owned if p.id not in starter_set]
    notice = request.query_params.get("notice")
    error = request.query_params.get("error") or request.query_params.get("chip_error")

    from app.services import deadline as deadline_svc
    from app.models import Fixture

    captain_editable = False
    if view["gw"].id == view["current_gw"].id:
        captain_editable = deadline_svc.can_edit_captain(view["current_gw"])
    # One query for the GW instead of per-club lookups.
    started_clubs: set[str] = set()
    for fx in db.query(Fixture).filter(Fixture.gameweek_number == gw.number).all():
        if fx.started or fx.finished:
            if fx.home_club_code:
                started_clubs.add(fx.home_club_code)
            if fx.away_club_code:
                started_clubs.add(fx.away_club_code)
    fixture_started = {p.id: p.team_code in started_clubs for p in owned}
    any_fixture_started = bool(started_clubs)
    # Don't show a GW total of 0 before any club has kicked off.
    if view["edits_locked"] and not any_fixture_started:
        gw_total = None
    armed = {
        p.player_id: bool(getattr(p, "captain_armed", 0))
        for p in picks
    }
    td_info = td_svc.td_view(db, manager.id, gw.number, gameweek_id=gw.id)
    super_sub_player_id = None
    if active_chip and active_chip.chip == "super_sub":
        try:
            ss_meta = json.loads(active_chip.meta_json or "{}")
            if ss_meta.get("player_id") is not None:
                super_sub_player_id = int(ss_meta["player_id"])
        except (json.JSONDecodeError, TypeError, ValueError):
            super_sub_player_id = None

    owned_by_id = {p.id: p for p in owned}
    captain_name = owned_by_id[captain].name if captain and captain in owned_by_id else None
    left_to_play = sum(
        1
        for pid in starters
        if pid in owned_by_id and owned_by_id[pid].team_code not in started_clubs
    )
    played_count = max(0, len(starters) - left_to_play)

    return templates.TemplateResponse(
        "lineup.html",
        _ctx(
            request,
            db,
            owned_json=_owned_payload(owned, db, gw_number=gw.number),
            initial_lineup={
                "starters": starters,
                "captain": captain,
                "vice": vice,
                "locked": view["edits_locked"],
                "captainEditable": captain_editable,
                "fixtureStarted": fixture_started,
                "captainArmed": armed,
                "gw": gw.number,
                "points": points_map,
                "breakdowns": points_breakdown,
                "gwTotal": gw_total,
                "activeChip": active_chip.chip if active_chip else None,
                "superSubPlayerId": super_sub_player_id,
            },
            spend=squad_svc.squad_spend(owned),
            gw_total=gw_total,
            any_fixture_started=any_fixture_started,
            captain_name=captain_name,
            left_to_play=left_to_play,
            played_count=played_count,
            chips=chips,
            active_chip=active_chip,
            bench_options=bench_options,
            captain_editable=captain_editable,
            td_info=td_info,
            notice=notice,
            error=error,
            **view,
        ),
    )


@router.post("/lineup/save")
async def lineup_save(request: Request, db: Session = Depends(get_db)):
    from urllib.parse import quote

    from app.services import deadline as deadline_svc

    wants_json = _wants_json(request)
    manager = current_manager(request, db)
    if not manager:
        if wants_json:
            return JSONResponse({"error": "login_required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    form = await request.form()
    roles_only = str(form.get("roles_only") or "") == "1"
    captain_id = int(form.get("captain_id") or 0)
    vice_id = int(form.get("vice_id") or 0)

    if roles_only:
        if not deadline_svc.can_edit_captain(gw):
            if wants_json:
                return JSONResponse({"error": "Captain changes are locked"}, status_code=400)
            return RedirectResponse("/lineup?error=Captain+changes+are+locked", status_code=303)
        try:
            squad_svc.save_captain_roles(
                db,
                manager_id=manager.id,
                gameweek_id=gw.id,
                gw_number=gw.number,
                captain_id=captain_id,
                vice_id=vice_id,
            )
        except squad_svc.SquadError as exc:
            if wants_json:
                return JSONResponse({"error": str(exc)}, status_code=400)
            return RedirectResponse(f"/lineup?error={quote(str(exc))}", status_code=303)
        from app.services.live_scoring import run_gameweek_scoring

        try:
            run_gameweek_scoring(db, gw, mode="auto")
        except Exception:
            pass
        if wants_json:
            return JSONResponse(
                {
                    "ok": True,
                    "saved": "captain",
                    "captain_id": captain_id,
                    "vice_id": vice_id,
                }
            )
        return RedirectResponse("/lineup?notice=Captain+updated", status_code=303)

    if not deadline_svc.can_edit(gw):
        if wants_json:
            return JSONResponse({"error": "Deadline passed — lineup is locked"}, status_code=400)
        return RedirectResponse("/lineup?error=Deadline+passed+—+lineup+is+locked", status_code=303)
    starter_ids = [int(x) for x in form.getlist("starter_id")]
    try:
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starter_ids,
            captain_id=captain_id,
            vice_id=vice_id,
        )
    except squad_svc.SquadError as exc:
        if wants_json:
            return JSONResponse({"error": str(exc)}, status_code=400)
        owned = squad_svc.owned_players(db, manager.id)
        return templates.TemplateResponse(
            "lineup.html",
            _ctx(
                request,
                db,
                owned_json=_owned_payload(owned, db, gw_number=gw.number),
                initial_lineup={
                    "starters": starter_ids,
                    "captain": captain_id or None,
                    "vice": vice_id or None,
                    "locked": False,
                    "gw": gw.number,
                    "points": {},
                },
                spend=squad_svc.squad_spend(owned),
                error=str(exc),
            ),
            status_code=400,
        )
    if wants_json:
        return JSONResponse(
            {
                "ok": True,
                "saved": "lineup",
                "starter_ids": starter_ids,
                "captain_id": captain_id,
                "vice_id": vice_id,
            }
        )
    return RedirectResponse("/lineup?notice=XI+saved", status_code=303)


@router.get("/transfers", response_class=HTMLResponse)
def transfers_page(request: Request, db: Session = Depends(get_db)):
    """Legacy URL — transfers happen on Squad pitch."""
    return RedirectResponse("/team", status_code=303)


@router.post("/transfers/make")
def transfers_make(
    request: Request,
    player_out_id: int = Form(...),
    player_in_id: int = Form(...),
    db: Session = Depends(get_db),
):
    from app.services import deadline as deadline_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        gw = squad_svc.current_gameweek(db)
    except squad_svc.SquadError as exc:
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
    if not deadline_svc.can_edit(gw):
        return RedirectResponse("/team?error=Deadline+passed+—+transfers+locked", status_code=303)
    try:
        before_hits = squad_svc.hit_transfers_this_gw(db, manager.id, gw.id)
        squad_svc.make_transfer(
            db,
            manager_id=manager.id,
            gameweek=gw,
            player_out_id=player_out_id,
            player_in_id=player_in_id,
        )
        after_hits = squad_svc.hit_transfers_this_gw(db, manager.id, gw.id)
    except squad_svc.SquadError as exc:
        return RedirectResponse(f"/team?error={quote(str(exc))}", status_code=303)
    if after_hits > before_hits:
        notice = quote(f"Transfer done (−{squad_svc.HIT_COST} hit).")
        return RedirectResponse(f"/team?ok=1&notice={notice}", status_code=303)
    return RedirectResponse("/team?ok=1", status_code=303)


@router.post("/sync/players")
def sync_players(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        info = sync_from_fpl(db)
        from app.services.player_catalog import clear_players_catalog_cache

        clear_players_catalog_cache()
        notice = f"Updated from FPL: {info['players']} players · current GW{info['current_gw']}"
    except Exception as exc:
        notice = None
        return templates.TemplateResponse(
            "home.html",
            _ctx(
                request,
                db,
                leagues=league_svc.manager_leagues(db, manager.id),
                formula_version=settings.formula_version,
                error=f"Sync failed: {exc}",
            ),
            status_code=400,
        )
    return templates.TemplateResponse(
        "home.html",
        _ctx(
            request,
            db,
            leagues=league_svc.manager_leagues(db, manager.id),
            formula_version=settings.formula_version,
            notice=notice,
        ),
    )


@router.get("/td", response_class=HTMLResponse)
def td_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        gw = squad_svc.current_gameweek(db)
    except squad_svc.SquadError as exc:
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
    pick = td_svc.current_td(db, manager.id, gw.number)
    clubs = db.query(Club).order_by(Club.name).all()
    can_set = td_svc.can_select_td(db, manager.id, gw.number)
    preview_start, preview_end = td_svc.window_for_start(gw.number)
    return templates.TemplateResponse(
        "td.html",
        _ctx(
            request,
            db,
            clubs=clubs,
            pick=pick,
            block_start=pick.start_gw if pick else preview_start,
            block_end=pick.end_gw if pick else preview_end,
            can_set=can_set,
        ),
    )


@router.post("/td/save")
def td_save(
    request: Request,
    club_code: str = Form(...),
    db: Session = Depends(get_db),
):
    from urllib.parse import quote

    from fastapi.responses import JSONResponse

    accept = (request.headers.get("accept") or "").lower()
    wants_json = (
        "application/json" in accept
        or request.query_params.get("format") == "json"
        or (request.headers.get("x-requested-with") or "").lower() == "fetch"
    )
    manager = current_manager(request, db)
    if not manager:
        if wants_json:
            return JSONResponse({"error": "login_required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    try:
        td_svc.set_td_pick(db, manager_id=manager.id, club_code=club_code, gw_number=gw.number)
    except td_svc.TDError as exc:
        if wants_json:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return RedirectResponse(f"/team?error={quote(str(exc))}", status_code=303)
    td_info = td_svc.td_view(db, manager.id, gw.number, gameweek_id=gw.id)
    if wants_json:
        payload = {
            k: v
            for k, v in td_info.items()
            if k != "pick" and not hasattr(v, "_sa_instance_state")
        }
        return JSONResponse({"ok": True, "td": payload})
    return RedirectResponse("/team?notice=Technical+Director+updated", status_code=303)


@router.post("/score/run")
def score_run(
    request: Request,
    db: Session = Depends(get_db),
    mode: str = Form("auto"),
):
    """Ingest FPL live (or demo if empty) and recompute manager/H2H points."""
    from app.services import live_scoring as live_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        summary = live_svc.run_gameweek_scoring(
            db,
            prefer_live=mode != "demo",
            force_demo=mode == "demo",
        )
    except Exception as exc:
        return RedirectResponse(f"/lineup?error={exc}", status_code=303)
    src = summary.get("ingest", {}).get("source", "?")
    notice = (
        f"GW{summary['gameweek']} scored · {summary['managers_scored']} managers · "
        f"{summary['players_scored']} players · {src}"
    )
    from urllib.parse import quote

    return RedirectResponse(f"/lineup?gw={summary['gameweek']}&notice={quote(notice)}", status_code=303)


@router.post("/demo/live-start")
def demo_live_start(request: Request, db: Session = Depends(get_db)):
    """Phone-test helper: lock current GW as live with fixtures + demo points."""
    from urllib.parse import quote

    from app.services import demo_live as demo_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        summary = demo_svc.start_live_demo(db, manager)
    except Exception as exc:
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
    gw = summary.get("gameweek")
    notice = f"Live GW{gw} demo ready — open XI / Fixtures on your phone."
    return RedirectResponse(f"/lineup?gw={gw}&notice={quote(notice)}", status_code=303)


@router.post("/demo/live-stop")
def demo_live_stop(request: Request, db: Session = Depends(get_db)):
    """Restore deadline + fixtures after a live GW demo session."""
    from urllib.parse import quote

    from app.services import demo_live as demo_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    try:
        summary = demo_svc.stop_live_demo(db)
    except Exception as exc:
        return RedirectResponse(f"/?error={quote(str(exc))}", status_code=303)
    if not summary.get("restored"):
        return RedirectResponse("/?notice=No+live+demo+was+active", status_code=303)
    return RedirectResponse("/?notice=Live+demo+ended+·+deadline+restored", status_code=303)


@router.get("/rules", response_class=HTMLResponse)
def rules_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse("rules.html", _ctx(request, db))


@router.get("/fixtures", response_class=HTMLResponse)
def fixtures_page(request: Request, db: Session = Depends(get_db)):
    """PL fixtures for a gameweek — live scores + tap for goals/assists."""
    from app.services import fixtures as fixtures_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    view = _resolve_gw(request, db)
    gw = view["gw"]
    fixtures_svc.ensure_fixtures_ready(db)
    owned = squad_svc.owned_players(db, manager.id)
    by_club = fixtures_svc.squad_by_club(owned)
    matches = fixtures_svc.enrich_fixtures_with_squad(
        fixtures_svc.fixtures_for_gameweek(db, gw_number=gw.number),
        by_club,
    )
    return templates.TemplateResponse(
        "fixtures.html",
        _ctx(
            request,
            db,
            matches=matches,
            match_count=len(matches),
            my_by_club=by_club,
            notice=request.query_params.get("notice"),
            error=request.query_params.get("error"),
            **view,
        ),
    )


@router.post("/fixtures/refresh")
def fixtures_refresh(request: Request, db: Session = Depends(get_db)):
    from app.services import fixtures as fixtures_svc
    from urllib.parse import quote

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    view = _resolve_gw(request, db)
    gw = view["gw"]
    try:
        info = fixtures_svc.refresh_fixtures(db)
        notice = quote(f"Updated {info.get('fixtures', 0)} fixtures from FPL")
        return RedirectResponse(f"/fixtures?gw={gw.number}&notice={notice}", status_code=303)
    except Exception as exc:
        return RedirectResponse(f"/fixtures?gw={gw.number}&error={exc}", status_code=303)


@router.get("/points", response_class=HTMLResponse)
def points_page(request: Request, db: Session = Depends(get_db)):
    """Legacy — live scores now live on Lineup after the deadline."""
    gw = request.query_params.get("gw")
    loc = f"/lineup?gw={gw}" if gw else "/lineup"
    return RedirectResponse(loc, status_code=303)


@router.get("/league/{league_id}/opponent/{manager_id}", response_class=HTMLResponse)
def h2h_opponent_peek(league_id: int, manager_id: int, request: Request, db: Session = Depends(get_db)):
    """Peek at another manager’s locked GW squad (classic + H2H scouting).

    Between gameweeks (before the next deadline), keep showing the last locked
    GW squad — transfer changes only appear once that next GW starts.
    """
    from app.kits import kit_for
    from app.models import Fixture, Manager, ManagerGameweekScore, PlayerPoints
    from app.services import fixtures as fixtures_svc
    from app.services.fpl_sync import availability_flag

    me = current_manager(request, db)
    if not me:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == me.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/", status_code=303)
    their_membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager_id)
        .one_or_none()
    )
    if not their_membership:
        return RedirectResponse(f"/standings/{league_id}", status_code=303)

    view = _resolve_gw(request, db)
    requested_gw = view["gw"]
    squad_gw = requested_gw
    squad_frozen = False
    # Pre-deadline on the viewed GW → freeze on previous locked GW squad
    if not view["edits_locked"] and requested_gw.id == view["current_gw"].id:
        prev = (
            db.query(Gameweek)
            .filter(Gameweek.number == requested_gw.number - 1)
            .one_or_none()
        )
        if prev:
            squad_gw = prev
            squad_frozen = True

    opponent = db.query(Manager).filter(Manager.id == manager_id).one()
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == opponent.id, SquadPick.gameweek_id == squad_gw.id)
        .all()
    )
    clubs = {c.code: c for c in db.query(Club).all()}
    player_ids = [p.player_id for p in picks]
    players = (
        db.query(Player).filter(Player.id.in_(player_ids)).all() if player_ids else []
    )
    by_id = {p.id: p for p in players}

    if not picks:
        owned = squad_svc.owned_players(db, opponent.id)
        by_id = {p.id: p for p in owned}
        starter_ids, _, _, _ = squad_svc.default_lineup_from_owned(owned)
        starter_ids = set(starter_ids)
        bench_ids = [p.id for p in owned if p.id not in starter_ids]
        picks_by_player: dict[int, SquadPick] = {}
    else:
        starter_ids = {p.player_id for p in picks if p.is_starter}
        bench_ids = [
            p.player_id
            for p in sorted(picks, key=lambda x: (x.bench_order or 99, x.player_id))
            if not p.is_starter
        ]
        picks_by_player = {p.player_id: p for p in picks}

    started_clubs: set[str] = set()
    for fx in db.query(Fixture).filter(Fixture.gameweek_number == squad_gw.number).all():
        if fx.started or fx.finished:
            if fx.home_club_code:
                started_clubs.add(fx.home_club_code)
            if fx.away_club_code:
                started_clubs.add(fx.away_club_code)

    points_map: dict[int, float] = {}
    for row in (
        db.query(PlayerPoints)
        .filter(
            PlayerPoints.gameweek_id == squad_gw.id,
            PlayerPoints.formula_version == settings.formula_version,
        )
        .all()
    ):
        points_map[row.player_id] = float(row.total or 0)

    fdr_by_club: dict[str, dict] = {}
    for match in fixtures_svc.fixtures_for_gameweek(db, gw_number=squad_gw.number):
        fdr_by_club[match["home"]["code"]] = {
            "opponent": match["away"]["code"],
            "venue": "H",
            "difficulty": match["home"]["difficulty"],
        }
        fdr_by_club[match["away"]["code"]] = {
            "opponent": match["home"]["code"],
            "venue": "A",
            "difficulty": match["away"]["difficulty"],
        }

    def pack(player: Player, on_bench: bool) -> dict:
        kit = kit_for(
            player.team_code,
            position=player.position,
            kit_code=getattr(clubs.get(player.team_code), "kit_code", None),
        )
        pick = picks_by_player.get(player.id)
        started = player.team_code in started_clubs
        pts = points_map.get(player.id) if started else None
        return {
            "player": player,
            "shirt": kit["shirt"],
            "is_captain": bool(pick and pick.is_captain),
            "is_vice": bool(pick and getattr(pick, "is_vice_captain", 0)),
            "on_bench": on_bench,
            "availability": availability_flag(
                getattr(player, "status", "a") or "a",
                getattr(player, "chance_of_playing", None),
            ),
            "fixture_started": started,
            "points": pts,
            "fdr": fdr_by_club.get(player.team_code),
        }

    by_pos = {"GK": [], "DEF": [], "MID": [], "ATT": []}
    for pid in starter_ids:
        p = by_id.get(pid)
        if p:
            by_pos[p.position].append(pack(p, False))
    bench = [pack(by_id[pid], True) for pid in bench_ids if pid in by_id]
    score = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.manager_id == opponent.id,
            ManagerGameweekScore.gameweek_id == squad_gw.id,
        )
        .one_or_none()
    )

    # Viewer's locked XI for desktop compare rail
    my_picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == me.id, SquadPick.gameweek_id == squad_gw.id)
        .all()
    )
    my_player_ids = [p.player_id for p in my_picks]
    my_players = (
        db.query(Player).filter(Player.id.in_(my_player_ids)).all() if my_player_ids else []
    )
    my_by_id = {p.id: p for p in my_players}
    my_starter_ids = {p.player_id for p in my_picks if p.is_starter}
    my_picks_by_player = {p.player_id: p for p in my_picks}

    def pack_mine(player: Player) -> dict:
        kit = kit_for(
            player.team_code,
            position=player.position,
            kit_code=getattr(clubs.get(player.team_code), "kit_code", None),
        )
        pick = my_picks_by_player.get(player.id)
        started = player.team_code in started_clubs
        pts = points_map.get(player.id) if started else None
        return {
            "name": player.name,
            "team": player.team_code,
            "pos": player.position,
            "shirt": kit["shirt"],
            "is_captain": bool(pick and pick.is_captain),
            "is_vice": bool(pick and getattr(pick, "is_vice_captain", 0)),
            "fixture_started": started,
            "points": pts,
        }

    my_starters = []
    for pid in my_starter_ids:
        p = my_by_id.get(pid)
        if p:
            my_starters.append(pack_mine(p))
    pos_order = {"GK": 0, "DEF": 1, "MID": 2, "ATT": 3}
    my_starters.sort(key=lambda r: (pos_order.get(r["pos"], 9), r["name"]))

    their_starters = []
    for pos in ("GK", "DEF", "MID", "ATT"):
        for row in by_pos[pos]:
            their_starters.append(
                {
                    "name": row["player"].name,
                    "team": row["player"].team_code,
                    "pos": row["player"].position,
                    "is_captain": row["is_captain"],
                    "is_vice": row["is_vice"],
                    "fixture_started": row["fixture_started"],
                    "points": row["points"],
                }
            )

    my_score = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.manager_id == me.id,
            ManagerGameweekScore.gameweek_id == squad_gw.id,
        )
        .one_or_none()
    )

    return templates.TemplateResponse(
        "opponent.html",
        _ctx(
            request,
            db,
            league=membership.league,
            opponent=opponent,
            by_pos=by_pos,
            bench_players=bench,
            score=score,
            squad_gw=squad_gw,
            squad_frozen=squad_frozen,
            any_fixture_started=bool(started_clubs),
            my_team_name=(me.team_name or "").strip() or "You",
            my_starters=my_starters,
            their_starters=their_starters,
            my_score=my_score,
            **view,
        ),
    )


@router.get("/standings/{league_id}", response_class=HTMLResponse)
def standings(league_id: int, request: Request, db: Session = Depends(get_db)):
    from app.services import standings as standings_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    membership = (
        db.query(Membership)
        .filter(Membership.league_id == league_id, Membership.manager_id == manager.id)
        .one_or_none()
    )
    if not membership:
        return RedirectResponse("/", status_code=303)
    league = membership.league
    gw = squad_svc.current_gameweek(db)
    fixtures = []
    if getattr(league, "league_type", "classic") == "h2h":
        rows, fixtures = standings_svc.h2h_standings(db, league, gw)
        mode = "h2h"
    else:
        rows = standings_svc.classic_standings(db, league, gw)
        mode = "classic"
    from datetime import datetime, timezone

    updated_label = datetime.now(timezone.utc).strftime("%A %d %b · %H:%M UTC")
    return templates.TemplateResponse(
        "standings.html",
        _ctx(
            request,
            db,
            league=league,
            rows=rows,
            fixtures=fixtures,
            mode=mode,
            me=manager,
            member_count=db.query(Membership).filter(Membership.league_id == league.id).count(),
            updated_label=updated_label,
        ),
    )
