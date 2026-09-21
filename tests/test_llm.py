"""LLM cost accounting and spend guardrails."""
from types import SimpleNamespace as NS

import pytest

from guardrail_trader import llm
from guardrail_trader.agent import TradingAgent
from guardrail_trader.fake_llm import FakeClaude
from guardrail_trader.journal import Journal
from tests.test_agent import CFG, StubMarket


def test_cost_formula_sonnet5():
    u = NS(input_tokens=10_000, output_tokens=2_000, cache_read_input_tokens=50_000,
           cache_creation_input_tokens=4_000, server_tool_use=NS(web_search_requests=2))
    # 10k*2 + 4k*2*1.25 + 50k*2*0.1 + 2k*10 = 20k+10k+10k+20k = 60k -> $0.06 ; + 2 searches $0.02
    assert llm.cost_usd("claude-sonnet-5", u) == pytest.approx(0.08)


def test_llm_module_loads_dotenv_on_import():
    """Regression: importing llm alone must load the project .env (caps were silently defaulting).

    Runs in a fresh interpreter with load_dotenv patched, so it passes with or without a real .env (CI)."""
    import subprocess
    import sys
    code = ("import dotenv; calls = []; dotenv.load_dotenv = lambda *a, **k: calls.append(str(a[0]) if a else '');"
            "from guardrail_trader import llm; print(any(c.endswith('.env') for c in calls))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout.strip()
    assert out == "True"


def test_unknown_model_refused(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "some-unpriced-model")
    with pytest.raises(ValueError):
        llm.model()


def test_openrouter_client_uses_bearer_and_base_url(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("CLAUDE_MODEL", raising=False)
    c = llm.make_client()
    assert str(c.base_url).startswith("https://openrouter.ai/api")
    assert c.auth_headers.get("Authorization") == "Bearer sk-or-test"
    assert llm.model() == "anthropic/claude-sonnet-5"


class PricyFake(FakeClaude):
    def create(self, **kw):
        r = super().create(**kw)
        r.usage = NS(input_tokens=100_000, output_tokens=0)  # $0.20 per turn on sonnet-5
        return r


def test_run_budget_stops_agent_without_trades():
    from guardrail_trader.risk import PortfolioState
    seen = []
    a = TradingAgent(PricyFake("CSCO", 1, price_fn=lambda s: 110.0), CFG,
                     PortfolioState(5000.0, peak_value_base=5000.0), StubMarket(), {"CSCO"},
                     log=lambda *_: None, model="claude-sonnet-5", cost_fn=llm.cost_usd,
                     run_budget_usd=0.50, on_usage=lambda u, c: seen.append(c))
    res = a.run()
    assert res.stop_reason == "run_budget_exceeded" and not res.submitted and res.proposals == []
    assert len(seen) == 3 and res.cost_usd == pytest.approx(0.60)


def test_at_most_three_cache_breakpoints_per_request():
    calls = []

    class Spy(FakeClaude):
        def create(self, **kw):
            n = sum(1 for m in kw["messages"] if m["role"] == "user" and isinstance(m["content"], list)
                    for b in m["content"] if isinstance(b, dict) and "cache_control" in b)
            n += sum(1 for t in kw["tools"] if "cache_control" in t)
            n += sum(1 for s in kw["system"] if "cache_control" in s)
            calls.append(n)
            return super().create(**kw)

    from guardrail_trader.risk import PortfolioState
    TradingAgent(Spy("CSCO", 1, price_fn=lambda s: 110.0), CFG, PortfolioState(5000.0, peak_value_base=5000.0),
                 StubMarket(), {"CSCO"}, log=lambda *_: None).run()
    assert calls and max(calls) <= 4 and all(c == 3 for c in calls)


def test_journal_tracks_monthly_spend(tmp_path):
    j = Journal(tmp_path / "j.sqlite")
    j.record_llm_usage(None, "anthropic", "claude-sonnet-5", NS(input_tokens=1, output_tokens=1), 0.12)
    j.record_llm_usage(None, "anthropic", "claude-sonnet-5", NS(input_tokens=1, output_tokens=1), 0.08)
    assert j.llm_spend_usd() == pytest.approx(0.20) and j.llm_spend_usd("all") == pytest.approx(0.20)
    assert j.llm_spend_usd("1999-01") == 0
