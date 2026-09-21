"""Read-only views over the journal for the local dashboard. No broker, no network."""
from __future__ import annotations

import json
from pathlib import Path

from guardrail_trader import llm
from guardrail_trader.config import PROJECT_ROOT
from guardrail_trader.journal import Journal
from guardrail_trader.risk import RiskConfig

RUNS_DIR = PROJECT_ROOT / "data" / "runs"


def _rows(j: Journal, sql: str, args=()) -> list[dict]:
    return [dict(r) for r in j.db.execute(sql, args).fetchall()]


def _avg_costs(j: Journal) -> dict[str, float]:
    """Average cost per share in base currency (incl. commission) for open positions."""
    pos: dict[str, list[float]] = {}  # key -> [qty, cost_base]
    for r in _rows(j, "SELECT kind, symbol, currency, quantity, amount_base FROM ledger "
                      "WHERE kind IN ('BUY','SELL') ORDER BY id"):
        k = f"{r['symbol']}:{r['currency']}"
        q, c = pos.setdefault(k, [0.0, 0.0])
        if r["kind"] == "BUY":
            pos[k] = [q + r["quantity"], c - r["amount_base"]]
        elif q > 0:
            sold = min(r["quantity"], q)
            pos[k] = [q - sold, c * (q - sold) / q]
    return {k: c / q for k, (q, c) in pos.items() if q > 1e-9}


def build(j: Journal, cfg: RiskConfig) -> dict:
    runs = _rows(j, "SELECT * FROM runs ORDER BY id")
    valued = [r for r in runs if r["value_base"] is not None]
    last_valued = valued[-1] if valued else None
    cash = j.cash_base()
    value = last_valued["value_base"] if last_valued else cash
    holdings_now = j.holdings_qty()
    if not holdings_now:
        value = cash  # all cash: value is exact without prices
    peak = max(j.peak(), value)
    drawdown = (1 - value / peak) * 100 if peak else 0.0

    # Holdings: quantities from the ledger, prices from the latest snapshot that has them.
    snap = {}
    if holdings_now:
        snap_run = j.db.execute("SELECT MAX(run_id) FROM snapshots").fetchone()[0]
        if snap_run is not None:
            snap = {r["key"]: r for r in _rows(j, "SELECT * FROM snapshots WHERE run_id=?", (snap_run,))}
    avg = _avg_costs(j)
    holdings = []
    for k, q in sorted(holdings_now.items()):
        px = snap.get(k, {}).get("price_base")
        val = q * px if px is not None else None
        cost = avg.get(k)
        holdings.append({
            "symbol": k.split(":")[0], "currency": k.split(":")[1], "quantity": q,
            "avg_cost_base": cost, "price_base": px, "value_base": val,
            "pnl_base": (px - cost) * q if px is not None and cost is not None else None,
            "weight_pct": val / value * 100 if val is not None and value else None,
        })

    llm_by_run = {r["run_id"]: r for r in _rows(
        j, "SELECT run_id, SUM(cost_usd) cost, SUM(input_tokens) tin, SUM(output_tokens) tout, "
           "SUM(cache_read_tokens) tcache, MAX(model) model FROM llm_usage GROUP BY run_id")}
    counts = {r["run_id"]: r for r in _rows(
        j, "SELECT run_id, SUM(approved) approved, COUNT(*) - SUM(approved) blocked FROM proposals GROUP BY run_id")}

    run_list = []
    for r in reversed(runs[-100:]):
        u, c = llm_by_run.get(r["id"], {}), counts.get(r["id"], {})
        run_list.append({**r, "llm_cost_usd": u.get("cost"), "model": u.get("model"),
                         "tokens_in": u.get("tin"), "tokens_out": u.get("tout"), "tokens_cached": u.get("tcache"),
                         "approved": c.get("approved") or 0, "blocked": c.get("blocked") or 0,
                         "has_transcript": (RUNS_DIR / f"run_{r['id']}.json").exists()})

    decisions = _rows(j, """
        SELECT p.id, p.run_id, p.ts, p.action, p.quantity, p.symbol, p.currency, p.limit_price, p.reason,
               p.approved, p.block_reasons, p.notional_base, p.est_commission_base, r.mode,
               o.status AS order_status, o.filled, o.avg_fill_price
        FROM proposals p JOIN runs r ON r.id = p.run_id LEFT JOIN orders o ON o.proposal_id = p.id
        ORDER BY p.id DESC LIMIT 200""")
    for d in decisions:
        d["block_reasons"] = json.loads(d["block_reasons"] or "[]")

    fills = _rows(j, "SELECT ts, kind, symbol, currency, quantity, price, commission, fx_to_base, amount_base, "
                     "broker_order_id FROM ledger WHERE kind IN ('BUY','SELL') ORDER BY id DESC LIMIT 200")

    llm_months = _rows(j, "SELECT substr(ts,1,7) month, SUM(cost_usd) cost, COUNT(DISTINCT run_id) runs, "
                          "SUM(input_tokens) tin, SUM(output_tokens) tout FROM llm_usage GROUP BY month ORDER BY month")

    # Brokerage actually paid: commission on booked fills, converted to the base currency.
    brk = _rows(j, "SELECT COUNT(*) n, COALESCE(SUM(commission * fx_to_base), 0) paid, "
                   "COALESCE(SUM(ABS(quantity * price) * fx_to_base), 0) traded "
                   "FROM ledger WHERE kind IN ('BUY', 'SELL')")[0]

    halted_reason = j._get("halted_reason", "") or ""
    scheduler = _scheduler_status()
    return {
        "base_currency": cfg.base_currency,
        "kpis": {
            "capital": cfg.capital, "value": value, "cash": cash, "peak": peak,
            "pnl": value - cfg.capital, "pnl_pct": (value / cfg.capital - 1) * 100,
            "drawdown_pct": drawdown, "kill_switch_pct": cfg.max_drawdown_pct,
            "orders_this_month": j.orders_this_month(), "orders_limit": cfg.max_trades_per_month,
            "llm_month_usd": j.llm_spend_usd(), "llm_month_cap_usd": llm.monthly_budget_usd(),
            "llm_lifetime_usd": j.llm_spend_usd("all"),
            "brokerage_base": brk["paid"], "brokerage_fills": brk["n"], "traded_base": brk["traded"],
            "halted": j.is_halted(), "halted_reason": halted_reason,
            "value_as_of": last_valued["finished_at"] if last_valued else None,
            "last_run": runs[-1] if runs else None,
            "universe_size": len(cfg.universe), "max_position_pct": cfg.max_position_pct,
        },
        "value_series": [{"ts": r["finished_at"] or r["started_at"], "value": r["value_base"],
                          "mode": r["mode"], "status": r["status"], "run_id": r["id"]} for r in valued],
        "holdings": holdings,
        "runs": run_list,
        "decisions": decisions,
        "fills": fills,
        "llm_months": llm_months,
        "scheduler": scheduler,
    }


def _scheduler_status() -> dict:
    """Heartbeat + last slots from scripts/scheduled_run.py, and the next scheduled slot."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    data = PROJECT_ROOT / "data"
    out: dict = {"last_tick_ny": None, "next_slot_sydney": None, "recent": []}
    try:
        out["last_tick_ny"] = json.loads((data / "scheduler_heartbeat.json").read_text()).get("last_tick_ny")
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    try:
        state = json.loads((data / "scheduler_state.json").read_text())
        out["recent"] = [{"slot": k, **v} for k, v in sorted(state.items())[-6:]][::-1]
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    ny, syd = ZoneInfo("America/New_York"), ZoneInfo("Australia/Sydney")
    now = datetime.now(ny)
    for day in range(0, 8):
        d = (now + timedelta(days=day)).date()
        if d.weekday() >= 5:
            continue
        for name, (h, m) in (("open", (10, 30)), ("close", (15, 0))):
            t = datetime(d.year, d.month, d.day, h, m, tzinfo=ny)
            if t > now:
                out["next_slot_sydney"] = t.astimezone(syd).isoformat(timespec="minutes")
                out["next_slot_name"] = name
                return out
    return out


def transcript(run_id: int) -> list[dict]:
    """Simplified view of Claude's run: its text, tool calls and (truncated) tool results."""
    path = RUNS_DIR / f"run_{int(run_id)}.json"
    if not path.exists():
        return []
    steps = []
    for m in json.loads(path.read_text()):
        content = m.get("content")
        if isinstance(content, str):
            steps.append({"role": m["role"], "kind": "text", "text": content})
            continue
        for b in content or []:
            t = b.get("type")
            if t == "text" and b.get("text", "").strip():
                steps.append({"role": m["role"], "kind": "text", "text": b["text"]})
            elif t == "tool_use":
                steps.append({"role": "assistant", "kind": "tool_call", "name": b.get("name"),
                              "input": b.get("input")})
            elif t == "tool_result":
                c = b.get("content")
                c = c if isinstance(c, str) else json.dumps(c)
                steps.append({"role": "tool", "kind": "tool_result", "is_error": b.get("is_error", False),
                              "text": c[:3000] + ("…" if len(c) > 3000 else "")})
            elif t in ("server_tool_use", "web_search_tool_result"):
                steps.append({"role": "assistant", "kind": "web_search",
                              "text": json.dumps(b.get("input") or "")[:300]})
    return steps
