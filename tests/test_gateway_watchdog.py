"""When the watchdog restarts the gateway - and, more importantly, when it refuses to."""
import importlib.util
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from guardrail_trader.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("gw", PROJECT_ROOT / "scripts" / "gateway_watchdog.py")
gw = importlib.util.module_from_spec(spec); spec.loader.exec_module(gw)
NOW = datetime(2026, 9, 24, 6, 0, tzinfo=ZoneInfo("Australia/Sydney"))


def decide(statuses, state=None, **kw):
    opts = {"min_bad": 2, "cooldown_min": 30, "max_per_day": 4, **kw}
    return gw.should_restart(statuses, state or {}, NOW, **opts)


def test_restarts_after_two_consecutive_gateway_failures():
    go, why = decide(["market_data_unavailable", "market_data_unavailable", "ok"])
    assert go and "gateway failures" in why


def test_mixed_gateway_failures_also_count():
    assert decide(["broker_not_ready", "market_data_unavailable"])[0]


@pytest.mark.parametrize("statuses", [
    [],                                        # nothing has run
    ["market_data_unavailable"],               # only one so far: wait
    ["ok", "market_data_unavailable"],         # newest run was fine
    ["reconcile_failed", "reconcile_failed"],  # a human's problem, not the gateway's
    ["error", "error"],                        # generic errors: could be anything
])
def test_does_not_restart(statuses):
    assert decide(statuses)[0] is False


def test_cooldown_blocks_a_restart_loop():
    state = {"last_restart": (NOW - timedelta(minutes=5)).isoformat()}
    go, why = decide(["market_data_unavailable"] * 2, state)
    assert not go and "cooldown" in why


def test_cooldown_expires():
    state = {"last_restart": (NOW - timedelta(minutes=31)).isoformat()}
    assert decide(["market_data_unavailable"] * 2, state)[0]


def test_daily_cap_hands_over_to_a_human():
    state = {"restarts": {"2026-09-24": 4}}
    go, why = decide(["market_data_unavailable"] * 2, state)
    assert not go and "human" in why


def test_reads_only_real_runs_from_the_journal(tmp_path):
    db = tmp_path / "j.sqlite"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE runs (id INTEGER PRIMARY KEY, mode TEXT, status TEXT)")
    con.executemany("INSERT INTO runs(mode,status) VALUES(?,?)", [
        ("paper", "ok"), ("paper", "market_data_unavailable"),
        ("paper-dry-fake", "dry_run"), ("paper", "broker_not_ready")])
    con.commit(); con.close()
    assert gw.recent_statuses(db) == ["broker_not_ready", "market_data_unavailable", "ok"]


def test_missing_journal_is_not_a_reason_to_restart(tmp_path):
    assert gw.recent_statuses(tmp_path / "nope.sqlite") == []
    assert decide(gw.recent_statuses(tmp_path / "nope.sqlite"))[0] is False
