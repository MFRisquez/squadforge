"""Defender formula (v0.2 thresholds).

Base: FPL-like appearance / attack / clean sheet / cards.
Extras: threshold bonuses + goal-line clearance, capped so DEF doesn't dominate.

Umbrales calibrados con percentiles de temporada 2025/26 (bootstrap-static
agregados), NO con datos jornada-por-jornada reales, porque la temporada
2026/27 no había arrancado al momento de calibrar. Revisar y ajustar
después de GW3-4 de la temporada actual comparando contra la distribución
real de esa temporada.
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
# Cap matches MID/ATT so the four positions share the same extras ceiling.
DEF_EXTRAS_CAP = 3.0


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")
    cs = m(metrics, "clean_sheets")
    gc = m(metrics, "goals_conceded")

    extras = capped_extras(
        {
            # Volume defense → flat reward (FPL tackles; threshold calibrated ~p75)
            "tackles_threshold": threshold_hit(m(metrics, "tackles"), 2, 2.0),
            # Combined clearances + blocks + interceptions (FPL field)
            "cbi_threshold": threshold_hit(m(metrics, "cbi"), 8, 2.0),
            # No free/real data source exposes goal-line clearances yet (neither
            # FPL live nor API-Football). Keep the hook at 0 until we find one.
            "goal_line_clearance": 0.0,
        },
        DEF_EXTRAS_CAP,
        priority=[
            "goal_line_clearance",
            "tackles_threshold",
            "cbi_threshold",
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
