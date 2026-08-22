"""Match clock + appearance points sanity for live GW display."""

from datetime import datetime, timedelta, timezone

from app.scoring.common import appearance_points
from app.services.fixtures import estimate_match_clock
from app.services.pl_content import format_pulse_clock


def test_appearance_points_any_minutes_is_one():
    assert appearance_points({"minutes": 0}) == 0
    assert appearance_points({"minutes": 1}) == 1
    assert appearance_points({"minutes": 59}) == 1
    assert appearance_points({"minutes": 60}) == 2
    assert appearance_points({"minutes": 10, "goals": 1}) == 2


def _clock(
    kick: datetime,
    minutes: int,
    *,
    finished: bool = False,
    started: bool = True,
    fpl_minutes: int | None = None,
    pulse_clock: str | None = None,
):
    return estimate_match_clock(
        kickoff_at=kick.isoformat().replace("+00:00", "Z"),
        started=started,
        finished=finished,
        now=kick + timedelta(minutes=minutes),
        fpl_minutes=fpl_minutes,
        pulse_clock=pulse_clock,
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


def test_format_pulse_clock_strips_seconds():
    assert format_pulse_clock({"label": "90+7'00"}) == "90+7'"
    assert format_pulse_clock({"label": "45'00"}) == "45'"
    assert format_pulse_clock({"label": "67'"}) == "67'"
    assert format_pulse_clock({"label": "HT"}) == "MT"
    assert format_pulse_clock(None) is None


def test_estimate_match_clock_prefers_pulse_then_fpl():
    kick = datetime(2026, 8, 21, 17, 0, tzinfo=timezone.utc)
    # Pulse Match Centre wins over wall estimate / FPL minute.
    assert _clock(kick, 100, fpl_minutes=79, pulse_clock="90+7'") == "90+7'"
    # FPL minutes beat a lagging wall estimate (wall thinks ~100' → 90+N).
    assert _clock(kick, 100, fpl_minutes=79) == "79'"
    assert _clock(kick, 48, fpl_minutes=45) == "45+3'"
    assert _clock(kick, 55, fpl_minutes=45) == "MT"
    assert _clock(kick, 110, fpl_minutes=90) == "90+5'"
