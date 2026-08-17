"""Attacker formula (v0.2 thresholds).

Threat (FPL ICT) drives ATT extras so volume/quality rewards map to a
real live field; clinical finishing competes under the same extras cap.

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

ATT_EXTRAS_CAP = 3.0


def _clinical_bonus(goals: float, xg: float) -> float:
    """+1 when a scorer beats their own match xG by ≥0.5."""
    if goals >= 1 and (goals - xg) >= 0.5:
        return 1.0
    return 0.0


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")
    xg = m(metrics, "xg")

    extras = capped_extras(
        {
            # FPL ICT threat replaces shots / shots_on_target
            "threat_threshold": threshold_hit(m(metrics, "threat"), 33, 2.0),
            "clinical_bonus": _clinical_bonus(goals, xg),
        },
        ATT_EXTRAS_CAP,
        priority=["threat_threshold", "clinical_bonus"],
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
