# guardrail-trader

Autonomous stock-trading agent (Option C): Claude proposes trades, deterministic code enforces risk limits and executes.

## Rules
- Use the project venv at `.venv/` for ALL Python SDK/library installs and runs (`.venv/bin/pip install ...`, `.venv/bin/python ...`). Never install into system/Homebrew Python.
- Claude proposes, code decides: every order must pass the hard-coded risk gate before reaching the broker. Risk limits live in code/config, never only in prompts.
- Paper trading is the default. Live trading requires an explicit config flag set by Saif.
- Secrets (API keys) live in `.env` only; never commit or log them.
- Every decision, reason and fill is written to the journal (SQLite).

## Stack
- Broker: Interactive Brokers via `ib_async` → IB Gateway (paper port 4002). Adapter: `guardrail_trader/broker/ibkr.py` (executes only, never decides).
- Package installed editable in `.venv` (`.venv/bin/pip install -e ".[dev]"`). Tests: `.venv/bin/python -m pytest -q`.
- Smoke test: `.venv/bin/python scripts/check_connection.py [--test-order]`.
- Risk limits: `config/risk.toml` (Saif's: 25% max position, 10 orders/month, 25% drawdown kill switch, ticker allowlist). Gate: `guardrail_trader/risk/gate.py` — pure functions, every rule unit-tested. Never loosen a limit without Saif's explicit instruction.
- Journal + virtual A$100 ledger: `data/journal.sqlite` via `guardrail_trader/journal.py`. The bot's cash/holdings come from the ledger, never from the paper account's balance. Operator CLI: `scripts/journal_cli.py init|status|reset-halt`.
- Universe: CSVs in `config/universe/` listed in risk.toml (`qus_sp500.csv` = Betashares QUS / S&P 500 constituents via `scripts/refresh_universe.py`; `saif_picks.csv`). Affordability report: `scripts/affordability.py` (~90s; run in background with a log file).
- IBKR API rejects fractional-share orders (error 10243) — whole shares only.
- Budget is A$5,000 for the paper phase (Saif's choice). The unused A$100 journal is archived as `data/journal.A100-unused.sqlite`.
- Bot run: `scripts/run_bot.py [--dry-run] [--fake-claude]` = reconcile → price universe (~75s) → kill switch → Claude agent (`guardrail_trader/agent.py`, read-only tools + submit_orders) → final gate → executor → journal. Transcripts: `data/runs/run_<id>.json`. Run long jobs with nohup + `logs/`.
- Tooling: run project commands via Desktop Commander (native macOS). The Cowork Linux VM can't use the macOS venv or reach IB Gateway on the Mac's localhost.
- LLM: `guardrail_trader/llm.py` — `LLM_PROVIDER=anthropic|openrouter` (same Messages API; OpenRouter via base_url + bearer). Saif's TOTAL budget is US$120 = US$100 trading capital + ~US$20 for LLM API AND AWS hosting combined, so spend caps are enforced in code from real usage: `LLM_RUN_BUDGET_USD` (set to 0.10) and `LLM_MONTHLY_BUDGET_USD` (set to 2.50), tracked in the `llm_usage` journal table. Prompt caching is on. Never raise these caps without Saif's say-so.
- Budget period: US$120 over 6 months → ~US$3.30/month for Claude + AWS combined (target: Claude ≤ $2, AWS ≈ $1).
- Universe = 50: `saif_picks.csv` (17) + `top_sp500.csv` (33 largest S&P 500 by SPY weight). Refresh monthly with `scripts/refresh_universe.py`. A full run now takes ~12s.
- Target hosting (not built yet): EventBridge Scheduler (America/New_York cron, 2 runs per US trading day) → Step Functions → ECS Fargate RunTask (IB Gateway + IBC + bot) → journal persisted in S3. No always-on compute, no NAT gateway. Open risk: IB Gateway needs a fresh login (2FA on live) each run.
- Dashboard (local, read-only): `.venv/bin/python scripts/dashboard.py` → http://127.0.0.1:8765. Data layer `guardrail_trader/dashboard_data.py`, page `guardrail_trader/web/dashboard.html` (stdlib server, no extra deps). Reads the journal only; holdings prices come from the `snapshots` table written at the end of each run.
- Unattended (local Mac, paper): LaunchAgents managed by `scripts/launchd.sh install|uninstall|status` — `scheduler` (every 15 min → `scripts/scheduled_run.py`, slots 10:30–11:30 and 15:00–15:40 America/New_York, Mon–Fri, max 3 attempts/slot, file lock), `awake` (caffeinate -i -s), `dashboard` (KeepAlive). Slot state: `data/scheduler_state.json`; heartbeat: `data/scheduler_heartbeat.json`; per-run logs: `logs/run_<date>_<slot>_<n>.log`. Saif does not want to intervene manually.
- Docker (branch `docker`, worktree `../guardrail-trader-docker`): `docker-compose.yml` = `ib-gateway` (gnzsnz image + IBC, paper, host ports 14002/15900, EXISTING_SESSION_DETECTED_ACTION=secondary), `bot` (supercronic → scheduled_run.py, IBKR_HOST=ib-gateway, IBKR_PORT=4004), `dashboard` (127.0.0.1:18765). Paper login via IBC verified with no 2FA. Only one of native IB Gateway / container may be logged in at a time (IBKR one-session rule).
- ACTIVE MODE (since 22 Sep 2026): **Docker**, run from this main folder (`docker compose up -d`; branch `docker` merged into main). launchd is in `docker-mode` (only keep-awake, which now runs 23:00 Sydney -> 16:00 New York on US trading nights via scripts/keep_awake.py). Native IB Gateway app is NOT used. Rollback: `docker compose down` → open/log in native IB Gateway → `scripts/launchd.sh install`. Pre-switch journal backup: `data/journal.pre-docker-*.sqlite`.
