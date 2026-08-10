"""Defender formula (v0.2 thresholds).

Base: FPL-like appearance / attack / clean sheet / cards.
Extras: threshold bonuses + goal-line clearance, capped so DEF doesn't dominate.
"""

from __future__ import annotations

from typing import Any

from app.scoring.common import (
    appearance_points,
    capped_extras,
    card_points,
    m,
    threshold_hit,
)

# Extras should feel meaningful but rarely beat a goal (6) on their own.
DEF_EXTRAS_CAP = 4.0


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")
    cs = m(metrics, "clean_sheets")
    gc = m(metrics, "goals_conceded")

    extras = capped_extras(
        {
            # User example: volume defense → flat reward
            "tackles_threshold": threshold_hit(m(metrics, "tackles"), 5, 2.0),
            "interceptions_threshold": threshold_hit(m(metrics, "interceptions"), 4, 1.0),
            "blocks_threshold": threshold_hit(m(metrics, "blocks"), 3, 1.0),
            "clearances_threshold": threshold_hit(m(metrics, "clearances"), 10, 1.0),
            # "Save on the line" / last-ditch clearance
            "goal_line_clearance": threshold_hit(m(metrics, "goal_line_clearances"), 1, 1.0),
        },
        DEF_EXTRAS_CAP,
        priority=[
            "goal_line_clearance",
            "tackles_threshold",
            "interceptions_threshold",
            "blocks_threshold",
            "clearances_threshold",
        ],
    )

    _, cards = card_points(metrics)

    breakdown = {
        "appearance": appearance_points(metrics),
        "goals": 6.0 * goals,
        "assists": 3.0 * assists,
        "clean_sheet": 4.0 * cs,
        "goals_conceded": -1.0 * (gc // 2),
        **extras,
        **cards,
    }
    return sum(breakdown.values()), breakdown
