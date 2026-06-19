"""Enumerations used across the domain model.

These encode the controlled vocabularies from the BRD/TDS: roles, vehicle and
session states, payment-method types, and the Payment state machine.
"""
from __future__ import annotations

import enum


class Role(str, enum.Enum):
    PLATFORM_ADMIN = "platform_admin"
    RETAILER_ADMIN = "retailer_admin"
    FORECOURT_MANAGER = "forecourt_manager"
    STATION_OPERATOR = "station_operator"
    FINANCE_AUDIT = "finance_audit"
    CUSTOMER = "customer"  # separate principal/scope (TDS 4.1)


class RetailerStatus(str, enum.Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class VehicleType(str, enum.Enum):
    FUEL = "fuel"
    EV = "ev"


class VehicleFlag(str, enum.Enum):
    OK = "ok"
    STOLEN = "stolen"


class SessionState(str, enum.Enum):
    CREATED = "created"
    DISPENSING = "dispensing"
    PAUSED = "paused"
    COMPLETED = "completed"
    REFUSED = "refused"       # stolen-vehicle gate
    FAILED = "failed"         # payment failed / unrecoverable


class PaymentMethodType(str, enum.Enum):
    CARD = "card"
    WALLET = "wallet"
    COUPON = "coupon"


class PaymentState(str, enum.Enum):
    """Payment state machine from TDS section 3.1 / Figure 2."""
    CREATED = "created"
    AUTHORISED = "authorised"
    CAPTURED = "captured"
    SETTLED = "settled"
    VOIDED = "voided"          # unused pre-auth released
    REFUNDED = "refunded"
    DECLINED = "declined"      # auth declined / capture failed


# Allowed Payment state transitions (single source of truth, dependency-free).
PAYMENT_TRANSITIONS: dict[PaymentState, set[PaymentState]] = {
    PaymentState.CREATED: {PaymentState.AUTHORISED, PaymentState.DECLINED},
    PaymentState.AUTHORISED: {PaymentState.CAPTURED, PaymentState.VOIDED, PaymentState.DECLINED},
    PaymentState.CAPTURED: {PaymentState.SETTLED, PaymentState.REFUNDED},
    PaymentState.SETTLED: {PaymentState.REFUNDED},
    PaymentState.VOIDED: set(),
    PaymentState.REFUNDED: set(),
    PaymentState.DECLINED: set(),
}
