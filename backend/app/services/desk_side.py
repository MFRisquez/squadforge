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
RANK_PREVIEW_WATERMARK = "Preview — real ranks after GW2"

# Desktop position chart geometry (taller so the left rail can fill pitch height).
_DESK_CHART_W = 400.0
_DESK_CHART_H = 280.0
_DESK_PAD_L = 100.0  # room for team-name labels on the left
_DESK_PAD_R = 14.0
_DESK_PAD_T = 16.0
_DESK_PAD_B = 24.0
_DESK_WINDOW_GWS = 5
_DESK_NAME_MAX = 10
_DESK_NAME_GAP = 12.0


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
    """Top players by points contributed to this manager while owned (TTL-cached).

    Also returns starter appearances (APP) and while-owned G / A / CS counts.
    """
    from app.models import MatchEvent

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
        db.query(ManagerGameweekScore, Gameweek.number, Gameweek.id)
        .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
        .filter(ManagerGameweekScore.manager_id == manager_id)
        .all()
    )
    totals: dict[int, float] = defaultdict(float)
    scored_nums: set[int] = set()
    for row, num, _gid in scores:
        scored_nums.add(int(num))
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
    pid_set = set(pids)

    apps: dict[int, int] = defaultdict(int)
    goals: dict[int, int] = defaultdict(int)
    assists: dict[int, int] = defaultdict(int)
    cs: dict[int, int] = defaultdict(int)

    if pids and scored_nums:
        starter_rows = (
            db.query(SquadPick.player_id, Gameweek.number)
            .join(Gameweek, Gameweek.id == SquadPick.gameweek_id)
            .filter(
                SquadPick.manager_id == manager_id,
                SquadPick.is_starter == 1,
                SquadPick.player_id.in_(pids),
                Gameweek.number.in_(scored_nums),
            )
            .all()
        )
        for pid, num in starter_rows:
            pid_i = int(pid)
            if pid_i in (owned_by_num.get(int(num)) or set()):
                apps[pid_i] += 1

        event_rows = (
            db.query(MatchEvent.player_id, MatchEvent.metric, MatchEvent.value, Gameweek.number)
            .join(Gameweek, Gameweek.id == MatchEvent.gameweek_id)
            .filter(
                MatchEvent.player_id.in_(pids),
                MatchEvent.metric.in_(("goals", "assists", "clean_sheets")),
                Gameweek.number.in_(scored_nums),
            )
            .all()
        )
        for pid, metric, value, num in event_rows:
            pid_i = int(pid)
            if pid_i not in pid_set:
                continue
            if pid_i not in (owned_by_num.get(int(num)) or set()):
                continue
            v = int(float(value or 0))
            if v <= 0:
                continue
            if metric == "goals":
                goals[pid_i] += v
            elif metric == "assists":
                assists[pid_i] += v
            elif metric == "clean_sheets":
                cs[pid_i] += v

    names = {
        int(r[0]): r[1]
        for r in db.query(Player.id, Player.name).filter(Player.id.in_(pids)).all()
    }
    rows = [
        {
            "player_id": pid,
            "name": names.get(pid, f"#{pid}"),
            "points": round(pts, 1),
            "app": int(apps.get(pid, 0)),
            "goals": int(goals.get(pid, 0)),
            "assists": int(assists.get(pid, 0)),
            "cs": int(cs.get(pid, 0)),
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
    include_kpis: bool = False,
) -> dict[str, Any]:
    """DT window + league cards for #xiSideLeft.

    Heavy KPI blocks (top scorers + rank charts) default off so /lineup can
    paint first; clients fetch them from ``/api/xi/side-kpis``.
    """
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

    payload: dict[str, Any] = {
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
        "kpis_deferred": not include_kpis,
    }
    if include_kpis:
        payload.update(
            xi_side_kpis_payload(db, manager_id=manager_id, gw=gw, leagues=leagues)
        )
    else:
        payload["top_scorers"] = []
        payload["rank_spark"] = None
    return payload


def xi_side_kpis_payload(
    db: Session,
    *,
    manager_id: int,
    gw,
    leagues: list[League],
) -> dict[str, Any]:
    """Heavy left-rail KPI blocks: top scorers + position charts."""
    return {
        "top_scorers": manager_top_scorers_while_owned(
            db, manager_id=manager_id, current_gw_id=int(gw.id)
        ),
        "rank_spark": manager_rank_sparks(
            db, manager_id=manager_id, gw=gw, leagues=leagues
        ),
        "kpis_deferred": False,
    }


def _desk_chart_kwargs() -> dict[str, Any]:
    return {
        "chart_width": _DESK_CHART_W,
        "chart_height": _DESK_CHART_H,
        "pad_left": _DESK_PAD_L,
        "pad_right": _DESK_PAD_R,
        "pad_top": _DESK_PAD_T,
        "pad_bottom": _DESK_PAD_B,
        "include_area": True,
    }


def _truncate_team_name(name: str, max_len: int = _DESK_NAME_MAX) -> str:
    text = (name or "").strip() or "—"
    if len(text) <= max_len:
        return text
    return text[: max(1, max_len - 1)] + "…"


def _nudge_name_labels(labels: list[dict[str, Any]], min_gap: float = _DESK_NAME_GAP) -> list[dict[str, Any]]:
    ordered = sorted(labels, key=lambda row: float(row["y"]))
    if not ordered:
        return []
    prev = float(ordered[0]["y"])
    ordered[0]["y"] = round(prev, 1)
    for lab in ordered[1:]:
        y = float(lab["y"])
        if y - prev < min_gap:
            y = prev + min_gap
        lab["y"] = round(y, 1)
        prev = y
    return ordered


def _name_labels_for_chart(chart: dict[str, Any]) -> list[dict[str, Any]]:
    labels: list[dict[str, Any]] = []
    for series in chart.get("series") or []:
        pts = series.get("points") or []
        if not pts:
            continue
        full = series.get("team_name") or "—"
        labels.append(
            {
                "text": _truncate_team_name(full),
                "full": full,
                "y": pts[-1]["y"],
                "is_me": bool(series.get("is_me")),
            }
        )
    return _nudge_name_labels(labels)


def _chart_view(chart: dict[str, Any]) -> dict[str, Any]:
    """Serializable chart slice used by the desk SVG + modal."""
    labeled = dict(chart)
    labeled["name_labels"] = _name_labels_for_chart(labeled)
    return {
        "gw_numbers": labeled.get("gw_numbers") or [],
        "gw_labels": labeled.get("gw_labels") or [],
        "grid": labeled.get("grid") or [],
        "series": labeled.get("series") or [],
        "name_labels": labeled.get("name_labels") or [],
        "chart_width": labeled.get("chart_width") or int(_DESK_CHART_W),
        "chart_height": labeled.get("chart_height") or int(_DESK_CHART_H),
        "plot_left": labeled.get("plot_left"),
        "plot_right": labeled.get("plot_right"),
        "plot_top": labeled.get("plot_top"),
        "plot_bottom": labeled.get("plot_bottom"),
        "max_rank": labeled.get("max_rank"),
    }


def _window_chart(
    chart: dict[str, Any],
    *,
    me_id: int | None,
    last_n: int = _DESK_WINDOW_GWS,
) -> dict[str, Any]:
    gws = list(chart.get("gw_numbers") or [])
    series = chart.get("series") or []
    if len(gws) <= last_n:
        return _chart_view(chart)
    start = len(gws) - last_n
    managers = []
    for s in series:
        ranks = list(s.get("ranks") or [])[start:]
        if len(ranks) < 2:
            continue
        managers.append(
            {
                "manager_id": s.get("manager_id"),
                "name": s.get("team_name") or "—",
                "ranks": ranks,
            }
        )
    if not managers:
        return _chart_view(chart)
    raw = {"gameweeks": gws[start:], "managers": managers}
    rebuilt = standings_svc._chart_from_rank_history(
        raw, me_id=me_id, **_desk_chart_kwargs()
    )
    return _chart_view(rebuilt)


def _preview_rank_raw(
    *,
    manager_id: int,
    team_name: str,
    member_count: int,
    league_id: int,
) -> dict[str, Any]:
    """Synthetic GW ranks so the Position chart can be designed before GW2."""
    n = max(4, int(member_count) or 4)
    gameweeks = [1, 2, 3, 4, 5]
    seed = int(league_id) % 3
    me_patterns = (
        [n, max(1, n - 1), max(1, n // 2), 2, 1],
        [max(1, n // 2), n - 1, 3, 2, 1],
        [3, 2, max(1, n // 2), max(1, n - 1), n],
    )
    me_ranks = [max(1, min(n, r)) for r in me_patterns[seed]]
    managers = [
        {
            "manager_id": int(manager_id),
            "name": team_name,
            "ranks": me_ranks,
        }
    ]
    # Ghost rivals for scale / professional density (not real people).
    for i in range(1, n):
        base = i + 1
        wave = [
            max(1, min(n, base + ((i + g) % 3) - 1))
            for g in range(5)
        ]
        # Keep "me" unique on the last GW when possible
        if wave[-1] == me_ranks[-1]:
            wave[-1] = 1 if me_ranks[-1] != 1 else min(n, 2)
        managers.append(
            {
                "manager_id": -(i),
                "name": f"Rival {i}",
                "ranks": wave,
            }
        )
    return {"gameweeks": gameweeks, "managers": managers}


def _spark_payload_from_chart(
    chart: dict[str, Any],
    *,
    league: League,
    preview: bool,
    me_id: int | None = None,
) -> dict[str, Any]:
    full = _chart_view(chart)
    window = _window_chart(chart, me_id=me_id, last_n=_DESK_WINDOW_GWS)
    me = next((s for s in (window.get("series") or []) if s.get("is_me")), None)
    ranks = (me or {}).get("ranks") or []
    return {
        "league_id": int(league.id),
        "league_name": league.name,
        "league_type": getattr(league, "league_type", "classic") or "classic",
        "empty": False,
        "preview": preview,
        "watermark": RANK_PREVIEW_WATERMARK if preview else None,
        "current_rank": ranks[-1] if ranks else None,
        "has_more_gws": len(full.get("gw_numbers") or [])
        > len(window.get("gw_numbers") or []),
        "window": window,
        "full": full,
        # Flatten window for templates that read top-level chart fields.
        **window,
    }


def manager_rank_spark(
    db: Session,
    *,
    manager_id: int,
    gw,
    leagues: list[League],
) -> dict[str, Any] | None:
    """Position timeline for the first league (preview until 2+ scored GWs)."""
    sparks = manager_rank_sparks(db, manager_id=manager_id, gw=gw, leagues=leagues)
    charts = (sparks or {}).get("charts") or []
    return charts[0] if charts else None


def manager_rank_sparks(
    db: Session,
    *,
    manager_id: int,
    gw,
    leagues: list[League],
) -> dict[str, Any] | None:
    """Position charts for every league the manager is in (switchable on desk)."""
    if not leagues:
        return None

    from app.models import Manager

    manager = db.query(Manager).filter(Manager.id == manager_id).one_or_none()
    team_name = (
        ((manager.team_name if manager else "") or "").strip()
        or ((manager.display_name if manager else "") or "You")
    )

    charts: list[dict[str, Any]] = []
    kwargs = _desk_chart_kwargs()
    for league in leagues:
        member_count = (
            db.query(func.count(Membership.id))
            .filter(Membership.league_id == int(league.id))
            .scalar()
            or 0
        )
        hist = standings_svc.league_rank_history(
            db, league, gw, me_id=manager_id, **kwargs
        )
        gw_numbers = hist.get("gw_numbers") or []
        if len(gw_numbers) >= 2 and hist.get("series"):
            charts.append(
                _spark_payload_from_chart(
                    hist, league=league, preview=False, me_id=manager_id
                )
            )
            continue

        raw = _preview_rank_raw(
            manager_id=manager_id,
            team_name=team_name,
            member_count=int(member_count),
            league_id=int(league.id),
        )
        preview_chart = standings_svc._chart_from_rank_history(
            raw, me_id=manager_id, **kwargs
        )
        charts.append(
            _spark_payload_from_chart(
                preview_chart, league=league, preview=True, me_id=manager_id
            )
        )

    return {"charts": charts, "count": len(charts)}


def _member_ids(db: Session, league_id: int) -> list[int]:
    return [
        int(mid)
        for (mid,) in db.query(Membership.manager_id)
        .filter(Membership.league_id == league_id)
        .all()
    ]


def _union_member_ids(db: Session, leagues: list[League]) -> list[int]:
    """Deduped manager ids across every league the user is in."""
    seen: set[int] = set()
    out: list[int] = []
    for league in leagues:
        for mid in _member_ids(db, int(league.id)):
            if mid in seen:
                continue
            seen.add(mid)
            out.append(mid)
    return out


def top_transfers_for_managers(
    db: Session,
    *,
    manager_ids: list[int],
    gameweek_id: int,
    limit: int = 3,
) -> dict[str, Any] | None:
    """Aggregated Most IN / OUT for a manager set (union of leagues)."""
    mids = [int(m) for m in manager_ids]
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
    return top_transfers_for_managers(
        db,
        manager_ids=_member_ids(db, league_id),
        gameweek_id=gameweek_id,
        limit=limit,
    )


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


def _preview_trends_block() -> dict[str, Any]:
    """Single combined preview (not per-league) for League Transfer Trends."""
    return {
        "preview": True,
        "watermark": PREVIEW_WATERMARK,
        "empty": False,
        "most_in": _preview_most_xfer_rows(),
        "most_out": _preview_most_xfer_rows(),
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
    """Combined League Transfer Trends + my GW history.

    One view across the union of managers in all of the user's leagues
    (deduped) — never a repeated block per league.

    Before deadline (``can_edit``): sample preview tables (never mixed with real).
    After deadline: real aggregated Most IN / Most OUT.
    """
    my_rows: list[dict[str, Any]] = []
    if manager_id is not None:
        my_rows = manager_gw_transfer_rows(
            db, manager_id=int(manager_id), gameweek_id=int(gw.id)
        )

    if deadline_svc.can_edit(gw):
        trends = _preview_trends_block()
        return {
            "locked": False,
            "preview": True,
            "watermark": PREVIEW_WATERMARK,
            "message": None,
            "trends": trends,
            # Legacy key kept empty so old callers don't loop per-league.
            "leagues": [],
            "min_managers": MIN_MANAGERS_FOR_TOP_TRANSFERS,
            "my_transfers": my_rows,
        }

    mids = _union_member_ids(db, leagues)
    top = top_transfers_for_managers(db, manager_ids=mids, gameweek_id=int(gw.id))
    if top is None:
        trends = None
    else:
        most_in = top.get("most_in") or []
        most_out = top.get("most_out") or []
        trends = {
            "preview": False,
            "watermark": None,
            "empty": not most_in and not most_out,
            "most_in": most_in,
            "most_out": most_out,
            "manager_count": top.get("manager_count") or len(mids),
        }

    return {
        "locked": False,
        "preview": False,
        "watermark": None,
        "message": None,
        "trends": trends,
        "leagues": [],
        "min_managers": MIN_MANAGERS_FOR_TOP_TRANSFERS,
        "my_transfers": my_rows,
    }
