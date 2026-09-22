"""Keep the Mac awake only while tonight's trading runs need it.

Called by launchd (com.guardrail-trader.awake) at the start time, at load, and again on wake if
the start time was missed while asleep. Window:
    start  KEEP_AWAKE_START local time (HH:MM, default 18:00)
    end    16:00 America/New_York  (45 min after the 15:00-15:40 "close" slot)
The end follows both daylight-saving changes automatically:
    06:00 Sydney now, 07:00 from early Oct (AEDT), 08:00 from early Nov (US EST).
Nights before a US weekend day are skipped. Run with the project venv python (macOS privacy rules
block /usr/bin/python3 from ~/Documents under launchd).
"""
import os
import re
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
DEFAULT_START = "18:00"
END_NY = time(16, 0)
MAX_HOURS = 16  # sanity guard; an 18:00 start runs up to 14 h (to 08:00 Sydney when US is on EST)


def start_time(value: str | None = None) -> time:
    """Parse KEEP_AWAKE_START (HH:MM, 12:00-23:59). Anything else is an error, not a silent default."""
    v = (value if value is not None else os.getenv("KEEP_AWAKE_START", DEFAULT_START)).strip()
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", v)
    if not m or not (12 <= int(m[1]) <= 23 and int(m[2]) <= 59):
        raise ValueError(f"KEEP_AWAKE_START must be HH:MM between 12:00 and 23:59, got {v!r}")
    return time(int(m[1]), int(m[2]))


def seconds_to_keep_awake(now_local: datetime, start: time | None = None) -> int:
    """0 if outside the window, else seconds until 16:00 New York."""
    start = start or start_time()
    now_ny = now_local.astimezone(NY)
    end = now_ny.replace(hour=END_NY.hour, minute=END_NY.minute, second=0, microsecond=0)
    if now_ny >= end:
        end += timedelta(days=1)
    if end.weekday() >= 5:                      # the session it would cover is a US weekend
        return 0
    in_window = now_local.time() >= start or now_local.time() < time(12, 0)
    secs = int((end - now_ny).total_seconds())
    if not in_window or secs <= 0 or secs > MAX_HOURS * 3600:
        return 0
    return secs


def main() -> int:
    now = datetime.now().astimezone()
    secs = seconds_to_keep_awake(now)
    if not secs:
        print(f"{now:%a %H:%M} outside keep-awake window (starts {start_time():%H:%M}); not holding the Mac awake")
        return 0
    until = now + timedelta(seconds=secs)
    print(f"{now:%a %H:%M} keeping the Mac awake until {until:%a %H:%M} ({secs // 60} min)", flush=True)
    os.execv("/usr/bin/caffeinate", ["caffeinate", "-i", "-s", "-t", str(secs)])


if __name__ == "__main__":
    sys.exit(main())
