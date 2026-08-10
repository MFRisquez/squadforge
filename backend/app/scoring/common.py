"""Shared helpers for position formulas."""

from __future__ import annotations

from typing import Any


def m(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(metrics.get(key, default) or 0)
    except (TypeError, ValueError):
        return default


def appearance_points(metrics: dict[str, Any]) -> float:
    """Playing-time points.

    - 60'+ → 2
    - Any minutes + goal or assist → 2 (reward impactful cameos)
    - Any other minutes → 1
    - Did not play → 0
    """
    minutes = m(metrics, "minutes")
    if minutes <= 0:
        return 0.0
    if minutes >= 60:
        return 2.0
    if m(metrics, "goals") >= 1 or m(metrics, "assists") >= 1:
        return 2.0
    return 1.0


def card_points(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    yc = m(metrics, "yellow_cards")
    rc = m(metrics, "red_cards")
    own = m(metrics, "own_goals")
    breakdown = {
        "yellow_cards": -1.0 * yc,
        "red_cards": -3.0 * rc,
        "own_goals": -2.0 * own,
    }
    return sum(breakdown.values()), breakdown


def threshold_hit(value: float, minimum: float, points: float) -> float:
    """If value reaches the floor, award flat points (not per-action)."""
    return points if value >= minimum else 0.0


def capped_extras(
    parts: dict[str, float],
    cap: float,
    *,
    priority: list[str] | None = None,
) -> dict[str, float]:
    """Keep flavor stats from outrunning goals/assists/clean sheets.

    When the sum would exceed `cap`, keep lines in `priority` order first
    (then highest value, then name). Dropped lines stay in the breakdown as 0.
    """
    priority = priority or []
    rank = {key: index for index, key in enumerate(priority)}

    def sort_key(item: tuple[str, float]) -> tuple[int, float, str]:
        key, value = item
        return (rank.get(key, len(priority)), -value, key)

    ordered = sorted(parts.items(), key=sort_key)
    out = {key: 0.0 for key in parts}
    remaining = cap
    for key, value in ordered:
        if value <= 0 or remaining <= 0:
            continue
        take = min(value, remaining)
        out[key] = take
        remaining -= take
    return out
