"""HTML routes for the phone-friendly MVP."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.auth import current_manager, login_manager, logout_manager
from app.config import settings
from app.db import get_db
from app.models import ChipState, Club, Membership, Player, SquadPick
from app.services import league as league_svc
from app.services import squad as squad_svc
from app.services import td as td_svc
from app.services.fpl_sync import sync_from_fpl
from app.services.seed import seed_if_empty

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "web" / "templates"))


def _ctx(request: Request, db: Session, **extra):
    manager = current_manager(request, db)
    gw = None
    try:
        gw = squad_svc.current_gameweek(db)
    except Exception:
        pass
    data = {
        "request": request,
        "app_name": settings.app_name,
        "manager": manager,
        "gw": gw,
        "budget": settings.budget,
        "error": None,
        "notice": None,
    }
    data.update(extra)
    return data


def _players_payload(db: Session) -> list[dict]:
    from app.services.fpl_sync import availability_flag

    players = db.query(Player).order_by(Player.position, Player.price.desc()).all()
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
        }
        for p in players
    ]


def _owned_payload(players: list[Player]) -> list[dict]:
    from app.services.fpl_sync import availability_flag

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
    from app.models import ChipPlay, TransferLog
    from app.services import chips as chips_svc
    from app.services import td as td_svc

    gw = squad_svc.current_gameweek(db)
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
    active_chip = (
        db.query(ChipPlay)
        .filter(ChipPlay.manager_id == manager.id, ChipPlay.gameweek_id == gw.id)
        .one_or_none()
    )
    td = td_svc.current_td(db, manager.id, gw.number)
    can_set_td = td_svc.can_select_td(db, manager.id, gw.number)
    clubs = db.query(Club).order_by(Club.name).all()
    ft_state = squad_svc.bank_free_transfers(db, manager.id, gw.number)
    unlimited = squad_svc.transfers_are_unlimited(db, manager.id, gw)
    transfers_gw = (
        db.query(TransferLog)
        .filter(TransferLog.manager_id == manager.id, TransferLog.gameweek_id == gw.id)
        .count()
    )
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
            td=td,
            can_set_td=can_set_td,
            clubs=clubs,
            ft_left=ft_state.free_transfers,
            unlimited_transfers=unlimited,
            transfers_gw=transfers_gw,
        ),
    )


@router.post("/team/chip")
def play_chip_from_squad(
    request: Request,
    chip: str = Form(...),
    db: Session = Depends(get_db),
):
    """Play a GW chip from the main squad sheet (Wildcard for now; others reserved)."""
    from app.services import chips as chips_svc
    from app.services.chips import ChipError

    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    try:
        if chip == "wildcard":
            chips_svc.play_wildcard(db, manager_id=manager.id, gameweek_id=gw.id)
        else:
            raise ChipError("That chip UI is next — Wildcard is available now")
    except ChipError as exc:
        return RedirectResponse(f"/team?chip_error={exc}", status_code=303)
    return RedirectResponse("/team?chip_ok=1", status_code=303)


@router.get("/team/edit", response_class=HTMLResponse)
def team_edit(request: Request, db: Session = Depends(get_db)):
    """Pick the fixed 15: 2 GK, 5 DEF, 5 MID, 3 ATT."""
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    owned = squad_svc.owned_players(db, manager.id)
    clubs = db.query(Club).order_by(Club.name).all()
    selected = [p.id for p in owned]
    return templates.TemplateResponse(
        "team_edit.html",
        _ctx(
            request,
            db,
            players_json=_players_payload(db),
            clubs=clubs,
            initial_squad={"selected": selected, "budget": settings.budget},
            player_count=db.query(Player).count(),
        ),
    )


@router.post("/team/save")
async def team_save(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    player_ids = [int(x) for x in form.getlist("player_id")]
    gw = squad_svc.current_gameweek(db)
    try:
        squad_svc.save_ownership(db, manager_id=manager.id, player_ids=player_ids, gw_number=gw.number)
        owned = squad_svc.owned_players(db, manager.id)
        starters, _all, captain = squad_svc.default_lineup_from_owned(owned)
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starters,
            captain_id=captain,
        )
    except squad_svc.SquadError as exc:
        clubs = db.query(Club).order_by(Club.name).all()
        return templates.TemplateResponse(
            "team_edit.html",
            _ctx(
                request,
                db,
                players_json=_players_payload(db),
                clubs=clubs,
                initial_squad={"selected": player_ids, "budget": settings.budget},
                player_count=db.query(Player).count(),
                error=str(exc),
            ),
            status_code=400,
        )
    return RedirectResponse("/lineup", status_code=303)


@router.get("/lineup", response_class=HTMLResponse)
def lineup_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    owned = squad_svc.owned_players(db, manager.id)
    if len(owned) != settings.squad_size:
        return RedirectResponse("/team/edit", status_code=303)
    gw = squad_svc.current_gameweek(db)
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == manager.id, SquadPick.gameweek_id == gw.id)
        .all()
    )
    starters = [p.player_id for p in picks if p.is_starter]
    captain = next((p.player_id for p in picks if p.is_captain), None)
    if not starters:
        starters, _, captain = squad_svc.default_lineup_from_owned(owned)
    return templates.TemplateResponse(
        "lineup.html",
        _ctx(
            request,
            db,
            owned_json=_owned_payload(owned),
            initial_lineup={"starters": starters, "captain": captain},
            spend=squad_svc.squad_spend(owned),
        ),
    )


@router.post("/lineup/save")
async def lineup_save(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    form = await request.form()
    starter_ids = [int(x) for x in form.getlist("starter_id")]
    captain_id = int(form.get("captain_id") or 0)
    gw = squad_svc.current_gameweek(db)
    try:
        squad_svc.save_lineup(
            db,
            manager_id=manager.id,
            gameweek_id=gw.id,
            starter_ids=starter_ids,
            captain_id=captain_id,
        )
    except squad_svc.SquadError as exc:
        owned = squad_svc.owned_players(db, manager.id)
        return templates.TemplateResponse(
            "lineup.html",
            _ctx(
                request,
                db,
                owned_json=_owned_payload(owned),
                initial_lineup={"starters": starter_ids, "captain": captain_id or None},
                spend=squad_svc.squad_spend(owned),
                error=str(exc),
            ),
            status_code=400,
        )
    return RedirectResponse("/team", status_code=303)


@router.get("/transfers", response_class=HTMLResponse)
def transfers_page(request: Request, db: Session = Depends(get_db)):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    state = squad_svc.bank_free_transfers(db, manager.id, gw.number)
    owned = squad_svc.owned_players(db, manager.id)
    if len(owned) != settings.squad_size:
        return RedirectResponse("/team/edit", status_code=303)
    unlimited = squad_svc.transfers_are_unlimited(db, manager.id, gw)
    clubs = db.query(Club).order_by(Club.name).all()
    return templates.TemplateResponse(
        "transfers.html",
        _ctx(
            request,
            db,
            owned=owned,
            owned_json=_owned_payload(owned),
            players_json=_players_payload(db),
            clubs=clubs,
            ft=state.free_transfers,
            unlimited=unlimited,
            spend=squad_svc.squad_spend(owned),
        ),
    )


@router.post("/transfers/make")
def transfers_make(
    request: Request,
    player_out_id: int = Form(...),
    player_in_id: int = Form(...),
    db: Session = Depends(get_db),
):
    manager = current_manager(request, db)
    if not manager:
        return RedirectResponse("/login", status_code=303)
    gw = squad_svc.current_gameweek(db)
    try:
        squad_svc.make_transfer(
            db,
            manager_id=manager.id,
            gameweek=gw,
            player_out_id=player_out_id,
            player_in_id=player_in_id,
        )
    except squad_svc.SquadError as exc:
        state = squad_svc.bank_free_transfers(db, manager.id, gw.number)
        owned = squad_svc.owned_players(db, manager.id)
        unlimited = squad_svc.transfers_are_unlimited(db, manager.id, gw)
        clubs = db.query(Club).order_by(Club.name).all()
        return templates.TemplateResponse(
            "transfers.html",
            _ctx(
                request,
                db,
                owned=owned,
                owned_json=_owned_payload(owned),
                players_json=_players_payload(db),
                clubs=clubs,
                ft=state.free_transfers,
                unlimited=unlimited,
                spend=squad_svc.squad_spend(owned),
                error=str(exc),
            ),
            status_code=400,
        )
    return RedirectResponse("/transfers?ok=1", status_code=303)


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
            member_count=db.query(Membership).filter(Membership.league_id == league.id).count(),
        ),
    )
