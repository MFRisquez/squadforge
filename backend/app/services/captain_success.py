"""Captain success rate for a manager across completed gameweeks."""

from __future__ import annotations

import json
import statistics
from typing import Any

from sqlalchemy.orm import Session

from app.models import Gameweek, ManagerGameweekScore


def _parse_breakdown(raw: str | None) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def captain_success_for_manager(db: Session, manager_id: int) -> dict[str, Any]:
    """Share of completed GWs where the captain "hit".

    Hit definition (documented for UI):
      Captain *base* points (before ×2/×3) are strictly above the median of
      that manager's own scored players' base points in the same GW.
      Uses ManagerGameweekScore.breakdown_json player lines. GWs without a
      captain line or with fewer than 2 players are skipped.
    """
    # Prefer finished GWs; one JOIN instead of finished-list + scores IN (...).
    joined = (
        db.query(ManagerGameweekScore, Gameweek)
        .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
        .filter(
            ManagerGameweekScore.manager_id == manager_id,
            Gameweek.status == "finished",
        )
        .all()
    )
    if not joined:
        # Demo / mid-season: any scored GW counts as evaluable.
        joined = (
            db.query(ManagerGameweekScore, Gameweek)
            .join(Gameweek, Gameweek.id == ManagerGameweekScore.gameweek_id)
            .filter(ManagerGameweekScore.manager_id == manager_id)
            .all()
        )

    if not joined:
        return {
            "rate": None,
            "hits": 0,
            "eligible": 0,
            "label": "—",
            "sub": "no GWs yet",
            "definition": (
                "Hit = captain base points above median of your squad that GW"
            ),
        }

    gw_by_id = {g.id: g for _, g in joined}
    scores = [row for row, _ in joined]

    hits = 0
    eligible = 0
    for row in scores:
        bd = _parse_breakdown(row.breakdown_json)
        players = [p for p in (bd.get("players") or []) if isinstance(p, dict)]
        if len(players) < 2:
            continue
        bases = []
        captain_base = None
        armband = bd.get("armband_player_id")
        for line in players:
            try:
                base = float(line.get("base") if line.get("base") is not None else line.get("points") or 0)
            except (TypeError, ValueError):
                base = 0.0
            bases.append(base)
            is_cap = bool(line.get("captain"))
            if not is_cap and armband is not None and int(line.get("player_id") or 0) == int(armband):
                is_cap = True
            if is_cap:
                captain_base = base
        if captain_base is None or len(bases) < 2:
            continue
        eligible += 1
        median = statistics.median(bases)
        if captain_base > median:
            hits += 1

    if eligible == 0:
        return {
            "rate": None,
            "hits": 0,
            "eligible": 0,
            "label": "—",
            "sub": "no captain GWs",
            "definition": (
                "Hit = captain base points above median of your squad that GW"
            ),
        }

    rate = hits / eligible
    return {
        "rate": round(rate * 100),
        "hits": hits,
        "eligible": eligible,
        "label": f"{round(rate * 100)}%",
        "sub": f"{hits}/{eligible} GWs",
        "definition": (
            "Hit = captain base points above median of your squad that GW"
        ),
        "gameweeks_sampled": len(gw_by_id),
    }
