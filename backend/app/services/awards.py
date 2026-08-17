"""End-of-season league awards derived from existing GW scores / chips / metrics."""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    ChipPlay,
    Gameweek,
    Manager,
    ManagerGameweekScore,
    MatchEvent,
    Membership,
    PlayerPoints,
)


CHIP_LABELS = {
    "wildcard": "Wildcard",
    "free_hit": "Free Hit",
    "bench_boost": "Bench Boost",
    "triple_captain": "Triple Captain",
    "super_sub": "Super Sub",
}


def _finished_gameweeks(db: Session) -> list[Gameweek]:
    rows = (
        db.query(Gameweek)
        .filter(Gameweek.status == "finished")
        .order_by(Gameweek.number.asc())
        .all()
    )
    if rows:
        return rows
    # Fallback: any GW that already has manager scores (demo / mid-sync).
    scored_ids = {
        r[0]
        for r in db.query(ManagerGameweekScore.gameweek_id).distinct().all()
    }
    if not scored_ids:
        return []
    return (
        db.query(Gameweek)
        .filter(Gameweek.id.in_(scored_ids))
        .order_by(Gameweek.number.asc())
        .all()
    )


def _parse_breakdown(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _award(
    *,
    key: str,
    title: str,
    blurb: str,
    manager: Manager | None,
    value_label: str,
    detail: str = "",
) -> dict[str, Any]:
    return {
        "key": key,
        "title": title,
        "blurb": blurb,
        "manager_id": manager.id if manager else None,
        "team_name": (manager.team_name or manager.display_name) if manager else None,
        "value_label": value_label,
        "detail": detail,
        "empty": manager is None,
    }


def _best_streak(
    managers: list[Manager],
    scores_by_mgr: dict[int, list[tuple[int, float]]],
) -> dict[str, Any]:
    """Highest sum of any contiguous run of completed GW totals (min 2 GWs)."""
    best: tuple[float, int, int, int, Manager] | None = None  # sum, len, start, end, mgr
    by_id = {m.id: m for m in managers}
    for mid, series in scores_by_mgr.items():
        if len(series) < 2 or mid not in by_id:
            continue
        totals = [t for _, t in series]
        numbers = [n for n, _ in series]
        n = len(totals)
        for i in range(n):
            running = 0.0
            for j in range(i, n):
                running += totals[j]
                length = j - i + 1
                if length < 2:
                    continue
                cand = (running, length, numbers[i], numbers[j], by_id[mid])
                if best is None or cand[0] > best[0] or (
                    cand[0] == best[0] and cand[1] > best[1]
                ):
                    best = cand
    if not best:
        return _award(
            key="streak",
            title="Hot streak",
            blurb="Best consecutive gameweek points run (2+ GWs).",
            manager=None,
            value_label="—",
        )
    total, length, start_n, end_n, mgr = best
    return _award(
        key="streak",
        title="Hot streak",
        blurb="Best consecutive gameweek points run (2+ GWs).",
        manager=mgr,
        value_label=f"{total:.0f} pts",
        detail=f"GW{start_n}–GW{end_n} · {length} GWs",
    )


def _most_clean_sheets_in_xi(
    db: Session,
    managers: list[Manager],
    gw_ids: list[int],
) -> dict[str, Any]:
    """Count starter XI clean sheets across finished GWs (MatchEvent + Squad score lines)."""
    by_id = {m.id: m for m in managers}
    manager_ids = list(by_id)
    if not manager_ids or not gw_ids:
        return _award(
            key="clean_sheets",
            title="Clean sheet king",
            blurb="Most clean sheets from players in your XI.",
            manager=None,
            value_label="—",
        )

    scores = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.manager_id.in_(manager_ids),
            ManagerGameweekScore.gameweek_id.in_(gw_ids),
        )
        .all()
    )
    xi_by_mgr_gw: dict[tuple[int, int], set[int]] = {}
    for row in scores:
        bd = _parse_breakdown(row.breakdown_json)
        players = bd.get("players") or []
        pids: set[int] = set()
        for line in players:
            if not isinstance(line, dict):
                continue
            if line.get("bench") or line.get("bench_boost"):
                continue
            pid = line.get("player_id")
            if pid is not None:
                pids.add(int(pid))
        xi_by_mgr_gw[(row.manager_id, row.gameweek_id)] = pids

    cs_events = (
        db.query(MatchEvent)
        .filter(
            MatchEvent.gameweek_id.in_(gw_ids),
            MatchEvent.metric == "clean_sheets",
            MatchEvent.value >= 1,
        )
        .all()
    )
    cs_by_gw_player: dict[tuple[int, int], float] = {
        (e.gameweek_id, e.player_id): float(e.value or 0) for e in cs_events
    }

    totals: dict[int, float] = defaultdict(float)
    for (mid, gwid), pids in xi_by_mgr_gw.items():
        for pid in pids:
            totals[mid] += cs_by_gw_player.get((gwid, pid), 0.0)

    if not totals:
        return _award(
            key="clean_sheets",
            title="Clean sheet king",
            blurb="Most clean sheets from players in your XI.",
            manager=None,
            value_label="—",
        )
    mid = max(totals, key=lambda m: (totals[m], -m))
    return _award(
        key="clean_sheets",
        title="Clean sheet king",
        blurb="Most clean sheets from players in your XI.",
        manager=by_id.get(mid),
        value_label=f"{totals[mid]:.0f} CS",
        detail="Starters only (bench boost excluded)",
    )


def _best_chip_gw(
    db: Session,
    managers: list[Manager],
    gw_ids: list[int],
) -> dict[str, Any]:
    by_id = {m.id: m for m in managers}
    manager_ids = list(by_id)
    if not manager_ids or not gw_ids:
        return _award(
            key="chip",
            title="Chip masterclass",
            blurb="Highest single GW score while a chip was active.",
            manager=None,
            value_label="—",
        )

    plays = (
        db.query(ChipPlay, ManagerGameweekScore, Gameweek)
        .join(
            ManagerGameweekScore,
            (ManagerGameweekScore.manager_id == ChipPlay.manager_id)
            & (ManagerGameweekScore.gameweek_id == ChipPlay.gameweek_id),
        )
        .join(Gameweek, Gameweek.id == ChipPlay.gameweek_id)
        .filter(
            ChipPlay.manager_id.in_(manager_ids),
            ChipPlay.gameweek_id.in_(gw_ids),
        )
        .all()
    )
    if not plays:
        return _award(
            key="chip",
            title="Chip masterclass",
            blurb="Highest single GW score while a chip was active.",
            manager=None,
            value_label="—",
        )

    best_play = max(plays, key=lambda row: (float(row[1].total or 0), -row[2].number))
    play, score, gw = best_play
    chip_label = CHIP_LABELS.get(play.chip, play.chip)
    return _award(
        key="chip",
        title="Chip masterclass",
        blurb="Highest single GW score while a chip was active.",
        manager=by_id.get(play.manager_id),
        value_label=f"{float(score.total or 0):.0f} pts",
        detail=f"{chip_label} · GW{gw.number}",
    )


def _best_differential(
    db: Session,
    managers: list[Manager],
    gw_ids: list[int],
) -> dict[str, Any]:
    """Most scouting_bonus points earned on players that appeared in XI lines."""
    by_id = {m.id: m for m in managers}
    manager_ids = list(by_id)
    if not manager_ids or not gw_ids:
        return _award(
            key="differential",
            title="Differential hunter",
            blurb="Most scouting bonus points from unique hits.",
            manager=None,
            value_label="—",
        )

    scores = (
        db.query(ManagerGameweekScore)
        .filter(
            ManagerGameweekScore.manager_id.in_(manager_ids),
            ManagerGameweekScore.gameweek_id.in_(gw_ids),
        )
        .all()
    )
    needed: set[tuple[int, int]] = set()
    xi_lines: list[tuple[int, int, int]] = []  # mgr, gw, player
    for row in scores:
        bd = _parse_breakdown(row.breakdown_json)
        for line in bd.get("players") or []:
            if not isinstance(line, dict):
                continue
            pid = line.get("player_id")
            if pid is None:
                continue
            pid_i = int(pid)
            needed.add((row.gameweek_id, pid_i))
            xi_lines.append((row.manager_id, row.gameweek_id, pid_i))

    bonus_map: dict[tuple[int, int], float] = {}
    if needed:
        pts_rows = (
            db.query(PlayerPoints)
            .filter(PlayerPoints.gameweek_id.in_(gw_ids))
            .all()
        )
        for pr in pts_rows:
            key = (pr.gameweek_id, pr.player_id)
            if key not in needed:
                continue
            bd = _parse_breakdown(pr.breakdown_json)
            bonus = float(bd.get("scouting_bonus") or 0)
            if bonus:
                bonus_map[key] = bonus

    totals: dict[int, float] = defaultdict(float)
    for mid, gwid, pid in xi_lines:
        totals[mid] += bonus_map.get((gwid, pid), 0.0)

    if not totals or max(totals.values()) <= 0:
        return _award(
            key="differential",
            title="Differential hunter",
            blurb="Most scouting bonus points from unique hits.",
            manager=None,
            value_label="—",
        )
    mid = max(totals, key=lambda m: (totals[m], -m))
    return _award(
        key="differential",
        title="Differential hunter",
        blurb="Most scouting bonus points from unique hits.",
        manager=by_id.get(mid),
        value_label=f"{totals[mid]:.0f} pts",
        detail="Sum of +2 scouting bonuses in XI",
    )


def league_awards(db: Session, league_id: int) -> dict[str, Any]:
    memberships = db.query(Membership).filter(Membership.league_id == league_id).all()
    manager_ids = [m.manager_id for m in memberships]
    managers = (
        db.query(Manager).filter(Manager.id.in_(manager_ids)).all() if manager_ids else []
    )
    gws = _finished_gameweeks(db)
    gw_ids = [g.id for g in gws]

    scores_by_mgr: dict[int, list[tuple[int, float]]] = defaultdict(list)
    if managers and gw_ids:
        rows = (
            db.query(ManagerGameweekScore, Gameweek)
            .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
            .filter(
                ManagerGameweekScore.manager_id.in_([m.id for m in managers]),
                ManagerGameweekScore.gameweek_id.in_(gw_ids),
            )
            .order_by(Gameweek.number.asc())
            .all()
        )
        for score, gw in rows:
            scores_by_mgr[score.manager_id].append((gw.number, float(score.total or 0)))

    categories = [
        _best_streak(managers, scores_by_mgr),
        _most_clean_sheets_in_xi(db, managers, gw_ids),
        _best_chip_gw(db, managers, gw_ids),
        _best_differential(db, managers, gw_ids),
    ]
    return {
        "gameweeks_counted": len(gws),
        "member_count": len(managers),
        "categories": categories,
    }
