"""SQLite journal: the bot's audit log AND its virtual A$100 sub-account.

The paper account holds far more than the budget, so the bot never trusts the
broker's cash figure. Its cash and holdings come from this ledger:
    cash     = sum(ledger.amount_base)
    holdings = sum(BUY qty) - sum(SELL qty) per instrument

Tables
  runs       one row per bot run (value, drawdown, status)
  proposals  every proposal Claude made + the gate's verdict and reasons
  orders     every order sent to the broker and its outcome
  ledger     DEPOSIT / BUY / SELL cash movements in base currency (fills only)
  state      key/value: peak value, halted flag
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from guardrail_trader.config import PROJECT_ROOT
from guardrail_trader.risk.gate import Decision, Holding, PortfolioState

DEFAULT_DB = PROJECT_ROOT / "data" / "journal.sqlite"
TZ = ZoneInfo("Australia/Sydney")

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
  mode TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'running',
  value_base REAL, cash_base REAL, peak_base REAL, drawdown_pct REAL, notes TEXT
);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), ts TEXT NOT NULL,
  symbol TEXT, exchange TEXT, currency TEXT, action TEXT, quantity REAL, limit_price REAL,
  reason TEXT, approved INTEGER NOT NULL, block_reasons TEXT,
  notional_base REAL, est_commission_base REAL
);
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY, proposal_id INTEGER REFERENCES proposals(id), ts TEXT NOT NULL,
  broker_order_id INTEGER, symbol TEXT, action TEXT, quantity REAL, limit_price REAL,
  status TEXT, filled REAL, avg_fill_price REAL, message TEXT
);
CREATE TABLE IF NOT EXISTS ledger (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, kind TEXT NOT NULL CHECK (kind IN ('DEPOSIT','BUY','SELL')),
  symbol TEXT, currency TEXT, quantity REAL, price REAL, commission REAL,
  fx_to_base REAL, amount_base REAL NOT NULL, broker_order_id INTEGER
);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS snapshots (
  run_id INTEGER NOT NULL REFERENCES runs(id), key TEXT NOT NULL, quantity REAL, price_base REAL,
  PRIMARY KEY (run_id, key)
);
CREATE TABLE IF NOT EXISTS llm_usage (
  id INTEGER PRIMARY KEY, run_id INTEGER REFERENCES runs(id), ts TEXT NOT NULL, provider TEXT, model TEXT,
  input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER, cache_write_tokens INTEGER,
  web_searches INTEGER, cost_usd REAL NOT NULL
);
"""


def _now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


class Journal:
    def __init__(self, path: Path | str = DEFAULT_DB):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # -- state ----------------------------------------------------------------
    def _get(self, key: str, default: str | None = None) -> str | None:
        row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def _set(self, key: str, value: str) -> None:
        with self.db:
            self.db.execute("INSERT INTO state(key,value) VALUES(?,?) "
                            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def base_currency(self) -> str | None:
        return self._get("base_currency")

    def is_halted(self) -> bool:
        return self._get("halted", "0") == "1"

    def halt(self, reason: str) -> None:
        self._set("halted", "1")
        self._set("halted_reason", f"{_now()} {reason}")

    def reset_halt(self, peak_value_base: float) -> None:
        """Manual re-arm by the operator. Peak resets to current value so drawdown starts at 0."""
        self._set("halted", "0")
        self._set("halted_reason", "")
        self._set("peak_base", repr(peak_value_base))

    def peak(self) -> float:
        return float(self._get("peak_base", "0"))

    def update_peak(self, value_base: float) -> float:
        peak = max(self.peak(), value_base)
        self._set("peak_base", repr(peak))
        return peak

    # -- ledger -----------------------------------------------------------------
    def init_budget(self, amount: float, currency: str) -> None:
        if self.db.execute("SELECT 1 FROM ledger WHERE kind='DEPOSIT'").fetchone():
            raise RuntimeError("Budget already initialised; refusing to deposit twice.")
        if amount <= 0:
            raise ValueError("amount must be > 0")
        with self.db:
            self.db.execute("INSERT INTO ledger(ts,kind,currency,amount_base,fx_to_base) "
                            "VALUES(?,?,?,?,1.0)", (_now(), "DEPOSIT", currency.upper(), amount))
        self._set("base_currency", currency.upper())
        self._set("peak_base", repr(amount))

    def cash_base(self) -> float:
        return float(self.db.execute("SELECT COALESCE(SUM(amount_base),0) FROM ledger").fetchone()[0])

    def holdings_qty(self) -> dict[str, float]:
        rows = self.db.execute(
            "SELECT symbol || ':' || currency AS k, "
            "SUM(CASE kind WHEN 'BUY' THEN quantity WHEN 'SELL' THEN -quantity END) AS q "
            "FROM ledger WHERE kind IN ('BUY','SELL') GROUP BY k").fetchall()
        return {r["k"]: r["q"] for r in rows if r["q"] and abs(r["q"]) > 1e-9}

    def record_fill(self, symbol: str, currency: str, action: str, quantity: float, price: float,
                    commission: float, fx_to_base: float, broker_order_id: int | None = None) -> None:
        """Book a FILL (not an order). Price and commission in the instrument currency."""
        action = action.upper()
        gross = quantity * price
        amount = -(gross + commission) * fx_to_base if action == "BUY" else (gross - commission) * fx_to_base
        with self.db:
            self.db.execute(
                "INSERT INTO ledger(ts,kind,symbol,currency,quantity,price,commission,fx_to_base,amount_base,broker_order_id) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (_now(), action, symbol.upper(), currency.upper(), quantity, price, commission,
                 fx_to_base, amount, broker_order_id))

    # -- runs / proposals / orders -------------------------------------------
    def start_run(self, mode: str) -> int:
        with self.db:
            return self.db.execute("INSERT INTO runs(started_at,mode) VALUES(?,?)", (_now(), mode)).lastrowid

    def finish_run(self, run_id: int, status: str, state: PortfolioState | None = None, notes: str = "") -> None:
        with self.db:
            self.db.execute(
                "UPDATE runs SET finished_at=?, status=?, value_base=?, cash_base=?, peak_base=?, drawdown_pct=?, notes=? WHERE id=?",
                (_now(), status,
                 state.value_base if state else None, state.cash_base if state else None,
                 state.peak_value_base if state else None, state.drawdown_pct if state else None,
                 notes, run_id))
            if state:  # holdings + prices at the end of the run, for the dashboard
                self.db.executemany(
                    "INSERT OR REPLACE INTO snapshots(run_id,key,quantity,price_base) VALUES(?,?,?,?)",
                    [(run_id, k, h.quantity, h.price_base) for k, h in state.holdings.items()])

    def record_decision(self, run_id: int, d: Decision) -> int:
        p = d.proposal
        with self.db:
            return self.db.execute(
                "INSERT INTO proposals(run_id,ts,symbol,exchange,currency,action,quantity,limit_price,reason,"
                "approved,block_reasons,notional_base,est_commission_base) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, _now(), p.symbol, p.exchange, p.currency, p.action.upper(), p.quantity, p.limit_price,
                 p.reason, int(d.approved), json.dumps(d.reasons), d.notional_base, d.commission_base)).lastrowid

    def record_order(self, proposal_id: int | None, r) -> int:
        """r: broker OrderResult."""
        with self.db:
            return self.db.execute(
                "INSERT INTO orders(proposal_id,ts,broker_order_id,symbol,action,quantity,limit_price,status,filled,avg_fill_price,message) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (proposal_id, _now(), r.order_id, r.symbol, r.action, r.quantity, r.limit_price,
                 r.status, r.filled, r.avg_fill_price, r.message)).lastrowid

    def orders_this_month(self, now: datetime | None = None) -> int:
        """Counts orders SUBMITTED this calendar month (Sydney) - filled or not."""
        now = now or datetime.now(TZ)
        month = now.astimezone(TZ).strftime("%Y-%m")
        return int(self.db.execute("SELECT COUNT(*) FROM orders WHERE substr(ts,1,7)=?", (month,)).fetchone()[0])

    # -- LLM spend --------------------------------------------------------------
    def record_llm_usage(self, run_id: int | None, provider: str, model: str, usage, cost_usd: float) -> None:
        g = lambda n: int(getattr(usage, n, 0) or 0)  # noqa: E731
        stu = getattr(usage, "server_tool_use", None)
        searches = int(getattr(stu, "web_search_requests", 0) or 0) if stu is not None else 0
        with self.db:
            self.db.execute(
                "INSERT INTO llm_usage(run_id,ts,provider,model,input_tokens,output_tokens,cache_read_tokens,"
                "cache_write_tokens,web_searches,cost_usd) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (run_id, _now(), provider, model, g("input_tokens"), g("output_tokens"),
                 g("cache_read_input_tokens"), g("cache_creation_input_tokens"), searches, cost_usd))

    def llm_spend_usd(self, month: str | None = None) -> float:
        """USD spent this calendar month (Sydney), or for `month`='YYYY-MM'; month='all' for lifetime."""
        if month == "all":
            return float(self.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage").fetchone()[0])
        month = month or datetime.now(TZ).strftime("%Y-%m")
        return float(self.db.execute("SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE substr(ts,1,7)=?",
                                     (month,)).fetchone()[0])

    # -- the view the gate needs ----------------------------------------------
    def portfolio_state(self, prices_base: dict[str, float]) -> PortfolioState:
        """prices_base: instrument key -> current price in base currency (for every holding)."""
        holdings = {}
        for key, qty in self.holdings_qty().items():
            if key not in prices_base:
                raise KeyError(f"no price for held instrument {key}; refusing to value portfolio")
            holdings[key] = Holding(qty, prices_base[key])
        state = PortfolioState(cash_base=self.cash_base(), holdings=holdings,
                               peak_value_base=self.peak(), trades_this_month=self.orders_this_month(),
                               halted=self.is_halted())
        state.peak_value_base = self.update_peak(state.value_base)
        return state
