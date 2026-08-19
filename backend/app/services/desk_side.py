"""Desktop left-rail payloads for XI / Transfers (cached, batched)."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    Gameweek,
    League,
    ManagerGameweekScore,
    Membership,
    OwnedPlayer,
    Player,
    SquadPick,
    TransferLog,
)
from app.services import deadline as deadline_svc
from app.services import standings as standings_svc
from app.services import td as td_svc

# Same idea as player_catalog FDR TTL — avoid rebuilding standings on every soft-nav.
_RANK_TTL = 45.0
# (league_id, gw_id) -> (monotonic_ts, {manager_id: card_fields})
_RANK_CACHE: dict[tuple[int, int], tuple[float, dict[int, dict[str, Any]]]] = {}

# Top scorers while-owned: longer TTL — walk TransferLog + scores is heavier.
_TOP_SCORERS_TTL = 180.0
# (manager_id, current_gw_id) -> (monotonic_ts, top rows)
_TOP_SCORERS_CACHE: dict[tuple[int, int], tuple[float, list[dict[str, Any]]]] = {}

# League XI share / captain aggregates — same TTL window as ranks.
_LEAGUE_XI_TTL = 45.0
# (league_id, gw_id, kind) -> (monotonic_ts, payload)
_LEAGUE_XI_CACHE: dict[tuple[int, int, str], tuple[float, Any]] = {}

# Minimum active managers before "top transfers" is meaningful.
MIN_MANAGERS_FOR_TOP_TRANSFERS = 4

PREVIEW_WATERMARK = "Preview — real data after deadline"


def clear_desk_side_caches() -> None:
    _RANK_CACHE.clear()
    _TOP_SCORERS_CACHE.clear()
    _LEAGUE_XI_CACHE.clear()


def _parse_breakdown(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def ownership_by_gw_number(db: Session, manager_id: int) -> dict[int, set[int]]:
    """Reconstruct which player_ids were owned for each scored GW.

    Starts from current OwnedPlayer and undoes TransferLog rows newest→oldest
    so re-bought players accumulate points across separate ownership stints.
    """
    current = {
        int(pid)
        for (pid,) in db.query(OwnedPlayer.player_id)
        .filter(OwnedPlayer.manager_id == manager_id)
        .all()
    }
    logs = (
        db.query(TransferLog, Gameweek.number)
        .join(Gameweek, Gameweek.id == TransferLog.gameweek_id)
        .filter(TransferLog.manager_id == manager_id)
        .order_by(Gameweek.number.desc(), TransferLog.id.desc())
        .all()
    )
    by_gw: dict[int, list[TransferLog]] = defaultdict(list)
    for log, num in logs:
        by_gw[int(num)].append(log)

    score_nums = [
        int(n)
        for (n,) in (
            db.query(Gameweek.number)
            .join(ManagerGameweekScore, ManagerGameweekScore.gameweek_id == Gameweek.id)
            .filter(ManagerGameweekScore.manager_id == manager_id)
            .distinct()
            .all()
        )
    ]
    transfer_nums = list(by_gw.keys())
    all_nums = sorted(set(score_nums) | set(transfer_nums) | ({1} if current else set()))
    if not all_nums:
        return {}

    squad = set(current)
    owned: dict[int, set[int]] = {}
    for n in sorted(all_nums, reverse=True):
        owned[n] = set(squad)
        for log in by_gw.get(n, []):
            if log.player_in_id:
                squad.discard(int(log.player_in_id))
            if log.player_out_id:
                squad.add(int(log.player_out_id))
    return owned


def manager_top_scorers_while_owned(
    db: Session,
    *,
    manager_id: int,
    current_gw_id: int,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Top players by points contributed to this manager while owned (TTL-cached)."""
    key = (int(manager_id), int(current_gw_id))
    now = time.monotonic()
    hit = _TOP_SCORERS_CACHE.get(key)
    if hit is not None and (now - hit[0]) < _TOP_SCORERS_TTL:
        return hit[1]

    owned_by_num = ownership_by_gw_number(db, manager_id)
    if not owned_by_num:
        _TOP_SCORERS_CACHE[key] = (now, [])
        return []

    scores = (
        db.query(ManagerGameweekScore, Gameweek.number)
        .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
        .filter(ManagerGameweekScore.manager_id == manager_id)
        .all()
    )
    totals: dict[int, float] = defaultdict(float)
    for row, num in scores:
        owned = owned_by_num.get(int(num)) or set()
        if not owned:
            continue
        bd = _parse_breakdown(row.breakdown_json)
        for line in bd.get("players") or []:
            if not isinstance(line, dict):
                continue
            pid = line.get("player_id")
            if pid is None:
                continue
            pid_i = int(pid)
            if pid_i not in owned:
                continue
            totals[pid_i] += float(line.get("points") or 0)

    if not totals:
        _TOP_SCORERS_CACHE[key] = (now, [])
        return []

    ranked = sorted(totals.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    pids = [pid for pid, _ in ranked]
    names = {
        int(r[0]): r[1]
        for r in db.query(Player.id, Player.name).filter(Player.id.in_(pids)).all()
    }
    rows = [
        {
            "player_id": pid,
            "name": names.get(pid, f"#{pid}"),
            "points": round(pts, 1),
        }
        for pid, pts in ranked
    ]
    _TOP_SCORERS_CACHE[key] = (now, rows)
    return rows


def _league_rank_map(db: Session, league: League, gw) -> dict[int, dict[str, Any]]:
    """Full league rank board, TTL-cached per (league, gw)."""
    key = (int(league.id), int(gw.id))
    now = time.monotonic()
    hit = _RANK_CACHE.get(key)
    if hit is not None and (now - hit[0]) < _RANK_TTL:
        return hit[1]

    lt = getattr(league, "league_type", "classic") or "classic"
    if lt == "h2h":
        rows, _ = standings_svc.h2h_standings(db, league, gw)
    else:
        rows = standings_svc.classic_standings(db, league, gw)

    size = len(rows)
    mapping: dict[int, dict[str, Any]] = {}
    for row in rows:
        mid = int(row["manager"].id)
        mapping[mid] = {
            "rank": int(row["rank"]),
            "size": size,
            "league_type": lt,
            "wins": int(row.get("wins") or 0),
            "draws": int(row.get("draws") or 0),
            "losses": int(row.get("losses") or 0),
        }
    _RANK_CACHE[key] = (now, mapping)
    return mapping


def manager_league_cards(
    db: Session,
    leagues: list[League],
    manager_id: int,
    gw,
) -> list[dict[str, Any]]:
    """Compact league rows for the XI left rail — uses TTL-cached standings boards."""
    cards: list[dict[str, Any]] = []
    for league in leagues:
        board = _league_rank_map(db, league, gw)
        info = board.get(int(manager_id))
        lt = getattr(league, "league_type", "classic") or "classic"
        size = info["size"] if info else len(board) or 0
        rank = info["rank"] if info else None
        if lt == "h2h" and info:
            label = f"H2H #{rank} · {info['wins']}-{info['draws']}-{info['losses']}"
        elif rank is not None:
            label = f"Classic #{rank} of {size}"
        else:
            label = f"{'H2H' if lt == 'h2h' else 'Classic'} · {size} managers"
        cards.append(
            {
                "id": league.id,
                "name": league.name,
                "league_type": lt,
                "rank": rank,
                "size": size,
                "label": label,
                "href": f"/standings/{league.id}",
            }
        )
    return cards


def xi_side_left_payload(
    db: Session,
    *,
    manager_id: int,
    gw,
    leagues: list[League],
    td_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DT window + league cards for #xiSideLeft."""
    info = td_info
    if info is None:
        info = td_svc.td_view(db, manager_id, gw.number, gameweek_id=gw.id)

    banner = td_svc.td_home_banner(db, manager_id, gw.number)
    end_gw = info.get("end_gw")
    gws_left = None
    if end_gw is not None:
        gws_left = max(0, int(end_gw) - int(gw.number))

    expired = bool(banner and banner.get("level") == "urgent")
    ending = bool(banner and banner.get("level") == "warn")

    return {
        "td": {
            "club_code": info.get("club_code"),
            "club_name": info.get("club_name") or info.get("club_code"),
            "badge": info.get("badge"),
            "start_gw": info.get("start_gw"),
            "end_gw": end_gw,
            "gws_left": gws_left,
            "expired": expired,
            "ending": ending,
            "message": (banner or {}).get("message"),
        },
        "leagues": manager_league_cards(db, leagues, manager_id, gw),
        "top_scorers": manager_top_scorers_while_owned(
            db, manager_id=manager_id, current_gw_id=int(gw.id)
        ),
    }


def _member_ids(db: Session, league_id: int) -> list[int]:
    return [
        int(mid)
        for (mid,) in db.query(Membership.manager_id)
        .filter(Membership.league_id == league_id)
        .all()
    ]


def league_top_transfers(
    db: Session,
    *,
    league_id: int,
    gameweek_id: int,
    limit: int = 3,
) -> dict[str, Any] | None:
    """One aggregated query path for top IN / OUT in a league this GW.

    Returns None when the league is too small for a meaningful top list.
    """
    mids = _member_ids(db, league_id)
    if len(mids) < MIN_MANAGERS_FOR_TOP_TRANSFERS:
        return None

    ins = (
        db.query(TransferLog.player_in_id, func.count().label("n"))
        .filter(
            TransferLog.gameweek_id == gameweek_id,
            TransferLog.manager_id.in_(mids),
        )
        .group_by(TransferLog.player_in_id)
        .order_by(func.count().desc(), TransferLog.player_in_id.asc())
        .limit(limit)
        .all()
    )
    outs = (
        db.query(TransferLog.player_out_id, func.count().label("n"))
        .filter(
            TransferLog.gameweek_id == gameweek_id,
            TransferLog.manager_id.in_(mids),
        )
        .group_by(TransferLog.player_out_id)
        .order_by(func.count().desc(), TransferLog.player_out_id.asc())
        .limit(limit)
        .all()
    )

    pids = {int(r[0]) for r in ins if r[0]} | {int(r[0]) for r in outs if r[0]}
    names: dict[int, str] = {}
    if pids:
        for row in db.query(Player.id, Player.name).filter(Player.id.in_(pids)).all():
            names[int(row[0])] = row[1]

    def _rows(raw: list) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for pid, n in raw:
            if not pid or not n:
                continue
            out.append(
                {
                    "player_id": int(pid),
                    "name": names.get(int(pid), f"#{pid}"),
                    "count": int(n),
                }
            )
        return out

    return {
        "most_in": _rows(ins),
        "most_out": _rows(outs),
        "manager_count": len(mids),
    }


def manager_gw_transfer_rows(
    db: Session,
    *,
    manager_id: int,
    gameweek_id: int,
) -> list[dict[str, Any]]:
    """This manager's TransferLog rows for the GW (out → in), newest first.

    Always filtered to ``gameweek_id`` so the list clears automatically when a
    new GW starts (no manual wipe).
    """
    logs = (
        db.query(TransferLog)
        .filter(
            TransferLog.manager_id == manager_id,
            TransferLog.gameweek_id == gameweek_id,
        )
        .order_by(TransferLog.id.desc())
        .all()
    )
    if not logs:
        return []
    pids = {int(r.player_out_id) for r in logs if r.player_out_id} | {
        int(r.player_in_id) for r in logs if r.player_in_id
    }
    names: dict[int, str] = {}
    if pids:
        for row in db.query(Player.id, Player.name).filter(Player.id.in_(pids)).all():
            names[int(row[0])] = row[1]
    rows: list[dict[str, Any]] = []
    for log in logs:
        oid = int(log.player_out_id) if log.player_out_id else None
        iid = int(log.player_in_id) if log.player_in_id else None
        rows.append(
            {
                "out_id": oid,
                "in_id": iid,
                "out": names.get(oid, f"#{oid}") if oid else "—",
                "in": names.get(iid, f"#{iid}") if iid else "—",
                "is_hit": bool(getattr(log, "is_hit", 0)),
            }
        )
    return rows


def _preview_most_xfer_rows() -> list[dict[str, Any]]:
    return [
        {"player_id": 0, "name": "Jugador-Ejemplo", "count": 0},
        {"player_id": 0, "name": "Nombre-Muestra", "count": 0},
        {"player_id": 0, "name": "Plantilla-Demo", "count": 0},
    ]


def _preview_most_picked_rows() -> list[dict[str, Any]]:
    return [
        {
            "player_id": 0,
            "name": "Jugador-Ejemplo",
            "points": 0,
            "pct": 0,
            "rival": "vs X",
        },
        {
            "player_id": 0,
            "name": "Nombre-Muestra",
            "points": 0,
            "pct": 0,
            "rival": "vs X",
        },
        {
            "player_id": 0,
            "name": "Plantilla-Demo",
            "points": 0,
            "pct": 0,
            "rival": "vs X",
        },
    ]


def _preview_popular_captain() -> dict[str, Any]:
    return {
        "player_id": 0,
        "name": "Capitan-Muestra",
        "points": 0,
        "pct": 0,
        "rival": "vs X",
    }


def _preview_league_block(league: League | None) -> dict[str, Any]:
    return {
        "id": league.id if league else 0,
        "name": league.name if league else "Your league",
        "preview": True,
        "watermark": PREVIEW_WATERMARK,
        "empty": False,
        "most_in": _preview_most_xfer_rows(),
        "most_out": _preview_most_xfer_rows(),
        "most_picked": _preview_most_picked_rows(),
        "popular_captain": _preview_popular_captain(),
        "manager_count": 0,
    }


def _season_points_map(db: Session, pids: set[int]) -> dict[int, float]:
    out: dict[int, float] = {}
    if not pids:
        return out
    for row in db.query(Player.id, Player.season_stats_json).filter(Player.id.in_(pids)).all():
        try:
            stats = json.loads(row[1] or "{}")
        except json.JSONDecodeError:
            stats = {}
        out[int(row[0])] = float((stats or {}).get("total_points") or 0)
    return out


def _rival_line(db: Session, *, team_code: str | None, gw_number: int) -> str:
    if not team_code:
        return "vs —"
    from app.services import fixtures as fixtures_svc

    upcoming = fixtures_svc.next_fixtures_for_club(
        db, club_code=team_code, from_gw=int(gw_number), limit=1
    )
    if not upcoming:
        return "vs —"
    fx = upcoming[0]
    opp = fx.get("opponent") or "—"
    venue = "H" if fx.get("home") else "A"
    return f"vs {opp} ({venue})"


def league_most_picked_xi(
    db: Session,
    *,
    league_id: int,
    gameweek_id: int,
    gw_number: int,
    limit: int = 5,
) -> list[dict[str, Any]] | None:
    """Share of league managers with each player in their starter XI this GW."""
    key = (int(league_id), int(gameweek_id), "picked")
    now = time.monotonic()
    hit = _LEAGUE_XI_CACHE.get(key)
    if hit is not None and (now - hit[0]) < _LEAGUE_XI_TTL:
        return hit[1]

    mids = _member_ids(db, league_id)
    if len(mids) < MIN_MANAGERS_FOR_TOP_TRANSFERS:
        _LEAGUE_XI_CACHE[key] = (now, None)
        return None

    rows = (
        db.query(SquadPick.player_id, func.count().label("n"))
        .filter(
            SquadPick.gameweek_id == gameweek_id,
            SquadPick.manager_id.in_(mids),
            SquadPick.is_starter == 1,
        )
        .group_by(SquadPick.player_id)
        .order_by(func.count().desc(), SquadPick.player_id.asc())
        .limit(limit)
        .all()
    )
    pids = {int(r[0]) for r in rows if r[0]}
    names: dict[int, str] = {}
    teams: dict[int, str] = {}
    if pids:
        for row in (
            db.query(Player.id, Player.name, Player.team_code)
            .filter(Player.id.in_(pids))
            .all()
        ):
            names[int(row[0])] = row[1]
            teams[int(row[0])] = row[2] or ""
    pts = _season_points_map(db, pids)
    total = float(len(mids))
    out: list[dict[str, Any]] = []
    for pid, n in rows:
        if not pid:
            continue
        pid_i = int(pid)
        out.append(
            {
                "player_id": pid_i,
                "name": names.get(pid_i, f"#{pid_i}"),
                "points": round(pts.get(pid_i, 0.0), 1),
                "pct": round((float(n) / total) * 100.0, 1) if total else 0.0,
                "count": int(n),
                "rival": _rival_line(db, team_code=teams.get(pid_i), gw_number=gw_number),
            }
        )
    _LEAGUE_XI_CACHE[key] = (now, out)
    return out


def league_popular_captain(
    db: Session,
    *,
    league_id: int,
    gameweek_id: int,
    gw_number: int,
) -> dict[str, Any] | None:
    """Most-captained player among league managers this GW (one row)."""
    key = (int(league_id), int(gameweek_id), "captain")
    now = time.monotonic()
    hit = _LEAGUE_XI_CACHE.get(key)
    if hit is not None and (now - hit[0]) < _LEAGUE_XI_TTL:
        return hit[1]

    mids = _member_ids(db, league_id)
    if len(mids) < MIN_MANAGERS_FOR_TOP_TRANSFERS:
        _LEAGUE_XI_CACHE[key] = (now, None)
        return None

    row = (
        db.query(SquadPick.player_id, func.count().label("n"))
        .filter(
            SquadPick.gameweek_id == gameweek_id,
            SquadPick.manager_id.in_(mids),
            SquadPick.is_captain == 1,
        )
        .group_by(SquadPick.player_id)
        .order_by(func.count().desc(), SquadPick.player_id.asc())
        .limit(1)
        .first()
    )
    if not row or not row[0]:
        empty: dict[str, Any] | None = None
        _LEAGUE_XI_CACHE[key] = (now, empty)
        return None

    pid_i = int(row[0])
    n = int(row[1])
    player = db.query(Player).filter(Player.id == pid_i).one_or_none()
    pts = _season_points_map(db, {pid_i}).get(pid_i, 0.0)
    total = float(len(mids))
    payload = {
        "player_id": pid_i,
        "name": player.name if player else f"#{pid_i}",
        "points": round(pts, 1),
        "pct": round((float(n) / total) * 100.0, 1) if total else 0.0,
        "count": n,
        "rival": _rival_line(
            db,
            team_code=player.team_code if player else None,
            gw_number=gw_number,
        ),
    }
    _LEAGUE_XI_CACHE[key] = (now, payload)
    return payload


def transfers_side_left_payload(
    db: Session,
    *,
    leagues: list[League],
    gw,
    manager_id: int | None = None,
) -> dict[str, Any]:
    """League transfer trends + my GW history.

    Before deadline (``can_edit``): sample preview tables (never mixed with real).
    After deadline: real aggregated Most IN/OUT, most-picked XI, popular captain.
    """
    my_rows: list[dict[str, Any]] = []
    if manager_id is not None:
        my_rows = manager_gw_transfer_rows(
            db, manager_id=int(manager_id), gameweek_id=int(gw.id)
        )

    if deadline_svc.can_edit(gw):
        blocks = [_preview_league_block(lg) for lg in leagues] or [_preview_league_block(None)]
        return {
            "locked": False,
            "preview": True,
            "watermark": PREVIEW_WATERMARK,
            "message": None,
            "leagues": blocks,
            "min_managers": MIN_MANAGERS_FOR_TOP_TRANSFERS,
            "my_transfers": my_rows,
        }

    blocks: list[dict[str, Any]] = []
    for league in leagues:
        top = league_top_transfers(db, league_id=league.id, gameweek_id=gw.id)
        picked = league_most_picked_xi(
            db,
            league_id=league.id,
            gameweek_id=gw.id,
            gw_number=int(gw.number),
        )
        captain = league_popular_captain(
            db,
            league_id=league.id,
            gameweek_id=gw.id,
            gw_number=int(gw.number),
        )
        if top is None and picked is None and captain is None:
            continue
        most_in = (top or {}).get("most_in") or []
        most_out = (top or {}).get("most_out") or []
        empty = not most_in and not most_out and not picked and not captain
        blocks.append(
            {
                "id": league.id,
                "name": league.name,
                "preview": False,
                "watermark": None,
                "empty": empty,
                "most_in": most_in,
                "most_out": most_out,
                "most_picked": picked or [],
                "popular_captain": captain,
                "manager_count": (top or {}).get("manager_count") or len(_member_ids(db, league.id)),
            }
        )

    return {
        "locked": False,
        "preview": False,
        "watermark": None,
        "message": None,
        "leagues": blocks,
        "min_managers": MIN_MANAGERS_FOR_TOP_TRANSFERS,
        "my_transfers": my_rows,
    }
