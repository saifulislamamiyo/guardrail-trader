<p align="center"><img src="docs/assets/icon.svg" alt="guardrail-trader bot icon" width="96"></p>

# guardrail-trader

An autonomous stock-trading agent for **Interactive Brokers (IBKR)**, built as a learning project in
**agent harness design**. Claude reviews the portfolio and proposes trades; plain, unit-tested code
decides whether any of them are allowed to reach the broker.

> **Claude proposes, code decides.** Every limit is enforced in code. Claude can read the limits,
> but it cannot change or bypass them.

⚠️ Runs against an IBKR **paper** (simulated) account by default. This is an engineering project,
not investment advice. Automated trading can lose money.

📖 **Docs:** https://saifulislamamiyo.github.io/guardrail-trader/

---

## How it works

```mermaid
flowchart TD
    S[launchd scheduler<br/>2 slots per US trading day] --> R[run_bot.py]
    R --> REC{Reconcile<br/>journal vs IBKR}
    REC -- mismatch --> STOP1[Stop: needs a human]
    REC -- ok --> P[Price universe + FX]
    P --> KS{Kill switch?}
    KS -- drawdown ≥ limit --> LIQ[Sell all, halt]
    KS -- ok --> MO{Market open?}
    MO -- no --> SKIP[Skip: no LLM call]
    MO -- yes --> AG[Claude agent loop<br/>read-only tools + submit_orders]
    AG --> G[Risk gate<br/>pure code]
    G -- approved --> EX[Executor → IBKR]
    G -- blocked --> J
    EX --> J[(Journal<br/>SQLite)]
    J --> D[Local dashboard]
```

---

## The rules (risk gate)

Every order Claude proposes goes through the gate **twice**: once when Claude calls `check_orders` or
`submit_orders`, so it can see why an order was blocked, and again, authoritatively, in [`run_bot.py`](scripts/run_bot.py)
before anything is sent. Orders are evaluated on a *simulated* portfolio in sequence, sells first,
so several orders together can't break a limit that each one passes on its own.

| Rule | Value | Where it's enforced |
|---|---|---|
| Only allowlisted instruments (50 tickers) | [`config/universe/*.csv`](config/universe/) | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()`; list loaded by [`risk/config.py`](guardrail_trader/risk/config.py) → `load_risk_config()` |
| Max single holding | 25% of portfolio | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` (BUY branch) · [`config/risk.toml`](config/risk.toml) `max_position_pct` |
| Max orders per calendar month (Sydney) | 10 | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` · count from [`journal.py`](guardrail_trader/journal.py) → `orders_this_month()` |
| Kill switch: drawdown from peak | 25% → sell all, halt | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `kill_switch_triggered()`, `liquidation_proposals()` · [`run_bot.py`](scripts/run_bot.py) step 3 |
| Halt persists until manually reset | — | [`journal.py`](guardrail_trader/journal.py) → `halt()` / `reset_halt()` · [`scripts/journal_cli.py reset-halt --confirm`](scripts/journal_cli.py) |
| No shorting: sell only what is held | hard-coded | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` (SELL branch) |
| No margin: cost plus commission ≤ cash | hard-coded | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` (BUY branch) |
| Limit orders only, within ±2% of reference price | `max_price_deviation_pct` | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` |
| Commission ≤ 10% of order value | `max_commission_pct` | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` · estimate from IBKR what-if [`broker/ibkr.py`](guardrail_trader/broker/ibkr.py) → `preview_order()` |
| Whole shares only (IBKR API rejects fractional orders) | `allow_fractional = false` | [`risk/gate.py`](guardrail_trader/risk/gate.py) → `_check()` |
| Invalid config refuses to load (fail-closed) | — | [`risk/config.py`](guardrail_trader/risk/config.py) → `load_risk_config()`, `_pct()` |

All tunable values live in [`config/risk.toml`](config/risk.toml). Every rule has tests in
[`tests/test_risk_gate.py`](tests/test_risk_gate.py).

---

## The harness (everything around Claude)

| Concern | What the harness does | Where |
|---|---|---|
| **Tools** | Claude gets read-only tools (`get_portfolio`, `list_universe`, `get_price_history`, `check_orders`) plus one final action (`submit_orders`). It never talks to the broker. | [`agent.py`](guardrail_trader/agent.py) → `TOOLS`, `_dispatch()` |
| **Permissions** | The gate decides; the executor only places orders the gate approved. | [`run_bot.py`](scripts/run_bot.py) step 5 · [`executor.py`](guardrail_trader/executor.py) → `execute()` |
| **Paper vs live safety** | Paper mode refuses IBKR's live ports; the account ID must match the mode (paper IDs start with `DU`); read-only connections can't place orders. | [`broker/ibkr.py`](guardrail_trader/broker/ibkr.py) → `check_endpoint()`, `check_account()`, `place_order()` |
| **Reconciliation** | Before each run, the journal's holdings must equal IBKR's positions, with no stray open orders; otherwise it stops. | [`run_bot.py`](scripts/run_bot.py) step 1 |
| **Virtual budget** | The paper account holds far more than the budget; the bot only sees its own ledger's cash. | [`journal.py`](guardrail_trader/journal.py) → `init_budget()`, `cash_base()`, `portfolio_state()` |
| **Fill accounting** | Only real fills are booked (partial fills handled; unfilled orders cancelled). | [`executor.py`](guardrail_trader/executor.py) → `execute()` · [`broker/ibkr.py`](guardrail_trader/broker/ibkr.py) → `fill_details()` |
| **Market-hours check** | Uses IBKR's own trading hours (holidays included); won't trade with less than 15 minutes to the close. | [`market.py`](guardrail_trader/market.py) → `market_sessions()`, `is_open()` |
| **Tool-error handling** | Tool errors go back to Claude as `is_error` results instead of crashing the loop. | [`agent.py`](guardrail_trader/agent.py) → `_dispatch()` |
| **Observability** | Every proposal, Claude's reason, the gate verdict, orders, fills and LLM cost are recorded. Full transcripts are saved per run. | [`journal.py`](guardrail_trader/journal.py) · `data/runs/run_<id>.json` · [Dashboard](https://saifulislamamiyo.github.io/guardrail-trader/dashboard/) |
| **Scheduling** | Runs at New York-time slots (handles both US and Sydney daylight saving), at most 3 attempts per slot, file lock against overlapping runs. | [`scripts/scheduled_run.py`](scripts/scheduled_run.py) → `SLOTS`, `MAX_ATTEMPTS`, `current_slot()` |

---

## The agent loop

```mermaid
sequenceDiagram
    participant H as Harness (agent.py)
    participant C as Claude
    participant T as Tools
    participant G as Risk gate
    H->>C: system prompt (limits) + task
    loop until submit_orders, stop, or a limit is hit
        C->>H: tool_use (get_portfolio / list_universe / get_price_history / check_orders)
        H->>T: run tool (read-only)
        T-->>H: result
        H-->>C: tool_result
    end
    C->>H: submit_orders(orders, summary)
    H->>G: final authoritative check (run_bot.py)
    G-->>H: approved / blocked + reasons
```

The loop is in [`agent.py`](guardrail_trader/agent.py) → `TradingAgent.run()`. It stops when:

- Claude calls `submit_orders` (an empty list means "hold"),
- Claude ends its turn without submitting, which means **no trades**,
- `MAX_TURNS` is reached (20, env `AGENT_MAX_TURNS`), or
- the per-run cost budget is exceeded (see below).

Per-run tool limits: `MAX_HISTORY_CALLS = 15` (IBKR pacing and cost) and `MAX_CHECK_CALLS = 5`,
both in [`agent.py`](guardrail_trader/agent.py).

---

## Budget constraints

| Constraint | Value | Where |
|---|---|---|
| Virtual trading capital | A$5,000 during the paper phase | [`config/risk.toml`](config/risk.toml) `[budget]` · [`journal.py`](guardrail_trader/journal.py) → `init_budget()` |
| LLM cost per run | stop at **US$0.10**, no trades | `.env` `LLM_RUN_BUDGET_USD` · [`agent.py`](guardrail_trader/agent.py) → `TradingAgent.run()` |
| LLM cost per month | skip runs once **US$2.50** is spent | `.env` `LLM_MONTHLY_BUDGET_USD` · [`run_bot.py`](scripts/run_bot.py) step 4 · [`journal.py`](guardrail_trader/journal.py) → `llm_spend_usd()` |
| Cost measured from real usage | tokens × published prices (incl. cache and web search) | [`llm.py`](guardrail_trader/llm.py) → `PRICES`, `cost_usd()` · table `llm_usage` |
| Unpriced models refused | a model with no known price can't be used | [`llm.py`](guardrail_trader/llm.py) → `model()` |
| Prompt caching | system prompt, tools and conversation prefix cached | [`agent.py`](guardrail_trader/agent.py) → `run()`, `_move_cache_breakpoint()` |
| No LLM call when the market is closed | weekends, holidays, outside slots | [`run_bot.py`](scripts/run_bot.py) (before step 4) · [`scripts/scheduled_run.py`](scripts/scheduled_run.py) |
| Small universe | 50 tickers keeps prompts small and pricing fast | [`config/risk.toml`](config/risk.toml) `[universe]` · [`scripts/refresh_universe.py`](scripts/refresh_universe.py) |
| Web search off by default | each search costs extra | `.env` `ENABLE_WEB_SEARCH` · [`agent.py`](guardrail_trader/agent.py) → `WEB_SEARCH_TOOL` |
| Provider choice | Anthropic direct or OpenRouter (same Messages API) | [`llm.py`](guardrail_trader/llm.py) → `make_client()` |

---

## Quick start

Full guides: **[native (launchd)](https://saifulislamamiyo.github.io/guardrail-trader/setup-native/)** ·
**[Docker](https://saifulislamamiyo.github.io/guardrail-trader/setup-docker/)** ·
[how to set your own rules and universe](https://saifulislamamiyo.github.io/guardrail-trader/configuration/) ·
[dashboard](https://saifulislamamiyo.github.io/guardrail-trader/dashboard/) ·
[operations](https://saifulislamamiyo.github.io/guardrail-trader/operations/)

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev,tools]"
cp .env.example .env                                         # API key; TRADING_MODE=paper
.venv/bin/python scripts/check_connection.py                 # IB Gateway (paper) on 4002
.venv/bin/python scripts/journal_cli.py init                 # deposit the virtual budget (once)
.venv/bin/python scripts/run_bot.py --dry-run --fake-claude  # whole harness, no cost, no orders
```

**Native:** `scripts/launchd.sh render` (review) → `scripts/launchd.sh install`.

**Docker:** add `docker/gateway.env` and `docker/secrets/*.txt`, then
`scripts/launchd.sh docker-mode && docker compose up -d --build`.

Dashboard: <http://127.0.0.1:8765>

---

## Project layout

| Path | Purpose |
|---|---|
| [`guardrail_trader/broker/ibkr.py`](guardrail_trader/broker/ibkr.py) | IBKR adapter: executes, never decides; paper/live safety checks |
| [`guardrail_trader/risk/gate.py`](guardrail_trader/risk/gate.py) | The risk gate (pure functions) |
| [`guardrail_trader/risk/config.py`](guardrail_trader/risk/config.py) | Loads and validates `risk.toml` and the universe |
| [`guardrail_trader/agent.py`](guardrail_trader/agent.py) | Claude agent loop, tools, caching, per-run cost stop |
| [`guardrail_trader/llm.py`](guardrail_trader/llm.py) | Provider switch, prices, cost accounting, caps |
| [`guardrail_trader/journal.py`](guardrail_trader/journal.py) | SQLite: ledger, runs, proposals, orders, snapshots, LLM usage |
| [`guardrail_trader/executor.py`](guardrail_trader/executor.py) | Places approved orders, books fills |
| [`guardrail_trader/market.py`](guardrail_trader/market.py) | Prices, history summaries, market hours |
| [`guardrail_trader/dashboard_data.py`](guardrail_trader/dashboard_data.py) | Read-only views for the dashboard |
| [`guardrail_trader/web/dashboard.html`](guardrail_trader/web/dashboard.html) | Dashboard UI |
| [`guardrail_trader/fake_llm.py`](guardrail_trader/fake_llm.py) | Scripted stand-in for Claude (tests, `--fake-claude`) |
| [`scripts/run_bot.py`](scripts/run_bot.py) | One bot run: reconcile → price → kill switch → Claude → gate → execute |
| [`scripts/scheduled_run.py`](scripts/scheduled_run.py) | Unattended entry point called by launchd |
| [`scripts/launchd.sh`](scripts/launchd.sh) | Install / uninstall / status of the LaunchAgents |
| [`scripts/dashboard.py`](scripts/dashboard.py) | Dashboard server |
| [`scripts/journal_cli.py`](scripts/journal_cli.py) | Operator CLI: `init`, `status`, `reset-halt` |
| [`scripts/check_connection.py`](scripts/check_connection.py) | IBKR connection smoke test (read-only; `--test-order` on paper) |
| [`scripts/refresh_universe.py`](scripts/refresh_universe.py) | Rebuilds the top-S&P 500 part of the universe |
| [`scripts/affordability.py`](scripts/affordability.py) | Which allowlisted tickers fit the position limit |
| [`config/`](config/) | `risk.toml` and universe CSVs |
| [`tests/`](tests/) | Gate, broker safety, journal, agent, LLM budget, dashboard |

---

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests run without a broker or API key. A scripted stand-in for Claude
([`guardrail_trader/fake_llm.py`](guardrail_trader/fake_llm.py)) exercises the full tool protocol.

---

## Known limitations

- **IB Gateway login:** IBKR requires a fresh login weekly, and IB Gateway doesn't restart itself after a reboot. [IBC](https://github.com/IbcAlpha/IBC) can automate this; it isn't set up yet.
- **Local hosting:** the Mac must stay awake with the lid open. The keep-awake job prevents idle sleep only.
- **Whole shares only:** the IBKR API rejects fractional-share orders.
- **Delayed prices:** the free-trial paper account gets delayed (~15 min) market data.
- **Not built yet:** planned AWS hosting (EventBridge Scheduler → Step Functions → ECS Fargate task, journal on S3).
