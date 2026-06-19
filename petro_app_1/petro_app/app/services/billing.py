"""Session & billing service.

Implements the two control gates from the BRD/TDS:
  1. Stolen-vehicle gate before dispensing (FR-8).
  2. Payment-coverage gate: a session completes only when an authorisation
     covering the dispensed amount exists, and the captured amount is the exact
     dispensed total (FR-11/12/13, TDS 3.4).

The capture, payment record, and transaction log are written in one DB
transaction so a session is never half-billed (TDS 5.2).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    ChargingSession, Forecourt, Payment, PaymentMethod, Pump, TransactionLog, Vehicle,
)
from app.models.enums import PaymentMethodType, SessionState, VehicleFlag, VehicleType
from app.services import payments as pay
from app.services.money import money, units
from app.services.psp import PSPAdapter


class SessionError(Exception):
    pass


def new_session_ref() -> str:
    return "S-" + datetime.now(timezone.utc).strftime("%Y%m%d") + "-" + secrets.token_hex(3)


def open_session(db: Session, *, pump: Pump, vehicle: Vehicle | None, customer_id: int | None,
                 operator_id: int | None, target, price_per_unit, mode: VehicleType) -> ChargingSession:
    # Stolen-vehicle gate (FR-8): refuse before anything else.
    if vehicle is not None and VehicleFlag(vehicle.flag) == VehicleFlag.STOLEN:
        session = ChargingSession(
            session_ref=new_session_ref(), pump_id=pump.id,
            vehicle_id=vehicle.id, customer_id=customer_id, operator_id=operator_id,
            mode=mode, target=units(target), price_per_unit=money(price_per_unit),
            dispensed=0, state=SessionState.REFUSED,
            ended_at=datetime.now(timezone.utc),
        )
        db.add(session)
        db.flush()
        raise SessionError("refused: vehicle flagged as stolen")

    session = ChargingSession(
        session_ref=new_session_ref(), pump_id=pump.id,
        vehicle_id=vehicle.id if vehicle else None, customer_id=customer_id,
        operator_id=operator_id, mode=mode, target=units(target),
        price_per_unit=money(price_per_unit), dispensed=0, state=SessionState.CREATED,
    )
    db.add(session)
    db.flush()
    return session


def authorise_session(db: Session, session: ChargingSession, method: PaymentMethod,
                      ceiling, psp: PSPAdapter) -> Payment:
    """Pre-authorise the customer's card before fuelling (FR-13)."""
    payment = pay.create_payment(db, method, currency="ZAR")
    pay.authorise(db, payment, method, ceiling, psp)
    session.payment_id = payment.id
    session.state = SessionState.DISPENSING
    db.flush()
    return payment


def record_dispense(db: Session, session: ChargingSession, new_units) -> ChargingSession:
    """Apply a pump tick: accumulate dispensed units, capped at target."""
    if SessionState(session.state) not in (SessionState.DISPENSING, SessionState.CREATED, SessionState.PAUSED):
        raise SessionError(f"cannot dispense in state {session.state}")
    total = units(money(session.dispensed) if False else session.dispensed) + units(new_units)
    target = units(session.target)
    if target > 0 and total > target:
        total = target
    session.dispensed = units(total)
    if SessionState(session.state) == SessionState.CREATED:
        session.state = SessionState.DISPENSING
    db.flush()
    return session


def complete_session(db: Session, session: ChargingSession, forecourt: Forecourt,
                     vehicle: Vehicle | None, psp: PSPAdapter) -> TransactionLog:
    """Close the session: capture the dispensed amount and write the log atomically.

    Payment-coverage gate: total = price x dispensed must be covered by the
    existing authorisation. Capture the exact dispensed amount; the unused
    portion of the authorisation is released by the PSP.
    """
    dispensed = units(session.dispensed)
    total = money(money(session.price_per_unit) * dispensed)

    payment = db.get(Payment, session.payment_id) if session.payment_id else None
    if payment is None:
        raise SessionError("no payment/authorisation on session")
    if total > money(payment.amount_authorised):
        raise SessionError("authorisation does not cover dispensed total")

    if dispensed <= 0:
        # Nothing dispensed: release the hold rather than charging (FR-14).
        pay.void(db, payment, psp)
        session.state = SessionState.COMPLETED
        session.ended_at = datetime.now(timezone.utc)
        outcome = "voided"
    else:
        pay.capture(db, payment, total, psp)
        session.state = SessionState.COMPLETED
        session.ended_at = datetime.now(timezone.utc)
        outcome = "captured"

    unit_type = "kWh" if VehicleType(session.mode) == VehicleType.EV else "L"
    log = TransactionLog(
        session_id=session.id, payment_id=payment.id, forecourt_id=forecourt.id,
        plate=vehicle.plate if vehicle else None, mode=VehicleType(session.mode).value,
        units=dispensed, unit_type=unit_type, price_per_unit=money(session.price_per_unit),
        total=total if dispensed > 0 else money(0), payment_outcome=outcome,
    )
    db.add(log)
    db.flush()
    return log
