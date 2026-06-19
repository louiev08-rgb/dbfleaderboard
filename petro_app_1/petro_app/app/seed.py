"""Seed demo data so the API is explorable immediately (TDS demo target).

Creates a platform admin, one retailer with a forecourt and two pumps, staff
users for each role, a customer with a card on file, and a few vehicles
(including one flagged stolen to demonstrate the gate).

Default password for every seeded account is 'password123'.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import Coupon, Customer, Forecourt, PaymentMethod, Pump, Retailer, User, Vehicle
from app.models.enums import PaymentMethodType, Role, VehicleFlag, VehicleType
from app.services.psp import get_psp

DEFAULT_PASSWORD = "password123"


def seed(db: Session) -> None:
    if db.scalar(select(User).where(User.email == "admin@petro.example")):
        return  # already seeded

    pw = hash_password(DEFAULT_PASSWORD)

    # Platform admin (no tenant).
    db.add(User(email="admin@petro.example", name="Platform Admin", password_hash=pw,
                role=Role.PLATFORM_ADMIN))

    # Retailer + forecourt + pumps.
    retailer = Retailer(name="ACME Fuel Co")
    db.add(retailer)
    db.flush()

    forecourt = Forecourt(retailer_id=retailer.id, name="ACME N1 Plaza", site_code="N1-001")
    db.add(forecourt)
    db.flush()

    pump1 = Pump(forecourt_id=forecourt.id, label="Pump 1", mode=VehicleType.FUEL,
                 pos_device_id="POS-481", webhook_secret="pump1secret")
    pump2 = Pump(forecourt_id=forecourt.id, label="Pump 2 (EV)", mode=VehicleType.EV,
                 pos_device_id="POS-482", webhook_secret="pump2secret")
    db.add_all([pump1, pump2])

    # Staff users scoped to the retailer / forecourt.
    db.add_all([
        User(email="retailer@acme.example", name="Retailer Admin", password_hash=pw,
             role=Role.RETAILER_ADMIN, retailer_id=retailer.id),
        User(email="manager@acme.example", name="Forecourt Manager", password_hash=pw,
             role=Role.FORECOURT_MANAGER, retailer_id=retailer.id, forecourt_id=forecourt.id),
        User(email="attendant@acme.example", name="Attendant", password_hash=pw,
             role=Role.STATION_OPERATOR, retailer_id=retailer.id, forecourt_id=forecourt.id),
        User(email="finance@acme.example", name="Finance/Audit", password_hash=pw,
             role=Role.FINANCE_AUDIT, retailer_id=retailer.id),
    ])

    # Customer with a tokenised card on file.
    customer = Customer(email="driver@example.com", name="Demo Driver", phone="0820000000",
                        password_hash=pw)
    db.add(customer)
    db.flush()
    token, mask = get_psp().tokenise_card("4242424242424242", "12/29", "123")
    db.add(PaymentMethod(customer_id=customer.id, type=PaymentMethodType.CARD,
                         psp_token=token, card_mask=mask, is_default=True))

    # Vehicles (one stolen to demonstrate the gate).
    v1 = Vehicle(retailer_id=retailer.id, customer_id=customer.id, plate="ABC123GP",
                 nickname="Demo Driver's car", type=VehicleType.FUEL, flag=VehicleFlag.OK,
                 wallet_balance=500)
    v2 = Vehicle(retailer_id=retailer.id, plate="EV1NEV", nickname="Fleet EV",
                 type=VehicleType.EV, flag=VehicleFlag.OK, wallet_balance=0)
    v3 = Vehicle(retailer_id=retailer.id, plate="STOL3N", nickname="Reported stolen",
                 type=VehicleType.FUEL, flag=VehicleFlag.STOLEN, wallet_balance=0)
    db.add_all([v1, v2, v3])
    db.flush()
    db.add(Coupon(vehicle_id=v1.id, value=100))

    db.commit()
