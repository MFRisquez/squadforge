"""Fixture scoreboard scorers + Pulse goal minutes."""

from __future__ import annotations

from app.services import fixtures as fixtures_svc
from app.services import pl_content


def test_grouped_scorer_labels_joins_minutes():
    lines = [
        {"name": "Muñoz", "minute": "34'", "own_goal": False},
        {"name": "Muñoz", "minute": "57'", "own_goal": False},
        {"name": "Elanga", "minute": "5'", "own_goal": False},
        {"name": "Willock (OG)", "minute": None, "own_goal": True},
    ]
    assert fixtures_svc.grouped_scorer_labels(lines) == [
        "Muñoz 34', 57'",
        "Elanga 5'",
        "Willock (OG)",
    ]


def test_apply_pulse_minutes_matches_web_name():
    lines = [
        {"name": "Szoboszlai", "minute": None, "own_goal": False},
        {"name": "Elanga", "minute": None, "own_goal": False},
    ]
    pulse = [
        {"side": "away", "name": "Dominik Szoboszlai", "minute": "90+9'"},
        {"side": "home", "name": "Anthony Elanga", "minute": "5'"},
    ]
    out = fixtures_svc._apply_pulse_minutes(lines, pulse, side="away")
    assert out[0]["minute"] == "90+9'"
    assert out[1]["minute"] is None  # wrong side
    out_h = fixtures_svc._apply_pulse_minutes(
        [{"name": "Elanga", "minute": None, "own_goal": False}],
        pulse,
        side="home",
    )
    assert out_h[0]["minute"] == "5'"


def test_parse_pulse_textstream_goals_new_liv():
    raw = {
        "events": {
            "content": [
                {
                    "type": "goal",
                    "time": {"label": "05"},
                    "text": "Goal! Newcastle United 1, Liverpool 0. Anthony Elanga (Newcastle United) right footed shot.",
                },
                {
                    "type": "penalty goal",
                    "time": {"label": "90+9"},
                    "text": "Goal! Newcastle United 2, Liverpool 2. Dominik Szoboszlai (Liverpool) converts the penalty.",
                },
            ]
        }
    }
    goals = pl_content.parse_pulse_textstream_goals(raw, home_abbr="NEW", away_abbr="LIV")
    assert goals == [
        {"side": "home", "name": "Anthony Elanga", "minute": "5'", "own_goal": False},
        {"side": "away", "name": "Dominik Szoboszlai", "minute": "90+9'", "own_goal": False},
    ]


def test_format_pulse_goal_minute():
    assert pl_content.format_pulse_goal_minute("05") == "5'"
    assert pl_content.format_pulse_goal_minute("90+9") == "90+9'"
    assert pl_content.format_pulse_goal_minute("90+9'00") == "90+9'"


def test_fpl_row_finished_includes_provisional():
    assert fixtures_svc._fpl_row_finished(
        {"finished": False, "finished_provisional": True}
    )
    assert fixtures_svc._fpl_row_finished({"finished": True})
    assert not fixtures_svc._fpl_row_fully_finished(
        {"finished": False, "finished_provisional": True}
    )
