"""Data sync stubs.

v1: manual / demo metrics for testing formulas.
v2: plug in official FPL API and/or API-Football.

Design rule: sync writes MatchEvent rows; scoring job reads them.
Never compute points only inside the phone UI.
"""

from __future__ import annotations

from typing import Any


# Official FPL endpoints are public but undocumented — fine for private hobbies.
FPL_BOOTSTRAP = "https://fantasy.premierleague.com/api/bootstrap-static/"
FPL_EVENT_LIVE = "https://fantasy.premierleague.com/api/event/{gw}/live/"


def demo_metrics_for_positions() -> dict[str, dict[str, Any]]:
    """Tiny fake GW so you can test scoring without an API key."""
    return {
        "GK": {
            "minutes": 90,
            "saves": 7,
            "clean_sheets": 1,
            "goals_conceded": 0,
            "yellow_cards": 0,
        },
        "DEF": {
            "minutes": 90,
            "goals": 0,
            "assists": 0,
            "clean_sheets": 1,
            "goals_conceded": 0,
            "tackles": 6,
            "interceptions": 4,
            "blocks": 3,
            "clearances": 11,
            "goal_line_clearances": 1,
        },
        "MID": {
            "minutes": 78,
            "goals": 1,
            "assists": 1,
            "xg": 0.3,
            "creativity": 28,
            "tackles": 2,
            "cbi": 3,
            "clean_sheets": 0,
        },
        "ATT": {
            "minutes": 90,
            "goals": 1,
            "assists": 0,
            "shots": 7,
            "shots_on_target": 3,
        },
    }


async def fetch_fpl_bootstrap(client) -> dict[str, Any]:
    """Placeholder for real player list sync — returns JSON from FPL."""
    response = await client.get(FPL_BOOTSTRAP, timeout=30.0)
    response.raise_for_status()
    return response.json()
