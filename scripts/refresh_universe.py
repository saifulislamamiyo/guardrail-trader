"""Rebuild config/universe/top_sp500.csv: the largest S&P 500 companies by market cap,
topping up Saif's picks to a fixed universe size (default 50).

Market cap ranking comes from SPY's published daily holdings weights (State Street),
which are float-adjusted market-cap weights. One share class per company (GOOGL beats GOOG).
Run monthly:

  .venv/bin/python scripts/refresh_universe.py [--size 50]
"""
from __future__ import annotations

import argparse
import csv
import io
import sys
from datetime import date

import pandas as pd
import requests

from guardrail_trader.config import PROJECT_ROOT

SPY_URL = ("https://www.ssga.com/us/en/intermediary/library-content/products/fund-data/"
           "etfs/us/holdings-daily-us-en-spy.xlsx")
PICKS = PROJECT_ROOT / "config" / "universe" / "saif_picks.csv"
OUT = PROJECT_ROOT / "config" / "universe" / "top_sp500.csv"
SAME_COMPANY = {"GOOG": "GOOGL", "GOOGL": "GOOG", "FOX": "FOXA", "FOXA": "FOX", "NWS": "NWSA", "NWSA": "NWS"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--size", type=int, default=50)
    args = ap.parse_args()

    picks = [r["symbol"] for r in csv.DictReader(open(PICKS))]
    need = args.size - len(picks)
    if need < 0:
        print(f"{len(picks)} picks already exceed size {args.size}")
        return 1

    r = requests.get(SPY_URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
    r.raise_for_status()
    df = pd.read_excel(io.BytesIO(r.content), skiprows=4)
    df = df[df["Ticker"].notna() & df["Weight"].notna() & (df["Local Currency"] == "USD")]
    df = df[df["Ticker"].str.match(r"^[A-Z]+(\.[A-Z])?$")].sort_values("Weight", ascending=False)
    if len(df) < 480:
        print(f"Only {len(df)} holdings parsed; refusing to overwrite {OUT}")
        return 1

    chosen, taken = [], set(picks)
    for _, row in df.iterrows():
        sym = row["Ticker"].replace(".", " ")          # IBKR: BRK.B -> "BRK B"
        if sym in taken or SAME_COMPANY.get(sym) in taken:
            continue
        chosen.append((sym, row["Name"].title(), round(float(row["Weight"]), 3)))
        taken.add(sym)
        if len(chosen) == need:
            break

    with open(OUT, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["symbol", "exchange", "currency", "name", "source"])
        for sym, name, wt in chosen:
            w.writerow([sym, "SMART", "USD", name, f"S&P 500 top by market cap (SPY weight {wt}%, {date.today()})"])
    print(f"Wrote {len(chosen)} tickers to {OUT.relative_to(PROJECT_ROOT)} (+{len(picks)} picks = {len(chosen) + len(picks)})")
    print(" ".join(s for s, *_ in chosen))
    return 0


if __name__ == "__main__":
    sys.exit(main())
