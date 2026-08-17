"""Checks for threshold formulas + scouting bonus."""

from app.scoring import score_player
from app.scoring.common import capped_extras, threshold_hit
from app.scoring.scouting import is_differential_pick, scouting_bonus
from app.sync import demo_metrics_for_positions


def test_demo_positions_score():
    for position, metrics in demo_metrics_for_positions().items():
        result = score_player(position, metrics)
        assert result.total > 0
        assert result.position == position
        assert "appearance" in result.breakdown


def test_def_thresholds_and_cap():
    metrics = {
        "minutes": 90,
        "clean_sheets": 1,
        "tackles": 2,
        "cbi": 8,
        "goal_line_clearances": 1,  # ignored: no real data source yet
    }
    result = score_player("DEF", metrics)
    # Base 2 + CS 4 = 6; extras: tackles 2 + cbi 2 = 4 → capped to 3; GLC always 0
    assert result.breakdown.get("goal_line_clearance", 0) == 0.0
    assert result.breakdown.get("tackles_threshold", 0) == 2.0
    assert result.breakdown.get("cbi_threshold", 0) > 0
    extras = (
        result.breakdown.get("tackles_threshold", 0)
        + result.breakdown.get("cbi_threshold", 0)
        + result.breakdown.get("goal_line_clearance", 0)
    )
    assert extras <= 3.0 + 1e-6
    assert abs(result.total - (6 + extras)) < 1e-6


def test_mid_thresholds_clinical_and_cap():
    metrics = {
        "minutes": 90,
        "goals": 1,
        "xg": 0.4,  # goals - xg = 0.6 ≥ 0.5 → clinical
        "creativity": 26,
        "tackles": 2,
        "cbi": 3,
    }
    result = score_player("MID", metrics)
    # Base: appearance 2 + goal 5 = 7; extras raw 2+1+1+1=5 → capped to 3
    assert result.breakdown.get("creativity_threshold", 0) == 2.0
    assert result.breakdown.get("clinical_bonus", 0) == 1.0
    extras = (
        result.breakdown.get("creativity_threshold", 0)
        + result.breakdown.get("clinical_bonus", 0)
        + result.breakdown.get("tackles_threshold", 0)
        + result.breakdown.get("cbi_threshold", 0)
    )
    assert extras <= 3.0 + 1e-6
    assert abs(result.total - (7 + extras)) < 1e-6

    no_clinical = score_player(
        "MID",
        {**metrics, "xg": 0.6},  # goals - xg = 0.4 < 0.5
    )
    assert no_clinical.breakdown.get("clinical_bonus", 0) == 0.0


def test_att_threat_clinical_and_cap():
    metrics = {
        "minutes": 90,
        "goals": 1,
        "xg": 0.4,  # goals - xg = 0.6 ≥ 0.5 → clinical
        "threat": 33,
    }
    result = score_player("ATT", metrics)
    # Base: appearance 2 + goal 4 = 6; extras: threat 2 + clinical 1 = 3 (at cap)
    assert result.breakdown.get("threat_threshold", 0) == 2.0
    assert result.breakdown.get("clinical_bonus", 0) == 1.0
    extras = (
        result.breakdown.get("threat_threshold", 0)
        + result.breakdown.get("clinical_bonus", 0)
    )
    assert extras <= 3.0 + 1e-6
    assert abs(result.total - (6 + extras)) < 1e-6

    no_clinical = score_player("ATT", {**metrics, "xg": 0.6})
    assert no_clinical.breakdown.get("clinical_bonus", 0) == 0.0


def test_threshold_helper():
    assert threshold_hit(5, 5, 2) == 2
    assert threshold_hit(4, 5, 2) == 0


def test_gk_saves_progressive_and_5plus_bonus():
    """+1 per 3 saves, plus flat +2 when saves >= 5 (via threshold_hit)."""
    four = score_player("GK", {"minutes": 90, "saves": 4})
    five = score_player("GK", {"minutes": 90, "saves": 5})
    six = score_player("GK", {"minutes": 90, "saves": 6})

    assert four.breakdown["saves"] == 1.0  # 4 // 3
    assert four.breakdown.get("saves_bonus_5plus", 0) == 0.0

    assert five.breakdown["saves"] == 1.0  # 5 // 3
    assert five.breakdown["saves_bonus_5plus"] == 2.0
    assert five.total == four.total + 2.0

    assert six.breakdown["saves"] == 2.0  # 6 // 3
    assert six.breakdown["saves_bonus_5plus"] == 2.0


def test_cameo_with_goal_gets_full_appearance():
    blank_sub = score_player("ATT", {"minutes": 20, "goals": 0, "assists": 0})
    # xg=1 so clinical_bonus does not fire; this test isolates appearance only
    hero_sub = score_player("ATT", {"minutes": 20, "goals": 1, "assists": 0, "xg": 1.0})
    assert blank_sub.breakdown["appearance"] == 1
    assert hero_sub.breakdown["appearance"] == 2
    assert hero_sub.breakdown.get("clinical_bonus", 0) == 0.0
    # Goal points are separate; cameo only upgrades appearance 1 → 2
    assert hero_sub.total == blank_sub.total - 1 + 2 + 4


def test_capped_extras_priority():
    capped = capped_extras(
        {
            "tackles_threshold": 2.0,
            "interceptions_threshold": 1.0,
            "blocks_threshold": 1.0,
            "clearances_threshold": 1.0,
            "goal_line_clearance": 1.0,
        },
        cap=4.0,
        priority=[
            "goal_line_clearance",
            "tackles_threshold",
            "interceptions_threshold",
            "blocks_threshold",
            "clearances_threshold",
        ],
    )
    assert sum(capped.values()) == 4.0
    assert capped["goal_line_clearance"] == 1.0
    assert capped["tackles_threshold"] == 2.0
    assert capped["clearances_threshold"] == 0.0


def test_scouting_unique_owner_with_goal():
    bonus = scouting_bonus(
        position="ATT",
        metrics={"goals": 1},
        owners_count=1,
        league_size=8,
    )
    assert bonus == 2
    assert is_differential_pick(1, 8) is True
    assert is_differential_pick(2, 8) is False


def test_scouting_cs_only_for_back_line():
    assert (
        scouting_bonus(
            position="MID",
            metrics={"clean_sheets": 1},
            owners_count=1,
            league_size=8,
        )
        == 0
    )
    assert (
        scouting_bonus(
            position="DEF",
            metrics={"clean_sheets": 1},
            owners_count=1,
            league_size=8,
        )
        == 2
    )


def test_score_player_includes_scouting_when_ownership_passed():
    result = score_player(
        "ATT",
        {"minutes": 90, "goals": 1, "threat": 10},
        owners_count=1,
        league_size=7,
    )
    assert result.breakdown.get("scouting_bonus") == 2
    assert result.total >= 8  # 2 appearance + 4 goal + 2 scouting
