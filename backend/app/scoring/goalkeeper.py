"""Goalkeeper formula (draft v0.1).

KPIs we expect from APIs (usually easy):
  minutes, goals, assists, clean_sheets, goals_conceded,
  saves, penalties_saved, penalties_missed, yellow_cards, red_cards, own_goals
"""

from __future__ import annotations

from typing import Any

from app.scoring.common import appearance_points, card_points, m, threshold_hit


def score(metrics: dict[str, Any]) -> tuple[float, dict[str, float]]:
    goals = m(metrics, "goals")
    assists = m(metrics, "assists")
    cs = m(metrics, "clean_sheets")
    gc = m(metrics, "goals_conceded")
    saves = m(metrics, "saves")
    pen_saved = m(metrics, "penalties_saved")
    pen_missed = m(metrics, "penalties_missed")

    _, cards = card_points(metrics)

    breakdown = {
        "appearance": appearance_points(metrics),
        "goals": 6.0 * goals,  # rare GK goals
        "assists": 3.0 * assists,
        "clean_sheet": 4.0 * cs,
        # -1 per 2 goals conceded (FPL-like)
        "goals_conceded": -1.0 * (gc // 2),
        "saves": 1.0 * (saves // 3),  # +1 per 3 saves
        # Extra flat bonus when the keeper makes a big save haul
        "saves_bonus_5plus": threshold_hit(saves, 5, 2.0),
        "penalties_saved": 5.0 * pen_saved,
        "penalties_missed": -2.0 * pen_missed,
        **cards,
    }
    return sum(breakdown.values()), breakdown
