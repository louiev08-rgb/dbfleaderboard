"""Pydantic request/response schemas."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import (
    PaymentMethodType, PaymentState, RetailerStatus, Role, SessionState, VehicleFlag, VehicleType,
)


# --- auth ---
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role


# --- retailer / forecourt / pump ---
class RetailerCreate(BaseModel):
    name: str


class RetailerOut(BaseModel):
    id: int
    name: str
    status: RetailerStatus

    class Config:
        from_attributes = True


class RetailerStatusUpdate(BaseModel):
    status: RetailerStatus


class ForecourtCreate(BaseModel):
    name: str
    site_code: str
    timezone: str = "Africa/Johannesburg"


class ForecourtOut(BaseModel):
    id: int
    retailer_id: int
    name: str
    site_code: str

    class Config:
        from_attributes = True


class PumpCreate(BaseModel):
    label: str
    mode: VehicleType = VehicleType.FUEL
    pos_device_id: str | None = None


class PumpOut(BaseModel):
    id: int
    forecourt_id: int
    label: str
    mode: VehicleType
    webhook_secret: str  # returned once on creation so the POS can be configured

    class Config:
        from_attributes = True


# --- customer / payment method ---
class CustomerRegister(BaseModel):
    email: EmailStr
    name: str
    password: str = Field(min_length=6)
    phone: str | None = None


class CustomerOut(BaseModel):
    id: int
    email: EmailStr
    name: str

    class Config:
        from_attributes = True


class CardOnFileCreate(BaseModel):
    """Demo only: card details are immediately tokenised by the (mock) PSP and
    discarded. A production app collects these in the PSP SDK, never our API."""
    card_number: str
    exp: str
    cvv: str
    make_default: bool = True
    consent: bool = True


class PaymentMethodOut(BaseModel):
    id: int
    type: PaymentMethodType
    card_mask: str | None
    is_default: bool

    class Config:
        from_attributes = True


# --- vehicle ---
class VehicleCreate(BaseModel):
    plate: str
    nickname: str | None = None
    type: VehicleType = VehicleType.FUEL
    flag: VehicleFlag = VehicleFlag.OK
    wallet_balance: Decimal = Decimal("0")
    coupons: list[Decimal] = []


class VehicleOut(BaseModel):
    id: int
    plate: str
    nickname: str | None
    type: VehicleType
    flag: VehicleFlag
    wallet_balance: Decimal

    class Config:
        from_attributes = True


# --- session ---
class SessionOpen(BaseModel):
    pump_id: int
    vehicle_id: int | None = None
    customer_id: int | None = None
    mode: VehicleType = VehicleType.FUEL
    target: Decimal
    price_per_unit: Decimal


class SessionAuthorise(BaseModel):
    method_id: int
    ceiling: Decimal | None = None  # defaults to configured PREAUTH_CEILING


class SessionOut(BaseModel):
    id: int
    session_ref: str
    pump_id: int
    state: SessionState
    mode: VehicleType
    target: Decimal
    price_per_unit: Decimal
    dispensed: Decimal
    payment_id: int | None

    class Config:
        from_attributes = True


# --- pump webhook ---
class PumpEvent(BaseModel):
    event: str = Field(examples=["dispense_tick", "dispense_complete"])
    session_ref: str
    units: Decimal = Decimal("0")
    unit_type: str = "L"
    timestamp: datetime | None = None


# --- payment ---
class PaymentOut(BaseModel):
    id: int
    state: PaymentState
    amount_authorised: Decimal
    amount_captured: Decimal
    fee: Decimal
    net: Decimal
    currency: str
    psp_reference: str | None

    class Config:
        from_attributes = True


class RefundRequest(BaseModel):
    amount: Decimal


# --- logbook ---
class LogEntryOut(BaseModel):
    id: int
    session_id: int
    forecourt_id: int
    plate: str | None
    mode: str
    units: Decimal
    unit_type: str
    price_per_unit: Decimal
    total: Decimal
    payment_outcome: str
    ts: datetime

    class Config:
        from_attributes = True
