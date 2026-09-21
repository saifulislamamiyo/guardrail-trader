# Native setup (macOS + launchd)

Everything runs as normal processes on your Mac, started by launchd.

## Prerequisites

- macOS with Python 3.11+
- An IBKR account with a **paper** (or free-trial) login
- [IB Gateway](https://www.interactivebrokers.com.au/en/trading/ibgateway-stable.php) (stable channel)
- An Anthropic API key, or an OpenRouter key (see [How to use → LLM provider](configuration.md#llm-provider-and-spend-caps))

## 1. Install

```bash
git clone https://github.com/saifulislamamiyo/guardrail-trader.git
cd guardrail-trader
python3 -m venv .venv
.venv/bin/pip install -e ".[dev,tools]"
cp .env.example .env        # add your API key; keep TRADING_MODE=paper, IBKR_PORT=4002
```

!!! danger "Never commit `.env`"
    It holds your API key. It is already in `.gitignore`.

## 2. Configure IB Gateway

1. Log in to IB Gateway with **Paper Trading** selected.
2. *Configure → Settings → API → Settings*:
    - **Enable ActiveX and Socket Clients**: on
    - **Read-Only API**: off (the bot has its own read-only mode)
    - **Socket port**: `4002`
    - **Allow connections from localhost only**: on
3. Leave it running and logged in.

## 3. Verify, then dry-run

```bash
.venv/bin/python scripts/check_connection.py                  # read-only: account, positions, a quote
.venv/bin/python scripts/journal_cli.py init                   # deposit the virtual budget (once)
.venv/bin/python scripts/run_bot.py --dry-run --fake-claude    # whole harness, no API cost, no orders
.venv/bin/python scripts/run_bot.py --dry-run                  # real Claude, nothing sent to IBKR
.venv/bin/python -m pytest -q                                  # tests need no broker or key
```

`check_connection.py` refuses to continue if the port is a live port or the account ID is not a
paper account (paper IDs start with `DU`).

## 4. Run unattended

```bash
scripts/launchd.sh render     # print the three plists first (installs nothing)
scripts/launchd.sh install    # scheduler, keep-awake, dashboard
scripts/launchd.sh status
```

That's it: from now on, two runs happen per US trading day, and the dashboard is at
<http://127.0.0.1:8765>. See [Operations](operations.md#launchd-as-code) for what the LaunchAgents
contain and how to remove them.

!!! warning "Keep the lid open"
    `caffeinate -i -s` prevents idle sleep only. Closing the lid still sleeps a MacBook (unless
    it's on power with an external display), and a sleeping Mac misses its runs.
