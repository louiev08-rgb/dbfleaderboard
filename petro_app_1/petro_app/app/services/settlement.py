"""Settlement & reconciliation service (FR-28..31, TDS 3.3 / section 8).

Reconciles captured payments against dispensed fuel per forecourt and per day,
recording gross, PSP fees, and net payout. Also surfaces exceptions: sessions
that dispensed fuel without a matching successful capture (FR-31).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ChargingSession, Forecourt, Payment, Settlement, TransactionLog
from app.models.enums import PaymentState, SessionState
from app.services.money import money


def run_reconciliation(db: Session, retailer_id: int | None = None, period: str | None = None) -> list[Settlement]:
    """Build (or refresh) per-forecourt, per-day settlement rows from captured
    payments. Idempotent for a given (forecourt, period): an existing row is
    updated rather than duplicated.

    `period` is a YYYY-MM-DD string; defaults to today (UTC).
    """
    target_period = period or date.today().isoformat()

    # Gather captured/settled payments joined to their session + forecourt.
    stmt = (
        select(Payment, TransactionLog, Forecourt)
        .join(TransactionLog, TransactionLog.payment_id == Payment.id)
        .join(Forecourt, Forecourt.id == TransactionLog.forecourt_id)
        .where(Payment.state.in_([PaymentState.CAPTURED, PaymentState.SETTLED]))
    )
    if retailer_id is not None:
        stmt = stmt.where(Forecourt.retailer_id == retailer_id)

    rollup: dict[tuple[int, int], dict[str, object]] = defaultdict(
        lambda: {"gross": money(0), "fees": money(0), "net": money(0)}
    )
    for payment, log, forecourt in db.execute(stmt).all():
        if log.ts.date().isoformat() != target_period:
            continue
        key = (forecourt.retailer_id, forecourt.id)
        rollup[key]["gross"] = money(rollup[key]["gross"] + money(payment.amount_captured))
        rollup[key]["fees"] = money(rollup[key]["fees"] + money(payment.fee))
        rollup[key]["net"] = money(rollup[key]["net"] + money(payment.net))

    results: list[Settlement] = []
    for (rid, fid), totals in rollup.items():
        existing = db.scalar(
            select(Settlement).where(
                Settlement.forecourt_id == fid, Settlement.period == target_period
            )
        )
        if existing:
            existing.gross = totals["gross"]
            existing.fees = totals["fees"]
            existing.net = totals["net"]
            existing.status = "reconciled"
            results.append(existing)
        else:
            s = Settlement(
                retailer_id=rid, forecourt_id=fid, period=target_period,
                gross=totals["gross"], fees=totals["fees"], net=totals["net"],
                status="reconciled",
            )
            db.add(s)
            results.append(s)
    db.flush()
    return results


def find_unmatched_sessions(db: Session, retailer_id: int | None = None) -> list[ChargingSession]:
    """Sessions that dispensed fuel but have no captured payment — flagged for
    investigation (FR-31)."""
    stmt = select(ChargingSession).where(
        ChargingSession.state == SessionState.COMPLETED,
        ChargingSession.dispensed > 0,
    )
    rows = list(db.scalars(stmt))
    unmatched = []
    for s in rows:
        payment = db.get(Payment, s.payment_id) if s.payment_id else None
        if payment is None or PaymentState(payment.state) not in (PaymentState.CAPTURED, PaymentState.SETTLED):
            unmatched.append(s)
    return unmatched
