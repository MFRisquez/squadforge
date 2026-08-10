"""HTML routes for the phone-friendly MVP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import current_manager, login_manager, logout_manager
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
    }


def _ctx(request: Request, db: Session, **extra):
    manager = current_manager(request, db)
    gw = None
    try:
        gw = squad_svc.current_gameweek(db)
    except Exception:
        pass
    leagues = league_svc.manager_leagues(db, manager.id) if manager else []
    data = {
        "request": request,
        "app_name": settings.app_name,
        "manager": manager,
        "gw": gw,
        "budget": settings.budget,
        "nav_leagues": leagues,
        "error": None,
        "notice": None,
    }
    data.update(extra)
    return data


def _players_payload(db: Session) -> list[dict]:
    from app.kits import kit_for
    from app.services import fixtures as fixtures_svc
    from app.services.fpl_sync import availability_flag

    clubs = {c.code: c for c in db.query(Club).all()}
    players = db.query(Player).order_by(Player.position, Player.price.desc()).all()
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
            ),
        }
        for p in players
    ]


def _owned_payload(players: list[Player], db: Session | None = None) -> list[dict]:
    from app.kits import kit_for
    from app.services.fpl_sync import availability_flag

    clubs: dict[str, Club] = {}
    if db is not None:
        clubs = {c.code: c for c in db.query(Club).all()}

    return [
        {
            "id": p.id,
            "name": p.name,
            "position": p.position,
            "team": p.team_code,
            "price": p.price,
            "status": getattr(p, "status", "a") or "a",
            "chance": getattr(p, "chance_of_playing", None),
            "news": getattr(p, "news", "") or "",
            "availability": availability_flag(
                getattr(p, "status", "a") or "a",
                getattr(p, "chance_of_playing", None),
            ),
            **kit_for(
                p.team_code,
                position=p.position,
                kit_code=getattr(clubs.get(p.team_code), "kit_code", None),
                photo=getattr(p, "photo", "") or "",
            ),
        }
        for p in players
    ]


@router.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    leagues = league_svc.manager_leagues(db, manager.id) if manager else []
    return templates.TemplateResponse(
        "home.html",
        _ctx(request, db, leagues=leagues, formula_version=settings.formula_version),
    )


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("login.html", _ctx(request, db))


@router.post("/login")
def login_submit(
    request: Request,
    display_name: str = Form(...),
    pin: str = Form(...),
    team_name: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        manager = league_svc.get_or_create_manager(db, display_name, pin, team_name)
    except league_svc.LeagueError as exc:
        return templates.TemplateResponse(
            "login.html",
            _ctx(request, db, error=str(exc)),
            status_code=400,
        )
    login_manager(request, manager)
    return RedirectResponse("/", status_code=303)


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
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    leagues = league_svc.manager_leagues(db, manager.id)
    return templates.TemplateResponse(
        "leagues.html",
        _ctx(request, db, leagues=leagues),
    )


@router.get("/league/{league_id}", response_class=HTMLResponse)
def league_home(league_id: int, request: Request, db: Session = Depends(get_db)):
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
    members = db.query(Membership).filter(Membership.league_id == league_id).all()
    chips = db.query(ChipState).filter(ChipState.manager_id == manager.id).one_or_none()
    even = len(members) % 2 == 0 and len(members) >= 2
    return templates.TemplateResponse(
        "league.html",
        _ctx(
            request,
            db,
            league=membership.league,
            members=members,
            chips=chips,
            even_members=even,
            member_count=len(members),
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
        members = db.query(Membership).filter(Membership.league_id == league_id).all()
        return templates.TemplateResponse(
            "league.html",
            _ctx(
                request,
                db,
                league=membership.league,
                members=members,
                error=str(exc),
                even_members=len(members) % 2 == 0 and len(members) >= 2,
                member_count=len(members),
            ),
            status_code=400,
        )
    return RedirectResponse(f"/standings/{league_id}", status_code=303)


@router.get("/team", response_class=HTMLResponse)
def team_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    from app.models import TransferLog
    from app.services import chips as chips_svc
    from app.services import td as td_svc

    view = _resolve_gw(request, db)
    gw = view["gw"]
    # Bank FTs + restore any expired Free Hit *before* reading ownership
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
    td = td_svc.current_td(db, manager.id, gw.number)
    can_set_td = td_svc.can_select_td(db, manager.id, gw.number) and not view["edits_locked"]
    clubs = db.query(Club).order_by(Club.name).all()
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
    return templates.TemplateResponse(
        "team.html",
        _ctx(
            request,
            db,
            owned=owned,
            spend=spend,
            pick_rows=pick_rows,
            chips=chips,
            active_chip=active_chip,
            bench_options=bench_options,
            td=td,
            can_set_td=can_set_td,
            clubs=clubs,
            ft_left=ft_state.free_transfers,
            unlimited_transfers=unlimited,
            transfers_gw=transfers_gw,
            hits_gw=hits_gw,
            hit_cost=squad_svc.HIT_COST,
            players_json=_players_payload(db),
            initial_squad={
                "selected": [p.id for p in owned],
                "budget": settings.budget,
                "maxPerClub": settings.max_per_club,
                "unlimited": unlimited and not view["edits_locked"],
                "hasSquad": len(owned) == settings.squad_size,
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
            notice=(
                request.query_params.get("notice")
                or ("Transfer done." if request.query_params.get("ok") else None)
                or ("Chip played." if request.query_params.get("chip_ok") else None)
            ),
            **view,
        ),
    )


@router.post("/team/chip")
def play_chip_from_squad(
    request: Request,
    chip: str = Form(...),
    player_id: Optional[int] = Form(None),
    db: Session = Depends(get_db),
):
    from app.services import chips as chips_svc
    from app.services.chips import ChipError

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    try:
        chips_svc.play_chip(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            chip=chip,
            player_id=player_id,
        )
    except ChipError as exc:
        return RedirectResponse(f"/team?chip_error={exc}", status_code=303)
    return RedirectResponse("/team?chip_ok=1", status_code=303)


@router.post("/team/chip/cancel")
def cancel_chip_from_squad(request: Request, db: Session = Depends(get_db)):
    from app.services import chips as chips_svc
    from app.services.chips import ChipError

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    try:
        chips_svc.cancel_chip(db, manager_id=manager.id, gameweek_id=gw.id)
    except ChipError as exc:
        return RedirectResponse(f"/team?chip_error={exc}", status_code=303)
    return RedirectResponse("/team?chip_ok=1", status_code=303)


@router.get("/team/edit", response_class=HTMLResponse)
def team_edit(request: Request, db: Session = Depends(get_db)):
    """Legacy URL — Squad & Transfers lives on /team."""
    return RedirectResponse("/team", status_code=303)


@router.post("/team/save")
async def team_save(request: Request, db: Session = Depends(get_db)):
    from app.services import deadline as deadline_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    if not deadline_svc.can_edit(gw):
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
                players_json=_players_payload(db),
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
    return RedirectResponse("/lineup", status_code=303)


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

    view = _resolve_gw(request, db)
    gw = view["gw"]
    squad_svc.bank_free_transfers(db, manager.id, view["current_gw"].number)
    chips_svc.restore_free_hits_if_needed(db, manager_id=manager.id, current_gw=view["current_gw"])
    owned = squad_svc.owned_players(db, manager.id)
    if len(owned) != settings.squad_size:
        return RedirectResponse("/team", status_code=303)
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
    gw_total = None
    if view["edits_locked"]:
        from app.services.auto_score import maybe_score_locked_gw
        from app.models import ManagerGameweekScore, PlayerPoints

        maybe_score_locked_gw()
        for row in (
            db.query(PlayerPoints)
            .filter(
                PlayerPoints.gameweek_id == gw.id,
                PlayerPoints.formula_version == settings.formula_version,
            )
            .all()
        ):
            points_map[str(row.player_id)] = float(row.total or 0)
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

    return templates.TemplateResponse(
        "lineup.html",
        _ctx(
            request,
            db,
            owned_json=_owned_payload(owned, db),
            initial_lineup={
                "starters": starters,
                "captain": captain,
                "vice": vice,
                "locked": view["edits_locked"],
                "gw": gw.number,
                "points": points_map,
            },
            spend=squad_svc.squad_spend(owned),
            gw_total=gw_total,
            notice=request.query_params.get("notice"),
            error=request.query_params.get("error"),
            **view,
        ),
    )


@router.post("/lineup/save")
async def lineup_save(request: Request, db: Session = Depends(get_db)):
    from app.services import deadline as deadline_svc

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    if not deadline_svc.can_edit(gw):
        return RedirectResponse("/lineup?error=Deadline+passed+—+lineup+is+locked", status_code=303)
    form = await request.form()
    starter_ids = [int(x) for x in form.getlist("starter_id")]
    captain_id = int(form.get("captain_id") or 0)
    vice_id = int(form.get("vice_id") or 0)
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
        owned = squad_svc.owned_players(db, manager.id)
        return templates.TemplateResponse(
            "lineup.html",
            _ctx(
                request,
                db,
                owned_json=_owned_payload(owned, db),
                initial_lineup={
                    "starters": starter_ids,
                    "captain": captain_id or None,
                    "vice": vice_id or None,
                },
                spend=squad_svc.squad_spend(owned),
                error=str(exc),
            ),
            status_code=400,
        )
    return RedirectResponse("/team", status_code=303)


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
    gw = squad_svc.current_gameweek(db)
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
        return RedirectResponse(f"/team?error={exc}", status_code=303)
    if after_hits > before_hits:
        from urllib.parse import quote

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
    gw = squad_svc.current_gameweek(db)
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
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    try:
        td_svc.set_td_pick(db, manager_id=manager.id, club_code=club_code, gw_number=gw.number)
    except td_svc.TDError as exc:
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
                error=str(exc),
            ),
            status_code=400,
        )
    return RedirectResponse("/td", status_code=303)


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
    matches = fixtures_svc.fixtures_for_gameweek(db, gw_number=gw.number)
    return templates.TemplateResponse(
        "fixtures.html",
        _ctx(
            request,
            db,
            matches=matches,
            match_count=len(matches),
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
    """Peek at another manager’s GW lineup (H2H scouting)."""
    from app.kits import kit_for
    from app.models import Manager, ManagerGameweekScore
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
    gw = view["gw"]
    opponent = db.query(Manager).filter(Manager.id == manager_id).one()
    owned = squad_svc.owned_players(db, opponent.id)
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == opponent.id, SquadPick.gameweek_id == gw.id)
        .all()
    )
    clubs = {c.code: c for c in db.query(Club).all()}
    by_id = {p.id: p for p in owned}
    starter_ids = {p.player_id for p in picks if p.is_starter}
    if not starter_ids and owned:
        starter_ids, _, _, _ = squad_svc.default_lineup_from_owned(owned)
        starter_ids = set(starter_ids)

    def pack(player: Player, on_bench: bool) -> dict:
        kit = kit_for(
            player.team_code,
            position=player.position,
            kit_code=getattr(clubs.get(player.team_code), "kit_code", None),
        )
        pick = next((x for x in picks if x.player_id == player.id), None)
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
        }

    by_pos = {"GK": [], "DEF": [], "MID": [], "ATT": []}
    for pid in starter_ids:
        p = by_id.get(pid)
        if p:
            by_pos[p.position].append(pack(p, False))
    bench = [pack(p, True) for p in owned if p.id not in starter_ids]
    score = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.manager_id == opponent.id,
            ManagerGameweekScore.gameweek_id == gw.id,
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
        ),
    )
