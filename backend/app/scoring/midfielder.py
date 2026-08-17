"""Midfielder formula (v0.2 thresholds).

Base stays FPL-like. Extras use thresholds + a lower cap than DEF,
because MIDs already score more from goals (5) than attackers (4).

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

MID_EXTRAS_CAP = 3.0


def _clinical_bonus(goals: float, xg: float) -> float:
    """+1 when a scorer beats their own match xG by ≥0.5."""
    if goals >= 1 and (goals - xg) >= 0.5:
        return 1.0
    return 0.0


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")
    cs = m(metrics, "clean_sheets")
    xg = m(metrics, "xg")

    extras = capped_extras(
        {
            # Creation via FPL ICT creativity (replaces key_passes)
            "creativity_threshold": threshold_hit(m(metrics, "creativity"), 26, 2.0),
            "clinical_bonus": _clinical_bonus(goals, xg),
            "tackles_threshold": threshold_hit(m(metrics, "tackles"), 2, 1.0),
            # Combined clearances + blocks + interceptions (FPL field)
            "cbi_threshold": threshold_hit(m(metrics, "cbi"), 3, 1.0),
        },
        MID_EXTRAS_CAP,
        priority=[
            "creativity_threshold",
            "clinical_bonus",
            "tackles_threshold",
            "cbi_threshold",
        ],
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
