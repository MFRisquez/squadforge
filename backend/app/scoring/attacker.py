"""Attacker formula (v0.2 thresholds).

Shot volume/quality uses thresholds so a 1-shot brace isn't drowned out
by empty 8-shot games, and so ATT extras don't quietly beat MID goals.
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

ATT_EXTRAS_CAP = 3.0


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")

    extras = capped_extras(
        {
            # Quality first
            "shots_on_target_threshold": threshold_hit(m(metrics, "shots_on_target"), 3, 2.0),
            # Volume only if they really pepper the goal
            "shots_threshold": threshold_hit(m(metrics, "shots"), 6, 1.0),
        },
        ATT_EXTRAS_CAP,
        priority=["shots_on_target_threshold", "shots_threshold"],
    )

    _, cards = card_points(metrics)

    breakdown = {
        "appearance": appearance_points(metrics),
        "goals": 4.0 * goals,
        "assists": 3.0 * assists,
        **extras,
        **cards,
    }
    return sum(breakdown.values()), breakdown
