"""Payment service: drives the Payment state machine (TDS 3.1) via the PSP.

Allowed transitions:
    CREATED -> AUTHORISED -> CAPTURED -> SETTLED
    CREATED -> DECLINED
    AUTHORISED -> VOIDED
    CAPTURED -> REFUNDED
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from app.models import Payment, PaymentMethod
from app.models.enums import PAYMENT_TRANSITIONS, PaymentState
from app.services.money import money
from app.services.psp import PSPAdapter


class PaymentError(Exception):
    pass


_ALLOWED = PAYMENT_TRANSITIONS


def _transition(payment: Payment, to: PaymentState) -> None:
    current = PaymentState(payment.state)
    if to not in _ALLOWED[current]:
        raise PaymentError(f"illegal payment transition {current.value} -> {to.value}")
    payment.state = to


def create_payment(db: Session, method: PaymentMethod | None, currency: str) -> Payment:
    payment = Payment(method_id=method.id if method else None, state=PaymentState.CREATED, currency=currency)
    db.add(payment)
    db.flush()
    return payment


def authorise(db: Session, payment: Payment, method: PaymentMethod, amount, psp: PSPAdapter) -> Payment:
    """Pre-authorise a ceiling amount against the card token (TDS 3.3)."""
    amount = money(amount)
    result = psp.authorise(method.psp_token or "", amount, payment.currency)
    if not result.ok:
        _transition(payment, PaymentState.DECLINED)
        db.flush()
        raise PaymentError("authorisation declined")
    payment.amount_authorised = amount
    payment.psp_reference = result.reference
    _transition(payment, PaymentState.AUTHORISED)
    db.flush()
    return payment


def capture(db: Session, payment: Payment, amount, psp: PSPAdapter) -> Payment:
    """Capture the exact dispensed amount; must be <= authorised (TDS 5.2)."""
    amount = money(amount)
    if amount > money(payment.amount_authorised):
        raise PaymentError("capture amount exceeds authorised amount")
    result = psp.capture(payment.psp_reference or "", amount)
    if not result.ok:
        raise PaymentError("capture failed")
    fee = getattr(psp, "fee_for", lambda a: money(0))(amount)
    payment.amount_captured = amount
    payment.fee = money(fee)
    payment.net = money(amount - money(fee))
    _transition(payment, PaymentState.CAPTURED)
    db.flush()
    return payment


def void(db: Session, payment: Payment, psp: PSPAdapter) -> Payment:
    """Release an unused authorisation when no fuel was dispensed (FR-14)."""
    psp.void(payment.psp_reference or "")
    _transition(payment, PaymentState.VOIDED)
    db.flush()
    return payment


def refund(db: Session, payment: Payment, amount, psp: PSPAdapter) -> Payment:
    amount = money(amount)
    if amount > money(payment.amount_captured):
        raise PaymentError("refund exceeds captured amount")
    result = psp.refund(payment.psp_reference or "", amount)
    if not result.ok:
        raise PaymentError("refund failed")
    _transition(payment, PaymentState.REFUNDED)
    db.flush()
    return payment


def mark_settled(db: Session, payment: Payment) -> Payment:
    """Advance a captured payment to settled on a PSP settlement webhook (TDS 3.3)."""
    _transition(payment, PaymentState.SETTLED)
    db.flush()
    return payment
