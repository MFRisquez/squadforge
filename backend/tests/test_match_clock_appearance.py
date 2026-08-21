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


def _clock(kick: datetime, minutes: int, *, finished: bool = False, started: bool = True):
    return estimate_match_clock(
        kickoff_at=kick.isoformat().replace("+00:00", "Z"),
        started=started,
        finished=finished,
        now=kick + timedelta(minutes=minutes),
    )


def test_estimate_match_clock_live_and_ft():
    kick = datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc)
    assert _clock(kick, 14) == "14'"
    assert _clock(kick, 14, finished=True) == "FT"
    assert _clock(kick, 14, started=False) is None


def test_estimate_match_clock_half_time_and_stoppage_caps():
    kick = datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc)
    assert _clock(kick, 45) == "45'"
    assert _clock(kick, 48) == "45+3'"
    # Wall clock deep into the HT window must not keep ticking 45+10'
    assert _clock(kick, 55) == "MT"
    assert _clock(kick, 59) == "MT"
    assert _clock(kick, 70) == "55'"
    assert _clock(kick, 105) == "90'"
    assert _clock(kick, 108) == "90+3'"
    assert _clock(kick, 130) == "90+10'"  # capped until FPL marks finished
    assert _clock(kick, 130, finished=True) == "FT"
