"""Desktop left-rail payloads for XI / Transfers (cached, batched)."""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import League, Membership, Player, TransferLog
from app.services import deadline as deadline_svc
from app.services import standings as standings_svc
from app.services import td as td_svc

# Same idea as player_catalog FDR TTL — avoid rebuilding standings on every soft-nav.
_RANK_TTL = 45.0
# (league_id, gw_id) -> (monotonic_ts, {manager_id: card_fields})
_RANK_CACHE: dict[tuple[int, int], tuple[float, dict[int, dict[str, Any]]]] = {}

# Minimum active managers before "top transfers" is meaningful.
MIN_MANAGERS_FOR_TOP_TRANSFERS = 4


def clear_desk_side_caches() -> None:
    _RANK_CACHE.clear()


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
    """This manager's TransferLog rows for the GW (out → in), oldest first."""
    logs = (
        db.query(TransferLog)
        .filter(
            TransferLog.manager_id == manager_id,
            TransferLog.gameweek_id == gameweek_id,
        )
        .order_by(TransferLog.id.asc())
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


def transfers_side_left_payload(
    db: Session,
    *,
    leagues: list[League],
    gw,
    manager_id: int | None = None,
) -> dict[str, Any]:
    """Top transfers rail + this manager's GW history (always)."""
    my_rows: list[dict[str, Any]] = []
    if manager_id is not None:
        my_rows = manager_gw_transfer_rows(
            db, manager_id=int(manager_id), gameweek_id=int(gw.id)
        )

    if deadline_svc.can_edit(gw):
        return {
            "locked": True,
            "message": "Se revela cuando cierre el mercado",
            "leagues": [],
            "min_managers": MIN_MANAGERS_FOR_TOP_TRANSFERS,
            "my_transfers": my_rows,
        }

    blocks: list[dict[str, Any]] = []
    for league in leagues:
        top = league_top_transfers(db, league_id=league.id, gameweek_id=gw.id)
        if top is None:
            continue
        if not top["most_in"] and not top["most_out"]:
            blocks.append(
                {
                    "id": league.id,
                    "name": league.name,
                    "empty": True,
                    "most_in": [],
                    "most_out": [],
                }
            )
            continue
        blocks.append(
            {
                "id": league.id,
                "name": league.name,
                "empty": False,
                **top,
            }
        )

    return {
        "locked": False,
        "message": None,
        "leagues": blocks,
        "min_managers": MIN_MANAGERS_FOR_TOP_TRANSFERS,
        "my_transfers": my_rows,
    }
