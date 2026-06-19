"""Garage & vehicle management (FR-32..34), tenant-scoped."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require_roles
from app.models import Coupon, Vehicle
from app.models.enums import Role
from app.schemas import VehicleCreate, VehicleOut
from app.services.money import money

router = APIRouter(tags=["vehicles"])

# Manager-level roles permitted to maintain the garage (TDS 4.1).
_MANAGER_ROLES = (Role.RETAILER_ADMIN, Role.FORECOURT_MANAGER)


@router.post("/vehicles", response_model=VehicleOut, status_code=201)
def add_vehicle(body: VehicleCreate, db: Session = Depends(get_db),
                principal: Principal = Depends(require_roles(*_MANAGER_ROLES))):
    if principal.retailer_id is None:
        raise HTTPException(status_code=403, detail="retailer scope required")
    existing = db.scalar(select(Vehicle).where(
        Vehicle.retailer_id == principal.retailer_id, Vehicle.plate == body.plate.upper()))
    if existing:
        existing.nickname = body.nickname
        existing.type = body.type
        existing.flag = body.flag
        existing.wallet_balance = money(body.wallet_balance)
        vehicle = existing
    else:
        vehicle = Vehicle(retailer_id=principal.retailer_id, plate=body.plate.upper(),
                          nickname=body.nickname, type=body.type, flag=body.flag,
                          wallet_balance=money(body.wallet_balance))
        db.add(vehicle)
        db.flush()
    # replace coupons
    for c in list(vehicle.coupons):
        db.delete(c)
    for val in body.coupons:
        db.add(Coupon(vehicle_id=vehicle.id, value=money(val)))
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get("/vehicles", response_model=list[VehicleOut])
def list_vehicles(db: Session = Depends(get_db),
                  principal: Principal = Depends(require_roles(*_MANAGER_ROLES, Role.STATION_OPERATOR))):
    stmt = select(Vehicle)
    if principal.retailer_id is not None:
        stmt = stmt.where(Vehicle.retailer_id == principal.retailer_id)
    return list(db.scalars(stmt))


@router.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: int, db: Session = Depends(get_db),
                   principal: Principal = Depends(require_roles(*_MANAGER_ROLES))):
    vehicle = db.get(Vehicle, vehicle_id)
    if not vehicle or (principal.retailer_id is not None and vehicle.retailer_id != principal.retailer_id):
        raise HTTPException(status_code=404, detail="vehicle not found")
    db.delete(vehicle)
    db.commit()
