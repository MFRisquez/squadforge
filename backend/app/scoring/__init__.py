"""Scoring entrypoint.

Flow:
  raw metrics dict → pick formula by position → total + breakdown
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from app.config import settings
from app.scoring import attacker, defender, goalkeeper, midfielder
from app.scoring.scouting import scouting_bonus

Position = str  # GK | DEF | MID | ATT


@dataclass
class ScoreResult:
    total: float
    breakdown: dict[str, float]
    formula_version: str
    position: str


FORMULAS = {
    "GK": goalkeeper.score,
    "DEF": defender.score,
    "MID": midfielder.score,
    "ATT": attacker.score,
}


def score_player(
    position: Position,
    metrics: dict[str, Any],
    *,
    owners_count: int | None = None,
    league_size: int | None = None,
) -> ScoreResult:
    """metrics example: {"minutes": 90, "goals": 1, "assists": 0, ...}

    Optional ownership fields unlock the +2 scouting bonus.
    """
    fn = FORMULAS.get(position.upper())
    if not fn:
        raise ValueError(f"Unknown position: {position}")
    total, breakdown = fn(metrics)
    breakdown = {key: round(float(value), 2) for key, value in dict(breakdown).items()}

    if owners_count is not None and league_size is not None:
        bonus = scouting_bonus(
            position=position,
            metrics=metrics,
            owners_count=owners_count,
            league_size=league_size,
        )
        if bonus:
            breakdown["scouting_bonus"] = round(bonus, 2)

    total = round(sum(breakdown.values()), 2)
    return ScoreResult(
        total=total,
        breakdown=breakdown,
        formula_version=settings.formula_version,
        position=position.upper(),
    )


def result_to_dict(result: ScoreResult) -> dict[str, Any]:
    return asdict(result)
