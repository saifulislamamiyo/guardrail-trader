"""Executes APPROVED decisions and books fills. No decisions are made here."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from guardrail_trader.broker import IBKRBroker
from guardrail_trader.journal import Journal
from guardrail_trader.risk import Decision


@dataclass
class ExecutionReport:
    symbol: str
    action: str
    requested: float
    filled: float
    avg_price: float
    commission: float
    status: str


def execute(decisions: list[tuple[int, Decision]], broker: IBKRBroker, journal: Journal,
            fx: dict[str, float], fill_timeout: float = 120.0,
            log: Callable[[str], None] = print) -> list[ExecutionReport]:
    """decisions: (proposal_row_id, approved Decision). Sells go first (already ordered by the gate).

    Orders are DAY limit orders. We wait up to `fill_timeout` seconds, cancel whatever is
    still open, then book only what actually filled into the virtual ledger.
    """
    placed: list[tuple[int, Decision, int]] = []
    for pid, d in decisions:
        assert d.approved, "executor received a blocked decision"
        p = d.proposal
        contract = broker.stock(p.symbol, p.exchange, p.currency)
        r = broker.place_order(contract, p.action, p.quantity, limit_price=p.limit_price, wait_seconds=2)
        log(f"[exec] placed {p.action} {p.quantity:g} {p.symbol} @ {p.limit_price} -> id={r.order_id} {r.status}")
        placed.append((pid, d, r.order_id))

    broker.wait_for_orders([oid for *_, oid in placed], fill_timeout)

    reports = []
    for pid, d, oid in placed:
        status = broker.order_result(oid).status
        if status not in ("Filled", "Cancelled", "ApiCancelled", "Inactive"):
            status = broker.cancel_order(oid).status
        qty, avg, comm, comm_ccy = broker.fill_details(oid)
        p = d.proposal
        if qty > 0:
            # commission is booked in the instrument currency; convert if IBKR reported another one
            comm_in_instr = comm * (fx.get(comm_ccy, 1.0) / fx[p.currency]) if comm_ccy and comm_ccy != p.currency else comm
            journal.record_fill(p.symbol, p.currency, p.action, qty, avg, comm_in_instr, fx[p.currency], oid)
        journal.record_order(pid, broker.order_result(oid))
        log(f"[exec] {p.action} {p.symbol}: filled {qty:g}/{p.quantity:g} @ {avg if not math.isnan(avg) else '-'}"
            f" commission {comm:.2f} {comm_ccy} -> {status}")
        reports.append(ExecutionReport(p.symbol, p.action, p.quantity, qty, avg, comm, status))
    return reports
