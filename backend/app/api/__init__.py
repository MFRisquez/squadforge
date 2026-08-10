from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.scoring import score_player
from app.sync import demo_metrics_for_positions

router = APIRouter(prefix="/api")


class ScoreRequest(BaseModel):
    position: str = Field(description="GK, DEF, MID, or ATT")
    metrics: dict = Field(default_factory=dict)
    owners_count: Optional[int] = Field(
        default=None, description="How many managers in the league own this player"
    )
    league_size: Optional[int] = Field(default=None, description="Managers in the private league")


@router.get("/health")
def health() -> dict:
    return {"ok": True, "service": "squadforge"}


@router.post("/score")
def score_endpoint(body: ScoreRequest) -> dict:
    """Try a formula live — useful while we tune weights together."""
    result = score_player(
        body.position,
        body.metrics,
        owners_count=body.owners_count,
        league_size=body.league_size,
    )
    return {
        "total": result.total,
        "breakdown": result.breakdown,
        "formula_version": result.formula_version,
        "position": result.position,
    }


@router.get("/demo-scores")
def demo_scores() -> dict:
    """One fake player per position so you can see points immediately."""
    out = {}
    for position, metrics in demo_metrics_for_positions().items():
        result = score_player(position, metrics)
        out[position] = {
            "metrics": metrics,
            "total": result.total,
            "breakdown": result.breakdown,
            "formula_version": result.formula_version,
        }
    return out
