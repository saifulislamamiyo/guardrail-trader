"""Keep-awake window: starts at KEEP_AWAKE_START (default 18:00 Sydney), ends 16:00 New York."""
import importlib.util
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest

from guardrail_trader.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("keep_awake", PROJECT_ROOT / "scripts" / "keep_awake.py")
ka = importlib.util.module_from_spec(spec); spec.loader.exec_module(ka)
SYD = ZoneInfo("Australia/Sydney")


def hours(y, mo, d, h, mi=0, start=None):
    return ka.seconds_to_keep_awake(datetime(y, mo, d, h, mi, tzinfo=SYD), start) / 3600


@pytest.fixture(autouse=True)
def default_start(monkeypatch):
    monkeypatch.delenv("KEEP_AWAKE_START", raising=False)


def test_default_start_is_1800():
    assert ka.start_time() == time(18, 0)
    assert hours(2026, 9, 22, 17, 59) == 0                     # Tue before the window
    assert hours(2026, 9, 22, 18, 0) == pytest.approx(12.0)   # Tue 18:00 -> Wed 06:00 (AEST, US EDT)


def test_evening_start_covers_both_slots():
    assert hours(2026, 9, 22, 20, 37) == pytest.approx(9 + 23 / 60)   # -> 06:00, after the 05:00-05:40 slot


@pytest.mark.parametrize("date,expected", [
    ((2026, 10, 6, 18, 0), 13.0),    # Sydney on AEDT from 4 Oct: ends 07:00
    ((2026, 11, 3, 18, 0), 14.0),    # US on EST from 1 Nov: ends 08:00 -> needs the 16 h guard
])
def test_daylight_saving_windows_are_not_blocked_by_the_guard(date, expected):
    assert hours(*date) == pytest.approx(expected)


def test_us_weekend_sessions_are_skipped():
    # Evening in Sydney is the early morning of the same day in New York.
    assert hours(2026, 9, 25, 20, 0) > 0     # Fri evening Sydney = Fri US session
    assert hours(2026, 9, 26, 20, 0) == 0    # Sat evening Sydney = Sat in NY: closed
    assert hours(2026, 9, 27, 20, 0) == 0    # Sun evening Sydney = Sun in NY: closed
    assert hours(2026, 9, 28, 20, 0) > 0     # Mon evening Sydney = Mon US session


def test_after_close_until_next_evening_is_outside():
    assert hours(2026, 9, 23, 7, 0) == 0     # Wed 07:00, after the 06:00 end
    assert hours(2026, 9, 23, 13, 0) == 0    # Wed afternoon


def test_start_is_configurable(monkeypatch):
    monkeypatch.setenv("KEEP_AWAKE_START", "23:00")
    assert hours(2026, 9, 22, 20, 37) == 0
    assert hours(2026, 9, 22, 23, 0) == pytest.approx(7.0)


@pytest.mark.parametrize("bad", ["25:00", "08:00", "7pm", "", "18:60"])
def test_bad_start_values_are_rejected(bad):
    with pytest.raises(ValueError):
        ka.start_time(bad)
