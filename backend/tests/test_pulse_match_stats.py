"""PulseLive free match stats (/stats/match/{id}) → team_stats mapping."""

from __future__ import annotations

import json
from pathlib import Path

from app.services import pl_content

FIXTURE = Path(__file__).parent / "fixtures_data" / "pulse_stats_match_ars_cov.json"


def test_map_pulse_match_stats_ars_cov_possession_and_shots():
    raw = json.loads(FIXTURE.read_text(encoding="utf-8"))
    out = pl_content.map_pulse_match_stats(raw)
    assert out is not None
    assert out["source"] == "pulselive"
    assert out["possession"] == {"home": "64%", "away": "36%"}
    assert out["shots_on_target"] == {"home": 6, "away": 1}
    assert out["chances_created"] == {"home": 20, "away": 4}
    assert out["passes_accurate"] == {"home": 565, "away": 271}
    assert out["duels_won"] == {"home": 37, "away": 34}
    assert out["fouls"] == {"home": 10, "away": 13}
    assert out["expected_goals"] == {"home": None, "away": None}


def test_map_pulse_match_stats_empty_payload():
    assert pl_content.map_pulse_match_stats({}) is None
    assert pl_content.map_pulse_match_stats({"entity": {}, "data": {}}) is None
