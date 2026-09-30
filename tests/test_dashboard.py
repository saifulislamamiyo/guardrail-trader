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


def test_pnl_is_against_total_deposits_so_a_topup_is_not_profit(j):
    j.topup_to(10000.0, "AUD")                               # second deposit of 5,000
    d = dashboard_data.build(j, CFG)
    k = d["kpis"]
    assert k["capital"] == 10000.0 and k["value"] == 10000.0
    assert k["pnl"] == 0 and k["pnl_pct"] == 0               # a deposit is not a gain
    assert [dp["amount"] for dp in k["deposits"]] == [5000.0, 5000.0]


def test_topup_after_the_last_run_counts_at_once_not_as_a_loss(j):
    run = j.start_run("paper")
    j.record_fill("CSCO", "USD", "BUY", 2, 110.0, commission=1.0, fx_to_base=1.4)         # cost 309.4
    state = PortfolioState(j.cash_base(), {"CSCO:USD": Holding(2, 120 * 1.4)}, 5000.0)
    j.finish_run(run, "ok", state, "bought CSCO")
    before = dashboard_data.build(j, CFG)["kpis"]
    j.topup_to(10000.0, "AUD")                               # no run has happened since
    with j.db:                                               # timestamps are whole seconds: pin it after the run
        j.db.execute("UPDATE ledger SET ts='2999-01-01T00:00:00+10:00' WHERE kind='DEPOSIT' AND amount_base=5000 "
                     "AND id=(SELECT MAX(id) FROM ledger)")
    after = dashboard_data.build(j, CFG)["kpis"]
    assert after["value"] == pytest.approx(before["value"] + 5000.0)
    assert after["pnl"] == pytest.approx(before["pnl"])      # a deposit moves value and baseline together


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


def test_dashboard_rejects_foreign_host_headers(monkeypatch):
    """DNS rebinding: only localhost Host headers are served."""
    import importlib.util
    from guardrail_trader.config import PROJECT_ROOT
    spec = importlib.util.spec_from_file_location("dash", PROJECT_ROOT / "scripts" / "dashboard.py")
    dash = importlib.util.module_from_spec(spec); spec.loader.exec_module(dash)
    monkeypatch.delenv("DASHBOARD_ALLOWED_HOSTS", raising=False)
    hosts = dash.allowed_hosts(8765)
    assert hosts == {"127.0.0.1:8765", "localhost:8765"}
    assert "attacker.example:8765" not in hosts
    monkeypatch.setenv("DASHBOARD_ALLOWED_HOSTS", "Dash.lan:8765")
    assert "dash.lan:8765" in dash.allowed_hosts(8765)


def test_executor_refuses_blocked_decision():
    from guardrail_trader.executor import execute
    blocked = Decision(Proposal("CSCO", "SMART", "USD", "BUY", 1, 100.0, "x"), False, ["no"])
    with pytest.raises(RuntimeError):
        execute(broker=None, journal=None, decisions=[(1, blocked)], fx={})
