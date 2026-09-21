"""Keep the Mac awake only while tonight's trading runs need it.

Called by launchd (com.guardrail-trader.awake) at 23:00 local time, at load, and again on
wake if 23:00 was missed while asleep. Window:
    start  23:00 local (Sydney)
    end    16:00 America/New_York  (45 min after the 15:00-15:40 "close" slot)
The end follows both daylight-saving changes automatically:
    06:00 Sydney now, 07:00 from early Oct (AEDT), 08:00 from early Nov (US EST).
Nights before a US weekend day are skipped. Run with the project venv python (macOS privacy rules block /usr/bin/python3 from ~/Documents under launchd).
"""
import os
import sys
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
START_LOCAL = time(23, 0)
END_NY = time(16, 0)
MAX_HOURS = 12  # sanity guard: never hold the Mac awake longer than this


def seconds_to_keep_awake(now_local: datetime) -> int:
    """0 if outside the window, else seconds until 16:00 New York."""
    now_ny = now_local.astimezone(NY)
    end = now_ny.replace(hour=END_NY.hour, minute=END_NY.minute, second=0, microsecond=0)
    if now_ny >= end:
        end += timedelta(days=1)
    if end.weekday() >= 5:                      # the session it would cover is a US weekend
        return 0
    in_window = now_local.time() >= START_LOCAL or now_local.time() < time(12, 0)
    secs = int((end - now_ny).total_seconds())
    if not in_window or secs <= 0 or secs > MAX_HOURS * 3600:
        return 0
    return secs


def main() -> int:
    now = datetime.now().astimezone()
    secs = seconds_to_keep_awake(now)
    if not secs:
        print(f"{now:%a %H:%M} outside keep-awake window; not holding the Mac awake")
        return 0
    until = now + timedelta(seconds=secs)
    print(f"{now:%a %H:%M} keeping the Mac awake until {until:%a %H:%M} ({secs // 60} min)", flush=True)
    os.execv("/usr/bin/caffeinate", ["caffeinate", "-i", "-s", "-t", str(secs)])


if __name__ == "__main__":
    sys.exit(main())
