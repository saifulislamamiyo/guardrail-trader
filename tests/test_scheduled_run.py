"""Which run outcomes end a slot, and which are worth retrying inside its window."""
import importlib.util

import pytest

from guardrail_trader.config import PROJECT_ROOT

spec = importlib.util.spec_from_file_location("scheduled_run", PROJECT_ROOT / "scripts" / "scheduled_run.py")
sr = importlib.util.module_from_spec(spec); spec.loader.exec_module(sr)


@pytest.mark.parametrize("rc,done", [
    (0, True),    # ran, market closed, halted, limits reached
    (3, True),    # reconciliation failed: needs a human, retrying won't help
    (1, False),   # error
    (2, False),   # gateway connected but serving no data (nightly re-login): retry
])
def test_slot_done(rc, done):
    assert sr.slot_done(rc) is done


def test_a_slot_retries_at_most_max_attempts():
    assert sr.MAX_ATTEMPTS == 3
