# Operations

## launchd as code

The LaunchAgents are never hand-edited. [`scripts/launchd.sh`](https://github.com/saifulislamamiyo/guardrail-trader/blob/main/scripts/launchd.sh) generates them from the
repo's own path, so anyone who clones the repo gets identical agents:

| Command | What it does |
|---|---|
| `scripts/launchd.sh render` | Print the three plists it would install. Writes nothing. |
| `scripts/launchd.sh install` | Native mode: write the plists to `~/Library/LaunchAgents` and load them |
| `scripts/launchd.sh docker-mode` | Remove the scheduler + dashboard agents; keep keep-awake |
| `scripts/launchd.sh status` | State, PID and last exit code of each agent |
| `scripts/launchd.sh uninstall` | Unload and delete all three |

| Label | Starts | Runs |
|---|---|---|
| `com.guardrail-trader.scheduler` | every 900 s (`StartInterval`) | `.venv/bin/python scripts/scheduled_run.py` |
| `com.guardrail-trader.dashboard` | at login, restarted if it exits (`KeepAlive`) | `.venv/bin/python scripts/dashboard.py --no-browser` |
| `com.guardrail-trader.awake` | `KEEP_AWAKE_START` local, default 18:00 (`StartCalendarInterval`), and at load | `.venv/bin/python scripts/keep_awake.py` |

All three use the project's **venv Python**, and write logs to `logs/<label>.log`.

!!! note "Why the venv Python and not `/usr/bin/python3`"
    macOS privacy protection (TCC) blocks `/usr/bin/python3` launched by launchd from reading
    `~/Documents`, failing with *Operation not permitted*. The venv interpreter isn't blocked.

### Keep-awake window

[`keep_awake.py`](https://github.com/saifulislamamiyo/guardrail-trader/blob/main/scripts/keep_awake.py) computes how long to stay awake, then replaces itself with
`caffeinate -i -s -t <seconds>`:

- From `KEEP_AWAKE_START` (default **18:00** local) until **16:00 New York** (after the close slot), on evenings
  before a US trading day. Change it with `KEEP_AWAKE_START=19:30 scripts/launchd.sh docker-mode` (or `install`).
- Outside that window, or on US weekends, it exits immediately, so the Mac can sleep normally.

Inspect what launchd has loaded:

```bash
launchctl list | grep guardrail
launchctl print gui/$(id -u)/com.guardrail-trader.awake
pmset -g assertions | grep caffeinate
```

## Logs and state

| File | Written by |
|---|---|
| `logs/com.guardrail-trader.*.log` | launchd agents (native) |
| `logs/run_*.log` | each bot run |
| `data/journal.sqlite` | the journal: the source of truth |
| `data/runs/run_<id>.json` | full Claude transcript per run |
| `data/scheduler_state.json` | per-slot attempts and completion |
| `data/scheduler_heartbeat.json` | last scheduler tick (Docker healthcheck, dashboard tile) |

In Docker: `docker compose logs -f bot` and `docker compose logs -f ib-gateway`.

## Journal CLI

```bash
.venv/bin/python scripts/journal_cli.py status               # budget, holdings, orders, spend
.venv/bin/python scripts/journal_cli.py init                 # deposit the budget (once)
.venv/bin/python scripts/journal_cli.py reset-halt --confirm # clear the kill switch
```

In Docker, prefix with `docker compose exec bot python` instead of `.venv/bin/python`.

## Dependencies and pinning

| What | Pinned by | Updated by |
|---|---|---|
| Python packages (image, CI) | `uv.lock` with sha256 hashes; image installs with `--require-hashes`, then `pip check` | Dependabot (`uv` ecosystem re-resolves the whole graph), or `uv lock --upgrade` |
| Base image, IB Gateway image | digest (`@sha256:…`) | Dependabot |
| GitHub Actions | commit SHA | Dependabot |
| supercronic | SHA-256 of the release binary | manual |
| uv (image build, CI) | image digest / version `0.10.12` | GitHub Action by Dependabot; image digest manual |

## Dashboard hardening

The dashboard answers only requests addressed to `127.0.0.1:<port>` or `localhost:<port>`, so a
web page on another domain can't read it through DNS rebinding. To reach it by another name
(e.g. behind a reverse proxy), set `DASHBOARD_ALLOWED_HOSTS=name:port`.

**Cloudflare tunnel:** have cloudflared rewrite the Host header to the local one:

```bash
cloudflared tunnel --url http://127.0.0.1:8765 --http-host-header 127.0.0.1:8765
```

!!! warning "A quick tunnel is public"
    Anyone with the `*.trycloudflare.com` link sees your portfolio, decisions and Claude
    transcripts; there is no login. For regular use, run a named tunnel behind
    Cloudflare Access (email login).

## Troubleshooting

??? question "IB Gateway: *softProtocols missing required protocols*, then a re-login loop"
    A stale session. Quit IB Gateway completely (not just close the window), wait a minute, and
    launch it again.

??? question "The container won't log in, or my native session got kicked"
    IBKR allows one session per username. Only one of the native app or the `ib-gateway` container
    may be logged in.

??? question "A run logged *BROKER NOT READY* (status `broker_not_ready`)"
    IB Gateway accepted the connection but served no data: the logs show `positions request timed
    out`, `account updates ... request timed out`. This is usually IBKR's nightly re-login, which
    IBC completes on its own. The run stops before any decision and **the scheduler retries it**
    on the next 15-minute tick, up to 3 attempts in the slot. If it persists, check
    `docker compose logs ib-gateway` for a "Re-login is required" dialog.

??? question "A run stopped with *RECONCILE FAILED* (status `reconcile_failed`)"
    The journal's holdings differ from IBKR's positions or there are open orders at IBKR (for example, you traded manually in the
    paper account). The bot refuses to trade until they match. Undo the manual trade, or fix the
    journal, then let the next slot run.

??? question "No runs happened overnight"
    Check the Mac didn't sleep (lid closed, or keep-awake not loaded: `scripts/launchd.sh status`),
    that IB Gateway was logged in, and the scheduler log. The dashboard's Scheduler tile shows
    *silent* when the heartbeat is stale.

??? question "Runs are skipped with *LLM monthly budget used*"
    Working as intended. Raise `LLM_MONTHLY_BUDGET_USD` or wait for the next month.

??? question "IBKR error 10243 (fractional shares)"
    The IBKR API rejects fractional orders. Keep `allow_fractional = false`.
