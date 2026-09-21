"""One bot run: reconcile -> price -> kill switch -> Claude -> risk gate -> execute -> journal.

  .venv/bin/python scripts/run_bot.py --dry-run --fake-claude   # whole harness, no API key, no orders
  .venv/bin/python scripts/run_bot.py --dry-run                 # real Claude, gate verdicts, no orders
  .venv/bin/python scripts/run_bot.py                           # paper trading (market must be open)

Exit codes: 0 ok/skipped, 1 error, 3 reconciliation failed (needs a human).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from guardrail_trader import llm
from guardrail_trader.agent import TradingAgent
from guardrail_trader.broker import IBKRBroker
from guardrail_trader.config import PROJECT_ROOT, load_ibkr_config
from guardrail_trader.executor import execute
from guardrail_trader.journal import Journal
from guardrail_trader.market import daily_history, is_open, market_sessions, price_instruments, summarize_history
from guardrail_trader.risk import (
    MarketInfo, Proposal, evaluate, instrument_key, kill_switch_triggered, liquidation_proposals, load_risk_config,
)

RUNS_DIR = PROJECT_ROOT / "data" / "runs"


class IBKRMarketView:
    """MarketView backed by IBKR (prices fetched once per run; history/commission on demand)."""

    def __init__(self, broker, cfg, prices, fx):
        self.broker, self.cfg, self.prices, self.fx = broker, cfg, prices, fx
        self._comm_cache: dict[tuple, float] = {}

    def history_summary(self, key: str) -> dict:
        return summarize_history(daily_history(self.broker, self.cfg.universe[key]))

    def commission_base(self, p: Proposal) -> float:
        ck = (p.key, p.action, p.quantity, p.limit_price)
        if ck not in self._comm_cache:
            try:
                c = self.broker.stock(p.symbol, p.exchange, p.currency)
                pv = self.broker.preview_order(c, p.action, p.quantity, p.limit_price)
                comm_ccy = pv["commission_currency"] or p.currency
                self._comm_cache[ck] = pv["commission"] * self.fx.get(comm_ccy, self.fx[p.currency])
            except Exception:
                self._comm_cache[ck] = float("inf")  # unknown cost -> gate blocks it
        return self._comm_cache[ck]


def log(msg: str) -> None:
    print(f"{datetime.now(ZoneInfo('Australia/Sydney')):%H:%M:%S} {msg}", flush=True)


def _jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: _jsonable(v) for k, v in vars(obj).items()}
    if isinstance(obj, list):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return obj


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="no orders; read-only broker connection")
    ap.add_argument("--fake-claude", action="store_true", help="scripted agent, no API calls")
    ap.add_argument("--fill-timeout", type=float, default=120.0)
    args = ap.parse_args()

    cfg = load_risk_config()
    ib_cfg = load_ibkr_config()
    j = Journal()
    if j.base_currency() is None:
        log("Journal not initialised: run scripts/journal_cli.py init")
        return 1
    mode = ib_cfg.mode + ("-dry" if args.dry_run else "") + ("-fake" if args.fake_claude else "")
    run_id = j.start_run(mode)
    log(f"run {run_id} mode={mode} universe={len(cfg.universe)} budget={cfg.capital:g} {cfg.base_currency}")

    try:
        with IBKRBroker(ib_cfg, readonly=args.dry_run) as broker:
            # 1. Reconcile: the ledger must match what IBKR actually holds.
            ibkr = {instrument_key(p.symbol, p.currency): p.quantity for p in broker.positions() if abs(p.quantity) > 1e-9}
            mine = j.holdings_qty()
            if any(abs(ibkr.get(k, 0) - mine.get(k, 0)) > 1e-6 for k in set(ibkr) | set(mine)):
                j.finish_run(run_id, "reconcile_failed", notes=f"ibkr={ibkr} journal={mine}")
                log(f"RECONCILE FAILED: IBKR {ibkr} vs journal {mine}. Not trading; needs a human.")
                return 3
            if broker.open_orders():
                j.finish_run(run_id, "reconcile_failed", notes="unexpected open orders at IBKR")
                log("Unexpected open orders at IBKR. Not trading; needs a human.")
                return 3

            # 2. Prices + FX
            fx = {c: broker.fx_to_base(c, cfg.base_currency) for c in {i.currency for i in cfg.universe.values()}}
            log(f"fx {fx}; pricing {len(cfg.universe)} instruments...")
            prices = price_instruments(broker, list(cfg.universe.values()))
            missing = [k for k in mine if k not in prices]
            if missing:
                j.finish_run(run_id, "error", notes=f"no price for holdings {missing}")
                log(f"No price for held {missing}; refusing to value portfolio.")
                return 1
            prices_base = {k: px * fx[cfg.universe[k].currency] for k, px in prices.items()}
            state = j.portfolio_state({k: prices_base[k] for k in mine})
            log(f"portfolio value {state.value_base:,.2f} cash {state.cash_base:,.2f} "
                f"drawdown {state.drawdown_pct:.2f}% orders this month {state.trades_this_month}")

            usd_open = is_open(market_sessions(broker, next(iter(cfg.universe.values()))),
                               datetime.now(ZoneInfo("America/New_York")))

            if state.halted:
                j.finish_run(run_id, "halted", state, "kill switch active; reset with journal_cli reset-halt")
                log("Trading halted (kill switch). Nothing to do.")
                return 0

            # 3. Kill switch: code decides, not Claude.
            if kill_switch_triggered(state, cfg):
                log(f"KILL SWITCH: drawdown {state.drawdown_pct:.2f}% >= {cfg.max_drawdown_pct}%")
                info = {k: MarketInfo(prices[k], fx[cfg.universe[k].currency], 0.0) for k in mine}
                liq = liquidation_proposals(state, info, cfg)
                if not args.dry_run and usd_open:
                    from guardrail_trader.risk import Decision
                    rows = [(j.record_decision(run_id, Decision(p, True, [])), Decision(p, True, [])) for p in liq]
                    execute(rows, broker, j, fx, args.fill_timeout, log)
                j.halt(f"drawdown {state.drawdown_pct:.2f}%")
                j.finish_run(run_id, "kill_switch", state, f"liquidation orders: {len(liq)}; market open={usd_open}")
                return 0

            if not usd_open and not args.dry_run:
                j.finish_run(run_id, "market_closed", state)
                log("US market closed (or <15 min left). Skipping (no Claude call, no cost).")
                return 0

            # 4. Claude
            market = IBKRMarketView(broker, cfg, prices, fx)
            picks = {r["symbol"] for r in csv.DictReader(open(PROJECT_ROOT / "config/universe/saif_picks.csv"))}
            if args.fake_claude:
                from guardrail_trader.fake_llm import FakeClaude
                client, prov, model_id, cost_fn = FakeClaude(price_fn=lambda s: prices[f"{s}:USD"]), "fake", "fake", None
            else:
                # LLM spend guardrail: never start a run once the monthly budget is used up.
                spent, cap = j.llm_spend_usd(), llm.monthly_budget_usd()
                if spent >= cap:
                    j.finish_run(run_id, "llm_budget_exhausted", state, f"spent US${spent:.2f} of US${cap:.2f} this month")
                    log(f"LLM monthly budget used (US${spent:.2f}/{cap:.2f}). Skipping; no trades.")
                    return 0
                client, prov, model_id, cost_fn = llm.make_client(), llm.provider(), llm.model(), llm.cost_usd
                log(f"LLM {prov}/{model_id}; spent this month US${spent:.2f} of US${cap:.2f}")
            agent = TradingAgent(
                client, cfg, state, market, picks,
                web_search=os.getenv("ENABLE_WEB_SEARCH", "0") == "1", log=log,
                model=model_id,
                **({} if cost_fn is None else dict(
                    cost_fn=cost_fn,
                    run_budget_usd=min(llm.run_budget_usd(), llm.monthly_budget_usd() - j.llm_spend_usd()),
                    on_usage=lambda usage, cost: j.record_llm_usage(run_id, prov, model_id, usage, cost))),
            )
            result = agent.run()
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            (RUNS_DIR / f"run_{run_id}.json").write_text(json.dumps(_jsonable(result.transcript), indent=1, default=str))
            log(f"Claude: {result.turns} turns, tokens in/out {result.input_tokens}/{result.output_tokens}, "
                f"cost US${result.cost_usd:.4f}; summary: {result.summary or '(none)'}")

            # 5. Final gate check - authoritative, independent of what Claude saw.
            info = {}
            for p in result.proposals:
                if p.key in prices:
                    info[p.key] = MarketInfo(prices[p.key], fx[p.currency], market.commission_base(p))
            decisions, _ = evaluate(result.proposals, state, info, cfg)
            rows = [(j.record_decision(run_id, d), d) for d in decisions]
            for _, d in rows:
                p = d.proposal
                log(f"[gate] {p.action} {p.quantity:g} {p.symbol} @ {p.limit_price}: "
                    f"{'APPROVED' if d.approved else 'BLOCKED ' + '; '.join(d.reasons)}")

            # 6. Execute
            approved = [(pid, d) for pid, d in rows if d.approved]
            if args.dry_run:
                j.finish_run(run_id, "dry_run", state, result.summary)
                log(f"Dry run: {len(approved)} order(s) would be placed. Nothing sent.")
                return 0
            execute(approved, broker, j, fx, args.fill_timeout, log)
            final = j.portfolio_state({k: prices_base[k] for k in j.holdings_qty()})
            j.finish_run(run_id, "ok", final, result.summary)
            log(f"Done. value {final.value_base:,.2f} cash {final.cash_base:,.2f}")
            return 0
    except Exception as e:
        j.finish_run(run_id, "error", notes=f"{e!r}\n{traceback.format_exc()[-2000:]}")
        log(f"ERROR: {e!r}")
        raise
    finally:
        j.close()


if __name__ == "__main__":
    sys.exit(main())
