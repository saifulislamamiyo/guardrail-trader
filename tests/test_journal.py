from types import SimpleNamespace

import pytest

from guardrail_trader.journal import Journal
from guardrail_trader.risk import Decision, Proposal


@pytest.fixture
def j(tmp_path):
    jr = Journal(tmp_path / "j.sqlite")
    jr.init_budget(100.0, "AUD")
    yield jr
    jr.close()


def test_budget_initialised_once(j):
    assert j.cash_base() == 100.0 and j.base_currency() == "AUD"
    with pytest.raises(RuntimeError):
        j.init_budget(100.0, "AUD")


def test_fills_update_virtual_cash_and_holdings(j):
    j.record_fill("AAA", "USD", "BUY", 2, 10.0, commission=1.0, fx_to_base=1.5)   # -(20+1)*1.5 = -31.5
    assert j.cash_base() == pytest.approx(68.5)
    assert j.holdings_qty() == {"AAA:USD": 2}
    j.record_fill("AAA", "USD", "SELL", 2, 11.0, commission=1.0, fx_to_base=1.5)  # +(22-1)*1.5 = 31.5
    assert j.cash_base() == pytest.approx(100.0)
    assert j.holdings_qty() == {}


def test_portfolio_state_values_holdings_and_tracks_peak(j):
    j.record_fill("BBB", "AUD", "BUY", 4, 5.0, commission=0.5, fx_to_base=1.0)
    s = j.portfolio_state({"BBB:AUD": 6.0})
    assert s.value_base == pytest.approx(79.5 + 24.0)
    assert j.peak() == pytest.approx(103.5)
    s = j.portfolio_state({"BBB:AUD": 4.0})
    assert s.peak_value_base == pytest.approx(103.5)  # peak never goes down
    with pytest.raises(KeyError):
        j.portfolio_state({})  # refuses to value a holding without a price


def test_halt_and_reset(j):
    j.halt("drawdown")
    assert j.is_halted() and j.portfolio_state({}).halted
    j.reset_halt(90.0)
    assert not j.is_halted() and j.peak() == 90.0


def test_decisions_and_orders_are_journaled_and_counted(j):
    run = j.start_run("paper")
    p = Proposal("BBB", "ASX", "AUD", "BUY", 1, 5.0, reason="because")
    pid = j.record_decision(run, Decision(p, True, [], 5.0, 0.5))
    j.record_decision(run, Decision(p, False, ["not on allowlist"]))
    j.record_order(pid, SimpleNamespace(order_id=7, symbol="BBB", action="BUY", quantity=1, limit_price=5.0,
                                        status="Submitted", filled=0, avg_fill_price=float("nan"), message=""))
    assert j.orders_this_month() == 1
    rows = j.db.execute("SELECT approved, reason FROM proposals").fetchall()
    assert [(r["approved"], r["reason"]) for r in rows] == [(1, "because"), (0, "because")]
    j.finish_run(run, "ok", j.portfolio_state({}))
