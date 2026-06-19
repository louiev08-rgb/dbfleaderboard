"""ORM models mapping the TDS Entity-Relationship Diagram (Figure 5).

Tenant-owned tables carry retailer_id (directly or via a parent) for row-level
isolation. Monetary columns use Numeric(12,2); dispensed units Numeric(12,3).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, CheckConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import (
    PaymentMethodType, PaymentState, RetailerStatus, Role, SessionState, VehicleFlag, VehicleType,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Tenancy hierarchy: Retailer -> Forecourt -> Pump
# --------------------------------------------------------------------------- #
class Retailer(Base):
    __tablename__ = "retailers"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[RetailerStatus] = mapped_column(String(20), default=RetailerStatus.ACTIVE, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    forecourts: Mapped[list["Forecourt"]] = relationship(back_populates="retailer", cascade="all, delete-orphan")


class Forecourt(Base):
    __tablename__ = "forecourts"
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    site_code: Mapped[str] = mapped_column(String(50), nullable=False)
    timezone: Mapped[str] = mapped_column(String(50), default="Africa/Johannesburg")
    status: Mapped[str] = mapped_column(String(20), default="active")

    retailer: Mapped[Retailer] = relationship(back_populates="forecourts")
    pumps: Mapped[list["Pump"]] = relationship(back_populates="forecourt", cascade="all, delete-orphan")


class Pump(Base):
    __tablename__ = "pumps"
    id: Mapped[int] = mapped_column(primary_key=True)
    forecourt_id: Mapped[int] = mapped_column(ForeignKey("forecourts.id"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(50), nullable=False)
    mode: Mapped[VehicleType] = mapped_column(String(10), default=VehicleType.FUEL)
    pos_device_id: Mapped[str | None] = mapped_column(String(100))
    webhook_secret: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active")

    forecourt: Mapped[Forecourt] = relationship(back_populates="pumps")


# --------------------------------------------------------------------------- #
# Identity: staff Users with Roles, and Customers (payers)
# --------------------------------------------------------------------------- #
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int | None] = mapped_column(ForeignKey("retailers.id"), nullable=True, index=True)
    forecourt_id: Mapped[int | None] = mapped_column(ForeignKey("forecourts.id"), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[Role] = mapped_column(String(30), nullable=False)
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    phone: Mapped[str | None] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(200))
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    payment_methods: Mapped[list["PaymentMethod"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan"
    )


# --------------------------------------------------------------------------- #
# Vehicles, payment methods, coupons
# --------------------------------------------------------------------------- #
class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("retailer_id", "plate", name="uq_vehicle_plate_per_retailer"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), nullable=False, index=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    plate: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    nickname: Mapped[str | None] = mapped_column(String(100))
    type: Mapped[VehicleType] = mapped_column(String(10), default=VehicleType.FUEL)
    flag: Mapped[VehicleFlag] = mapped_column(String(10), default=VehicleFlag.OK)
    wallet_balance: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    coupons: Mapped[list["Coupon"]] = relationship(back_populates="vehicle", cascade="all, delete-orphan")


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False, index=True)
    type: Mapped[PaymentMethodType] = mapped_column(String(10), nullable=False)
    # Card-on-file: only the PSP token + a display mask are stored, never the PAN.
    psp_token: Mapped[str | None] = mapped_column(String(255))
    card_mask: Mapped[str | None] = mapped_column(String(30))
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    customer: Mapped[Customer] = relationship(back_populates="payment_methods")


class Coupon(Base):
    __tablename__ = "coupons"
    id: Mapped[int] = mapped_column(primary_key=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    vehicle: Mapped[Vehicle] = relationship(back_populates="coupons")


# --------------------------------------------------------------------------- #
# Sessions, payments, logs, settlement, audit
# --------------------------------------------------------------------------- #
class ChargingSession(Base):
    __tablename__ = "charging_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_ref: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    pump_id: Mapped[int] = mapped_column(ForeignKey("pumps.id"), nullable=False, index=True)
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"), nullable=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), nullable=True)
    operator_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)

    mode: Mapped[VehicleType] = mapped_column(String(10), default=VehicleType.FUEL)
    target: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    price_per_unit: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    dispensed: Mapped[float] = mapped_column(Numeric(12, 3), default=0)
    state: Mapped[SessionState] = mapped_column(String(20), default=SessionState.CREATED)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    payment: Mapped["Payment"] = relationship(foreign_keys=[payment_id])


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_captured <= amount_authorised", name="ck_capture_le_auth"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int | None] = mapped_column(ForeignKey("charging_sessions.id"), nullable=True, index=True)
    method_id: Mapped[int | None] = mapped_column(ForeignKey("payment_methods.id"), nullable=True)
    state: Mapped[PaymentState] = mapped_column(String(20), default=PaymentState.CREATED, index=True)
    amount_authorised: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    amount_captured: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    fee: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    net: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="ZAR")
    psp_reference: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class TransactionLog(Base):
    __tablename__ = "transaction_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("charging_sessions.id"), index=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("payments.id"), nullable=True)
    forecourt_id: Mapped[int] = mapped_column(ForeignKey("forecourts.id"), index=True)
    plate: Mapped[str | None] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(10))
    units: Mapped[float] = mapped_column(Numeric(12, 3))
    unit_type: Mapped[str] = mapped_column(String(5))
    price_per_unit: Mapped[float] = mapped_column(Numeric(12, 2))
    total: Mapped[float] = mapped_column(Numeric(12, 2))
    payment_outcome: Mapped[str] = mapped_column(String(20))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Settlement(Base):
    __tablename__ = "settlements"
    id: Mapped[int] = mapped_column(primary_key=True)
    retailer_id: Mapped[int] = mapped_column(ForeignKey("retailers.id"), index=True)
    forecourt_id: Mapped[int] = mapped_column(ForeignKey("forecourts.id"), index=True)
    period: Mapped[str] = mapped_column(String(10))  # YYYY-MM-DD
    gross: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    fees: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    net: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    payout_reference: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default="pending")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    retailer_id: Mapped[int | None] = mapped_column(ForeignKey("retailers.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(80))
    entity: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[str | None] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(Text)
    ip_address: Mapped[str | None] = mapped_column(String(50))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class WebhookEvent(Base):
    """Idempotency ledger: a seen idempotency key short-circuits re-processing
    so a retried pump/PSP delivery never double-bills (TDS 3.4)."""
    __tablename__ = "webhook_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    source: Mapped[str] = mapped_column(String(20))  # 'pump' | 'psp'
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
