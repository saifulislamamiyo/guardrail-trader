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


class FakeChild:
    """Stands in for the caffeinate subprocess."""
    def __init__(self, argv):
        self.argv, self.alive, self.terminated = argv, True, False
    def poll(self):
        return None if self.alive else 0
    def terminate(self):
        self.alive, self.terminated = False, True
    def wait(self, timeout=None):
        return 0


class FakeClock:
    """Wall clock that only moves when the loop sleeps, plus an optional jump (the Mac sleeping)."""
    def __init__(self, t0, jump_at=None, jump_to=None):
        self.t, self.jump_at, self.jump_to, self.sleeps = t0, jump_at, jump_to, 0
    def now(self):
        return self.t
    def sleep(self, secs):
        self.sleeps += 1
        self.t += secs
        if self.jump_at is not None and self.t >= self.jump_at:
            self.t, self.jump_at = self.jump_to, None


def run_hold(end, clock, children):
    def popen(argv):
        children.append(FakeChild(argv)); return children[-1]
    return ka.hold_until(end, popen=popen, now=clock.now, sleep=clock.sleep, poll_secs=30)


def test_hold_has_no_caffeinate_timer_and_is_tied_to_this_process():
    kids = []
    run_hold(100, FakeClock(0), kids)
    argv = kids[0].argv
    assert "-t" not in argv                                 # -t does not advance while the Mac sleeps
    assert argv[argv.index("-w") + 1] == str(__import__("os").getpid())   # dies with the launcher
    assert "-i" in argv and "-s" in argv


def test_hold_releases_caffeinate_at_the_wall_clock_end():
    kids = []
    clock = FakeClock(0)
    assert run_hold(100, clock, kids) == 0
    assert kids[0].terminated and clock.t == 100


def test_hold_ends_promptly_when_the_mac_slept_past_the_end():
    """The 1 Oct bug: asleep for hours, the old timer never expired. Wall clock must."""
    kids = []
    clock = FakeClock(0, jump_at=30, jump_to=10_000)       # sleeps after the first 30 s tick
    run_hold(3600, clock, kids)
    assert kids[0].terminated
    assert clock.sleeps == 1                                # no further polling once past the end


def test_hold_exits_if_caffeinate_dies_and_does_not_signal_a_dead_child():
    kids = []
    clock = FakeClock(0)
    orig_sleep = clock.sleep
    def sleep_then_die(secs):
        orig_sleep(secs); kids[0].alive = False
    clock.sleep = sleep_then_die
    run_hold(3600, clock, kids)
    assert not kids[0].terminated and clock.sleeps == 1


def test_hold_restores_the_previous_sigterm_handler():
    import signal
    before = signal.getsignal(signal.SIGTERM)
    run_hold(10, FakeClock(0), [])
    assert signal.getsignal(signal.SIGTERM) is before
