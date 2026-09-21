# Dashboard

A local web page showing everything the bot has done. It is **read-only**: it reads the journal and
scheduler files, never connects to IBKR, and listens on `127.0.0.1` only. It refreshes every 60
seconds and follows your system theme (or use its **Theme** button).

- Native: <http://127.0.0.1:8765> (LaunchAgent `com.guardrail-trader.dashboard`), or run
  `.venv/bin/python scripts/dashboard.py` by hand.
- Docker: the `dashboard` container publishes the same URL.

!!! info "Screenshots"
    Taken from a real paper account with [`scripts/screenshot_dashboard.py`](https://github.com/saifulislamamiyo/guardrail-trader/blob/main/scripts/screenshot_dashboard.py)
    (Playwright), once per theme. Switch this site's theme to see the matching version.

![Dashboard overview](assets/screenshots/overview-light.png#only-light)
![Dashboard overview](assets/screenshots/overview-dark.png#only-dark)

## Summary tiles

![Summary tiles](assets/screenshots/kpis-light.png#only-light)
![Summary tiles](assets/screenshots/kpis-dark.png#only-dark)

| Tile | Meaning |
|---|---|
| Portfolio value | Cash plus holdings at the last run's prices, in the base currency |
| P/L | Against the starting capital |
| Cash | The bot's virtual cash (its ledger, not the whole paper account) |
| Drawdown | Fall from the peak value, with a meter towards the kill switch |
| Orders this month | Used vs `max_trades_per_month` |
| Brokerage paid | Commission on booked fills (base currency), fill count and % of traded value |
| LLM spend | This month vs `LLM_MONTHLY_BUDGET_USD` |
| Last run | Time and status of the most recent run |
| Scheduler | Running or silent (from the heartbeat), plus the next slot in local time |

If the kill switch has fired, a red banner shows the reset command.

## Portfolio value and holdings

![Value chart and holdings](assets/screenshots/value-and-holdings-light.png#only-light)
![Value chart and holdings](assets/screenshots/value-and-holdings-dark.png#only-dark)

The chart plots the value at the end of each run against a dashed starting-capital line; hover for
run details. Holdings show quantity, average cost (including commission), last price, value, P/L
and weight. Prices come from the `snapshots` the journal writes at the end of each run, so the
dashboard needs no broker connection.

## Decisions

![Decisions](assets/screenshots/decisions-light.png#only-light)
![Decisions](assets/screenshots/decisions-dark.png#only-dark)

Every order Claude proposed, with the gate's verdict (and block reasons), what IBKR did with it
(filled, partial, not filled, dry run) and Claude's own reason. Filters: all, approved, blocked,
and hide dry/fake runs.

## Runs and transcripts

![Runs](assets/screenshots/runs-light.png#only-light)
![Runs](assets/screenshots/runs-dark.png#only-dark)

One row per run: mode, status, value, approved/blocked counts and LLM cost. **Click a run** to open
Claude's step-by-step transcript, with every tool call and result:

![Transcript drawer](assets/screenshots/transcript-light.png#only-light)
![Transcript drawer](assets/screenshots/transcript-dark.png#only-dark)

## Fills and LLM spend

![Fills and LLM spend](assets/screenshots/fills-and-llm-light.png#only-light)
![Fills and LLM spend](assets/screenshots/fills-and-llm-dark.png#only-dark)

Fills are what actually executed at IBKR and was booked in the ledger. LLM spend is cost, runs and
tokens per month.

## Where it's implemented

| Piece | File |
|---|---|
| HTTP server (standard library; `/`, `/api/data`, `/api/transcript/<run_id>`) | [`scripts/dashboard.py`](https://github.com/saifulislamamiyo/guardrail-trader/blob/main/scripts/dashboard.py) |
| Data layer | [`guardrail_trader/dashboard_data.py`](https://github.com/saifulislamamiyo/guardrail-trader/blob/main/guardrail_trader/dashboard_data.py) → `build()`, `transcript()` |
| Page (HTML/CSS/JS, inline SVG, no external dependencies) | [`guardrail_trader/web/dashboard.html`](https://github.com/saifulislamamiyo/guardrail-trader/blob/main/guardrail_trader/web/dashboard.html) |

## Regenerating the screenshots

```bash
.venv/bin/pip install -e ".[docs]"
.venv/bin/python -m playwright install chromium
.venv/bin/python scripts/screenshot_dashboard.py    # dashboard must be running on :8765
```
