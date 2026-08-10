"""Scouting bonus — reward differential picks that actually deliver.

This is a *league* rule, not a pure on-pitch KPI: it needs ownership counts.
Apply it when building a manager's GW score, after position formulas run.
"""

from __future__ import annotations

from typing import Any

from app.scoring.common import m

SCOUTING_BONUS_POINTS = 2.0


def is_differential_pick(owners_count: int, league_size: int) -> bool:
    """Best rule for a private league of ~5–10 managers.

    - With 5–10 people, "5% ownership" is weaker than one owner (5% of 10 = 0.5).
    - So: only **exactly one manager** owns the player → counts as scouting.
    - If the league grows past 10, switch to ≤10% ownership (at least 1 owner).
    """
    if owners_count < 1 or league_size < 1:
        return False
    if league_size <= 10:
        return owners_count == 1
    max_owners = max(1, int(league_size * 0.10))
    return owners_count <= max_owners


def qualifies_for_scouting_performance(position: str, metrics: dict[str, Any]) -> bool:
    """Goal, assist, or (GK/DEF only) clean sheet."""
    if m(metrics, "goals") >= 1 or m(metrics, "assists") >= 1:
        return True
    pos = position.upper()
    if pos in {"GK", "DEF"} and m(metrics, "clean_sheets") >= 1:
        return True
    return False


def scouting_bonus(
    *,
    position: str,
    metrics: dict[str, Any],
    owners_count: int,
    league_size: int,
) -> float:
    if not is_differential_pick(owners_count, league_size):
        return 0.0
    if not qualifies_for_scouting_performance(position, metrics):
        return 0.0
    return SCOUTING_BONUS_POINTS
