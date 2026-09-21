"""Operator CLI for the journal (Saif only - the bot never calls these).

  .venv/bin/python scripts/journal_cli.py init                 # deposit budget from config/risk.toml (once)
  .venv/bin/python scripts/journal_cli.py status               # cash, holdings, halt state, recent activity
  .venv/bin/python scripts/journal_cli.py reset-halt --confirm # re-arm after a kill switch
"""
from __future__ import annotations

import argparse
import json
import sys

from guardrail_trader.journal import Journal
from guardrail_trader.risk import load_risk_config


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    sub.add_parser("status")
    r = sub.add_parser("reset-halt")
    r.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    cfg = load_risk_config()
    j = Journal()

    if args.cmd == "init":
        j.init_budget(cfg.capital, cfg.base_currency)
        print(f"Deposited {cfg.capital:,.2f} {cfg.base_currency} into the virtual ledger.")

    elif args.cmd == "status":
        base = j.base_currency() or "(not initialised)"
        print(f"base currency : {base}")
        print(f"cash          : {j.cash_base():,.2f}")
        print(f"peak value    : {j.peak():,.2f}")
        print(f"halted        : {j.is_halted()}  {j._get('halted_reason', '') or ''}")
        print(f"orders/month  : {j.orders_this_month()} of {cfg.max_trades_per_month}")
        print(f"allowlist     : {len(cfg.universe)} instruments")
        print(f"LLM spend     : US${j.llm_spend_usd():.2f} this month, US${j.llm_spend_usd('all'):.2f} lifetime")
        h = j.holdings_qty()
        print(f"holdings      : {h or 'none'}")
        print("\nlast 10 proposals:")
        for row in j.db.execute("SELECT ts, action, quantity, symbol, currency, limit_price, approved, block_reasons, reason "
                                "FROM proposals ORDER BY id DESC LIMIT 10"):
            verdict = "APPROVED" if row["approved"] else f"BLOCKED {json.loads(row['block_reasons'])}"
            print(f"  {row['ts']} {row['action']} {row['quantity']:g} {row['symbol']}:{row['currency']} "
                  f"@ {row['limit_price']} -> {verdict}\n      why: {row['reason']}")

    elif args.cmd == "reset-halt":
        if not args.confirm:
            print("Refusing without --confirm. This re-enables trading after a kill switch.")
            return 2
        # Without live prices we can't value holdings, so only re-arm when flat (all cash).
        if j.holdings_qty():
            print("Holdings still present; liquidate first so the new peak is unambiguous.")
            return 2
        j.reset_halt(j.cash_base())
        print(f"Kill switch reset. New peak = {j.cash_base():,.2f}. Trading re-enabled.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
