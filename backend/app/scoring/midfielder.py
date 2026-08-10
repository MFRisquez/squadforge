"""Midfielder formula (v0.2 thresholds).

Base stays FPL-like. Extras use thresholds + a lower cap than DEF,
because MIDs already score more from goals (5) than attackers (4).
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

MID_EXTRAS_CAP = 3.0


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")
    cs = m(metrics, "clean_sheets")

    extras = capped_extras(
        {
            # Creation is the MID identity
            "key_passes_threshold": threshold_hit(m(metrics, "key_passes"), 4, 2.0),
            # Defensive work — slightly harder than rewarding every scraper
            "tackles_threshold": threshold_hit(m(metrics, "tackles"), 5, 1.0),
            "interceptions_threshold": threshold_hit(m(metrics, "interceptions"), 4, 1.0),
        },
        MID_EXTRAS_CAP,
        priority=["key_passes_threshold", "tackles_threshold", "interceptions_threshold"],
    )

    _, cards = card_points(metrics)

    breakdown = {
        "appearance": appearance_points(metrics),
        "goals": 5.0 * goals,
        "assists": 3.0 * assists,
        "clean_sheet": 1.0 * cs,
        **extras,
        **cards,
    }
    return sum(breakdown.values()), breakdown
