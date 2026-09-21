from types import SimpleNamespace as NS

import pytest

from guardrail_trader import dashboard_data
from guardrail_trader.journal import Journal
from guardrail_trader.risk import Decision, Holding, PortfolioState, Proposal
from tests.test_agent import CFG


@pytest.fixture
def j(tmp_path):
    jr = Journal(tmp_path / "j.sqlite")
    jr.init_budget(5000.0, "AUD")
    yield jr
    jr.close()


def test_empty_journal_builds(j):
    d = dashboard_data.build(j, CFG)
    assert d["kpis"]["value"] == 5000.0 and d["kpis"]["pnl"] == 0 and d["holdings"] == []


def test_holdings_pnl_and_decisions(j):
    run = j.start_run("paper")
    p = Proposal("CSCO", "SMART", "USD", "BUY", 2, 110.0, reason="cheap vs SMA50")
    pid = j.record_decision(run, Decision(p, True, [], 308.0, 1.4))
    j.record_decision(run, Decision(Proposal("META", "SMART", "USD", "BUY", 3, 680.0, "x"), False, ["position too big"]))
    j.record_order(pid, NS(order_id=9, symbol="CSCO", action="BUY", quantity=2, limit_price=110.0,
                           status="Filled", filled=2, avg_fill_price=110.0, message=""))
    j.record_fill("CSCO", "USD", "BUY", 2, 110.0, commission=1.0, fx_to_base=1.4, broker_order_id=9)  # cost 309.4
    state = PortfolioState(j.cash_base(), {"CSCO:USD": Holding(2, 120 * 1.4)}, 5000.0)
    j.finish_run(run, "ok", state, "bought CSCO")

    d = dashboard_data.build(j, CFG)
    (h,) = d["holdings"]
    assert h["avg_cost_base"] == pytest.approx(154.7) and h["price_base"] == pytest.approx(168.0)
    assert h["pnl_base"] == pytest.approx((168.0 - 154.7) * 2)
    assert d["kpis"]["value"] == pytest.approx(5000 - 309.4 + 336.0)
    assert d["kpis"]["brokerage_base"] == pytest.approx(1.4) and d["kpis"]["brokerage_fills"] == 1
    assert d["kpis"]["traded_base"] == pytest.approx(308.0)
    assert {x["symbol"]: x["approved"] for x in d["decisions"]} == {"CSCO": 1, "META": 0}
    assert d["decisions"][-1]["order_status"] == "Filled"
    assert d["runs"][0]["approved"] == 1 and d["runs"][0]["blocked"] == 1
