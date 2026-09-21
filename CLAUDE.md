# guardrail-trader

Autonomous stock-trading agent: Claude proposes trades, deterministic code enforces risk limits and executes.
Docs: https://saifulislamamiyo.github.io/guardrail-trader/

## Rules
- Use the project venv at `.venv/` for all Python installs and runs (`.venv/bin/pip`, `.venv/bin/python`).
- Claude proposes, code decides: every order must pass the risk gate (`guardrail_trader/risk/gate.py`) before reaching the broker. Limits live in code/config, never only in prompts.
- Never loosen a risk limit or raise an LLM spend cap without the owner's explicit instruction.
- Paper trading is the default. Live trading needs the owner's explicit switch (`TRADING_MODE=live` + live port + live account).
- Secrets live in `.env`, `docker/gateway.env` and `docker/secrets/` only (all gitignored); never commit or log them.
- Every decision, reason and fill is written to the journal (`data/journal.sqlite`).
- Every gate rule has a unit test; run `.venv/bin/python -m pytest -q` before committing.

## Map
- Broker adapter (executes, never decides): `guardrail_trader/broker/ibkr.py`
- Agent loop + tools: `guardrail_trader/agent.py`; LLM provider/prices/caps: `guardrail_trader/llm.py`
- Journal/ledger: `guardrail_trader/journal.py`; operator CLI: `scripts/journal_cli.py`
- One run: `scripts/run_bot.py [--dry-run] [--fake-claude]`; scheduler: `scripts/scheduled_run.py`
- Config: `config/risk.toml`, universe CSVs in `config/universe/`
- Hosting: native LaunchAgents via `scripts/launchd.sh`, or `docker-compose.yml`
- Dashboard: `scripts/dashboard.py` → http://127.0.0.1:8765
- Docs site: `docs/` + `mkdocs.yml`; screenshots via `scripts/screenshot_dashboard.py`

Personal/operator notes go in `CLAUDE.local.md` (gitignored).
