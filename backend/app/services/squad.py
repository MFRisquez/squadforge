"""Ownership (15), lineup (XI), and transfers with free-transfer banking."""

from __future__ import annotations

from collections import Counter
from typing import Iterable

from sqlalchemy.orm import Session

from app.config import settings
from app.models import (
    ChipPlay,
    Gameweek,
    OwnedPlayer,
    Player,
    SquadPick,
    TransferLog,
    TransferState,
)

REQUIRED = {"GK": 2, "DEF": 5, "MID": 5, "ATT": 3}
STARTER_BANDS = {"DEF": (3, 5), "MID": (3, 5), "ATT": (1, 3)}
FT_CAP = 5
HIT_COST = 4  # FPL-style points deducted per transfer beyond free allowance


class SquadError(ValueError):
    pass


def current_gameweek(db: Session) -> Gameweek:
    gw = db.query(Gameweek).filter(Gameweek.is_current == 1).one_or_none()
    if not gw:
        gw = db.query(Gameweek).order_by(Gameweek.number).first()
    if not gw:
        raise SquadError("No gameweeks seeded")
    return gw


def get_transfer_state(db: Session, manager_id: int) -> TransferState:
    state = db.query(TransferState).filter(TransferState.manager_id == manager_id).one_or_none()
    if state:
        return state
    state = TransferState(manager_id=manager_id, free_transfers=1, last_banked_gw=1, has_squad=0)
    db.add(state)
    db.commit()
    db.refresh(state)
    return state


def bank_free_transfers(db: Session, manager_id: int, gw_number: int) -> TransferState:
    """Each new GW after GW1 adds +1 FT (cumulative, capped)."""
    from app.services import chips as chips_svc

    state = get_transfer_state(db, manager_id)
    if gw_number <= 1:
        state.last_banked_gw = max(state.last_banked_gw, 1)
        db.commit()
        return state
    while state.last_banked_gw < gw_number:
        state.last_banked_gw += 1
        if state.last_banked_gw >= 2:
            state.free_transfers = min(FT_CAP, state.free_transfers + 1)
    db.commit()
    db.refresh(state)
    # After rolling into a new GW, restore any expired Free Hit squads
    current = db.query(Gameweek).filter(Gameweek.number == gw_number).one_or_none()
    if current:
        chips_svc.restore_free_hits_if_needed(db, manager_id=manager_id, current_gw=current)
    return state


def transfers_are_unlimited(db: Session, manager_id: int, gw: Gameweek) -> bool:
    """GW1 = unlimited. Wildcard/Free Hit active this GW = unlimited. No squad yet = unlimited build."""
    state = get_transfer_state(db, manager_id)
    if not state.has_squad:
        return True
    if gw.number <= 1:
        return True
    chip = (
        db.query(ChipPlay)
        .filter(
            ChipPlay.manager_id == manager_id,
            ChipPlay.gameweek_id == gw.id,
            ChipPlay.chip.in_(("wildcard", "free_hit")),
        )
        .one_or_none()
    )
    return chip is not None


def hit_transfers_this_gw(db: Session, manager_id: int, gameweek_id: int) -> int:
    return (
        db.query(TransferLog)
        .filter(
            TransferLog.manager_id == manager_id,
            TransferLog.gameweek_id == gameweek_id,
            TransferLog.is_hit == 1,
        )
        .count()
    )


def transfer_hit_points(db: Session, manager_id: int, gameweek_id: int) -> float:
    """Negative points from paid transfers this GW (−4 each)."""
    return float(-HIT_COST * hit_transfers_this_gw(db, manager_id, gameweek_id))


def owned_players(db: Session, manager_id: int) -> list[Player]:
    rows = db.query(OwnedPlayer).filter(OwnedPlayer.manager_id == manager_id).all()
    if not rows:
        return []
    ids = [r.player_id for r in rows]
    players = db.query(Player).filter(Player.id.in_(ids)).all()
    order = {i: n for n, i in enumerate(ids)}
    return sorted(players, key=lambda p: order.get(p.id, 0))


def validate_composition(players: list[Player]) -> None:
    if len(players) != settings.squad_size:
        raise SquadError(f"Need exactly {settings.squad_size} players")
    counts = Counter(p.position for p in players)
    for pos, need in REQUIRED.items():
        if counts.get(pos, 0) != need:
            raise SquadError(f"Need {need} {pos}, got {counts.get(pos, 0)}")
    club_counts = Counter(p.team_code for p in players)
    for club, n in club_counts.items():
        if n > settings.max_per_club:
            raise SquadError(f"Max {settings.max_per_club} from {club}")
    spend = sum(p.price for p in players)
    if spend > settings.budget + 1e-6:
        raise SquadError(f"Over budget: £{spend:.1f}m / £{settings.budget:.1f}m")


def validate_starter_shape(starter_counts: Counter) -> None:
    if starter_counts.get("GK", 0) != 1:
        raise SquadError("Starting XI must include exactly 1 GK")
    outfield = sum(starter_counts.get(pos, 0) for pos in ("DEF", "MID", "ATT"))
    if outfield != 10:
        raise SquadError("Starting XI needs 10 outfield players")
    for pos, (lo, hi) in STARTER_BANDS.items():
        n = starter_counts.get(pos, 0)
        if n < lo or n > hi:
            raise SquadError(f"Starters need {lo}–{hi} {pos} (have {n})")


def save_ownership(db: Session, *, manager_id: int, player_ids: list[int], gw_number: int) -> None:
    if len(set(player_ids)) != len(player_ids):
        raise SquadError("Duplicate players")
    players = db.query(Player).filter(Player.id.in_(player_ids)).all()
    if len(players) != len(player_ids):
        raise SquadError("Unknown player in squad")
    validate_composition(players)

    db.query(OwnedPlayer).filter(OwnedPlayer.manager_id == manager_id).delete()
    for pid in player_ids:
        db.add(OwnedPlayer(manager_id=manager_id, player_id=pid, acquired_gw=gw_number))
    state = get_transfer_state(db, manager_id)
    state.has_squad = 1
    db.commit()


def default_lineup_from_owned(players: list[Player]) -> tuple[list[int], list[int], int, int]:
    """Pick a legal default XI + bench order from owned 15. Returns starters, all, captain, vice."""
    by_pos: dict[str, list[Player]] = {"GK": [], "DEF": [], "MID": [], "ATT": []}
    for p in sorted(players, key=lambda x: -x.price):
        by_pos[p.position].append(p)
    # Prefer 3-4-3 / 3-5-2 style: 1 GK, 3 DEF, 4 MID, 3 ATT if possible
    starters: list[Player] = []
    starters += by_pos["GK"][:1]
    starters += by_pos["DEF"][:3]
    starters += by_pos["MID"][:4]
    starters += by_pos["ATT"][:3]
    if len(starters) != 11:
        # fallback fill
        starters = by_pos["GK"][:1] + by_pos["DEF"][:4] + by_pos["MID"][:4] + by_pos["ATT"][:2]
    starter_ids = [p.id for p in starters]
    bench = [p.id for p in players if p.id not in starter_ids]
    captain = starter_ids[-1]
    vice = starter_ids[-2] if len(starter_ids) > 1 else starter_ids[0]
    if vice == captain and len(starter_ids) > 1:
        vice = starter_ids[0]
    return starter_ids, [p.id for p in players], captain, vice


def effective_captain_id(
    captain_id: int,
    vice_id: int | None,
    minutes_by_player: dict[int, float],
) -> int:
    """If captain plays 0 minutes, armband passes to vice-captain (FPL-style)."""
    cap_mins = minutes_by_player.get(captain_id, 0) or 0
    if cap_mins > 0:
        return captain_id
    if vice_id and (minutes_by_player.get(vice_id, 0) or 0) > 0:
        return vice_id
    return captain_id


def save_lineup(
    db: Session,
    *,
    manager_id: int,
    gameweek_id: int,
    starter_ids: list[int],
    captain_id: int,
    vice_id: int,
) -> None:
    owned = owned_players(db, manager_id)
    if len(owned) != settings.squad_size:
        raise SquadError("Save your 15 players first")
    owned_ids = {p.id for p in owned}
    if captain_id not in starter_ids:
        raise SquadError("Captain must start")
    if vice_id not in starter_ids:
        raise SquadError("Vice-captain must start")
    if captain_id == vice_id:
        raise SquadError("Captain and vice-captain must be different")
    if len(starter_ids) != 11:
        raise SquadError("Need exactly 11 starters")
    if any(pid not in owned_ids for pid in starter_ids):
        raise SquadError("Starters must be in your squad")

    by_id = {p.id: p for p in owned}
    validate_starter_shape(Counter(by_id[i].position for i in starter_ids))

    bench = [p.id for p in owned if p.id not in starter_ids]
    db.query(SquadPick).filter(
        SquadPick.manager_id == manager_id,
        SquadPick.gameweek_id == gameweek_id,
    ).delete()
    for pid in owned_ids:
        is_starter = 1 if pid in starter_ids else 0
        db.add(
            SquadPick(
                manager_id=manager_id,
                gameweek_id=gameweek_id,
                player_id=pid,
                is_captain=1 if pid == captain_id else 0,
                is_vice_captain=1 if pid == vice_id else 0,
                is_starter=is_starter,
                bench_order=(bench.index(pid) + 1) if not is_starter else 0,
            )
        )
    db.commit()


def set_player_lineup_role(
    db: Session,
    *,
    manager_id: int,
    gameweek_id: int,
    player_id: int,
    make_starter: bool,
) -> dict:
    """Move one owned player between XI and bench, keeping a legal formation."""
    owned = owned_players(db, manager_id)
    if len(owned) != settings.squad_size:
        raise SquadError("Save your 15 players first")
    by_id = {p.id: p for p in owned}
    if player_id not in by_id:
        raise SquadError("Player not in your squad")

    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == manager_id, SquadPick.gameweek_id == gameweek_id)
        .all()
    )
    if not picks:
        starters, _, captain, vice = default_lineup_from_owned(owned)
    else:
        starters = [p.player_id for p in picks if p.is_starter]
        captain = next((p.player_id for p in picks if p.is_captain), None) or starters[0]
        vice = next((p.player_id for p in picks if getattr(p, "is_vice_captain", 0)), None)
        if not vice or vice == captain:
            vice = next((s for s in starters if s != captain), captain)

    starter_set = set(starters)
    is_starter = player_id in starter_set
    if make_starter and is_starter:
        return {"starters": starters, "captain": captain, "vice": vice, "changed": False}
    if (not make_starter) and (not is_starter):
        return {"starters": starters, "captain": captain, "vice": vice, "changed": False}

    if make_starter:
        if len(starter_set) >= 11:
            # swap with cheapest same-position starter if possible, else cheapest starter
            player = by_id[player_id]
            candidates = [
                sid
                for sid in starters
                if by_id[sid].position == player.position and sid != captain and sid != vice
            ]
            if not candidates:
                candidates = [sid for sid in starters if sid != captain and sid != vice]
            if not candidates:
                raise SquadError("Can't move into XI — adjust captain/vice first")
            drop = sorted(candidates, key=lambda sid: by_id[sid].price)[0]
            starter_set.remove(drop)
        starter_set.add(player_id)
    else:
        if player_id == captain or player_id == vice:
            raise SquadError("Clear captain/vice first (or move another starter in)")
        if len(starter_set) <= 11:
            # need a bench player to promote — prefer same position
            player = by_id[player_id]
            bench = [pid for pid in by_id if pid not in starter_set]
            promote = next((pid for pid in bench if by_id[pid].position == player.position), None)
            if promote is None:
                # any bench that keeps shape valid after swap
                promote = None
                for pid in bench:
                    trial = (starter_set - {player_id}) | {pid}
                    try:
                        validate_starter_shape(Counter(by_id[i].position for i in trial))
                        promote = pid
                        break
                    except SquadError:
                        continue
            if promote is None:
                raise SquadError("No legal bench swap for that move")
            starter_set.remove(player_id)
            starter_set.add(promote)

    new_starters = list(starter_set)
    if captain not in starter_set:
        captain = new_starters[-1]
    if vice not in starter_set or vice == captain:
        vice = next((s for s in new_starters if s != captain), captain)
    validate_starter_shape(Counter(by_id[i].position for i in new_starters))
    save_lineup(
        db,
        manager_id=manager_id,
        gameweek_id=gameweek_id,
        starter_ids=new_starters,
        captain_id=captain,
        vice_id=vice,
    )
    return {"starters": new_starters, "captain": captain, "vice": vice, "changed": True}


def make_transfer(
    db: Session,
    *,
    manager_id: int,
    gameweek: Gameweek,
    player_out_id: int,
    player_in_id: int,
) -> TransferState:
    if player_out_id == player_in_id:
        raise SquadError("Choose different players")

    state = bank_free_transfers(db, manager_id, gameweek.number)
    owned = owned_players(db, manager_id)
    owned_ids = {p.id for p in owned}
    if player_out_id not in owned_ids:
        raise SquadError("You don't own that player")
    if player_in_id in owned_ids:
        raise SquadError("You already own the incoming player")

    incoming = db.query(Player).filter(Player.id == player_in_id).one_or_none()
    if not incoming:
        raise SquadError("Incoming player not found")

    new_ids = [pid for pid in owned_ids if pid != player_out_id] + [player_in_id]
    players = db.query(Player).filter(Player.id.in_(new_ids)).all()
    validate_composition(players)

    unlimited = transfers_are_unlimited(db, manager_id, gameweek)
    is_hit = 0
    if not unlimited:
        if state.free_transfers >= 1:
            state.free_transfers -= 1
        else:
            is_hit = 1

    # Apply ownership change
    db.query(OwnedPlayer).filter(
        OwnedPlayer.manager_id == manager_id,
        OwnedPlayer.player_id == player_out_id,
    ).delete()
    db.add(OwnedPlayer(manager_id=manager_id, player_id=player_in_id, acquired_gw=gameweek.number))
    db.add(
        TransferLog(
            manager_id=manager_id,
            gameweek_id=gameweek.id,
            player_out_id=player_out_id,
            player_in_id=player_in_id,
            free_transfers_after=state.free_transfers,
            is_hit=is_hit,
        )
    )
    db.commit()

    # Keep lineup valid: drop out-player from XI if present, auto-put in-player on bench
    picks = (
        db.query(SquadPick)
        .filter(SquadPick.manager_id == manager_id, SquadPick.gameweek_id == gameweek.id)
        .all()
    )
    if picks:
        out_pick = next((p for p in picks if p.player_id == player_out_id), None)
        was_starter = bool(out_pick and out_pick.is_starter)
        was_captain = bool(out_pick and out_pick.is_captain)
        was_vice = bool(out_pick and getattr(out_pick, "is_vice_captain", 0))
        if out_pick:
            db.delete(out_pick)
        db.add(
            SquadPick(
                manager_id=manager_id,
                gameweek_id=gameweek.id,
                player_id=player_in_id,
                is_captain=0,
                is_vice_captain=0,
                is_starter=0,
                bench_order=4,
            )
        )
        db.commit()
        if was_starter:
            # Force manager to fix lineup — auto-start the new player in same role if possible
            remaining = (
                db.query(SquadPick)
                .filter(SquadPick.manager_id == manager_id, SquadPick.gameweek_id == gameweek.id)
                .all()
            )
            starters = [p.player_id for p in remaining if p.is_starter]
            if len(starters) == 10:
                in_pick = next(p for p in remaining if p.player_id == player_in_id)
                in_pick.is_starter = 1
                in_pick.bench_order = 0
                if was_captain:
                    for p in remaining:
                        p.is_captain = 1 if p.player_id == player_in_id else 0
                if was_vice:
                    for p in remaining:
                        p.is_vice_captain = 1 if p.player_id == player_in_id else 0
                db.commit()
    return state


def squad_spend(players: Iterable[Player]) -> float:
    return sum(p.price for p in players)
