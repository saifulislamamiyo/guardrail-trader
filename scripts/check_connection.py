"""Smoke-test the IBKR connection.

Read-only by default: prints account, cash, positions and one quote.

Usage (from the project root):
  .venv/bin/python scripts/check_connection.py
  .venv/bin/python scripts/check_connection.py --symbol VAS --exchange ASX --currency AUD
  .venv/bin/python scripts/check_connection.py --test-order
      PAPER ONLY: places a 1-share limit BUY at 80% of the price (so it won't fill),
      shows its status, then cancels it. Proves the full order path end to end.
"""
from __future__ import annotations

import argparse
import math
import sys

from guardrail_trader.broker import BrokerSafetyError, IBKRBroker
from guardrail_trader.config import load_ibkr_config


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="AAPL")
    ap.add_argument("--exchange", default="SMART")
    ap.add_argument("--currency", default="USD")
    ap.add_argument("--test-order", action="store_true")
    args = ap.parse_args()

    cfg = load_ibkr_config()
    if args.test_order and cfg.mode != "paper":
        print("--test-order is only allowed with TRADING_MODE=paper")
        return 2

    print(f"mode={cfg.mode} host={cfg.host} port={cfg.port} client_id={cfg.client_id}")
    try:
        broker = IBKRBroker(cfg, readonly=not args.test_order).connect()
    except BrokerSafetyError as e:
        print(f"SAFETY STOP: {e}")
        return 3
    except (ConnectionError, TimeoutError, OSError) as e:
        print(f"Could not connect to TWS/IB Gateway at {cfg.host}:{cfg.port} ({e!r}).")
        print("Is IB Gateway running, logged in to PAPER, with API socket clients enabled?")
        return 1

    with broker:
        a = broker.account_snapshot()
        print(f"\naccount={a.account_id} currency={a.currency}")
        print(f"  net liquidation: {a.net_liquidation:,.2f}")
        print(f"  cash:            {a.cash:,.2f}")
        print(f"  available funds: {a.available_funds:,.2f}")

        pos = broker.positions()
        print(f"\npositions ({len(pos)}):")
        for p in pos:
            print(f"  {p.symbol:<8} {p.quantity:>10g} @ {p.avg_cost:,.4f} {p.currency}")

        contract = broker.stock(args.symbol, args.exchange, args.currency)
        q = broker.quote(contract)
        print(f"\nquote {q.symbol} ({q.data_type}): price={q.price} bid={q.bid} ask={q.ask} close={q.close} {q.currency}")

        if args.test_order:
            if math.isnan(q.price):
                print("No price available; skipping test order.")
                return 1
            limit = round(q.price * 0.8, 2)
            print(f"\npreview: {broker.preview_order(contract, 'BUY', 1, limit)}")
            r = broker.place_order(contract, "BUY", 1, limit_price=limit)
            print(f"placed:    id={r.order_id} status={r.status} filled={r.filled} {r.message}")
            if r.status not in ("Cancelled", "ApiCancelled", "Inactive", "Filled"):
                c = broker.cancel_order(r.order_id)
                print(f"cancelled: id={c.order_id} status={c.status}")
    print("\nOK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
