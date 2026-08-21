"""Match clock + appearance points sanity for live GW display."""

from datetime import datetime, timedelta, timezone

from app.scoring.common import appearance_points
from app.services.fixtures import estimate_match_clock


def test_appearance_points_any_minutes_is_one():
    assert appearance_points({"minutes": 0}) == 0
    assert appearance_points({"minutes": 1}) == 1
    assert appearance_points({"minutes": 59}) == 1
    assert appearance_points({"minutes": 60}) == 2
    assert appearance_points({"minutes": 10, "goals": 1}) == 2


def test_estimate_match_clock_live_and_ft():
    kick = datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc)
    now = kick + timedelta(minutes=14)
    assert (
        estimate_match_clock(
            kickoff_at=kick.isoformat().replace("+00:00", "Z"),
            started=True,
            finished=False,
            now=now,
        )
        == "14'"
    )
    assert (
        estimate_match_clock(
            kickoff_at=kick.isoformat().replace("+00:00", "Z"),
            started=True,
            finished=True,
            now=now,
        )
        == "FT"
    )
    assert (
        estimate_match_clock(
            kickoff_at=kick.isoformat().replace("+00:00", "Z"),
            started=False,
            finished=False,
            now=now,
        )
        is None
    )
