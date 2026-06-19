"""Platform administration & tenancy: retailers, forecourts, pumps (FR-39..43)."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require_roles
from app.models import AuditLog, Forecourt, Pump, Retailer
from app.models.enums import Role
from app.schemas import (
    ForecourtCreate, ForecourtOut, PumpCreate, PumpOut, RetailerCreate, RetailerOut, RetailerStatusUpdate,
)

router = APIRouter(tags=["admin"])


def _audit(db: Session, principal: Principal, action: str, entity: str, entity_id, detail: str = "") -> None:
    db.add(AuditLog(user_id=principal.user_id, retailer_id=principal.retailer_id,
                    action=action, entity=entity, entity_id=str(entity_id), detail=detail))


@router.post("/admin/retailers", response_model=RetailerOut, status_code=201)
def create_retailer(body: RetailerCreate, db: Session = Depends(get_db),
                    principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN))):
    retailer = Retailer(name=body.name)
    db.add(retailer)
    db.flush()
    _audit(db, principal, "create_retailer", "retailer", retailer.id, body.name)
    db.commit()
    db.refresh(retailer)
    return retailer


@router.get("/admin/retailers", response_model=list[RetailerOut])
def list_retailers(db: Session = Depends(get_db),
                   principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN))):
    return list(db.scalars(select(Retailer)))


@router.patch("/admin/retailers/{retailer_id}", response_model=RetailerOut)
def set_retailer_status(retailer_id: int, body: RetailerStatusUpdate, db: Session = Depends(get_db),
                        principal: Principal = Depends(require_roles(Role.PLATFORM_ADMIN))):
    retailer = db.get(Retailer, retailer_id)
    if not retailer:
        raise HTTPException(status_code=404, detail="retailer not found")
    retailer.status = body.status
    _audit(db, principal, "set_retailer_status", "retailer", retailer.id, body.status.value)
    db.commit()
    db.refresh(retailer)
    return retailer


@router.post("/forecourts", response_model=ForecourtOut, status_code=201)
def create_forecourt(body: ForecourtCreate, db: Session = Depends(get_db),
                     principal: Principal = Depends(require_roles(Role.RETAILER_ADMIN, Role.PLATFORM_ADMIN))):
    if principal.role == Role.RETAILER_ADMIN and principal.retailer_id is None:
        raise HTTPException(status_code=403, detail="no retailer scope on token")
    retailer_id = principal.retailer_id
    if retailer_id is None:
        raise HTTPException(status_code=400, detail="platform admin must impersonate a retailer to create forecourts")
    forecourt = Forecourt(retailer_id=retailer_id, name=body.name, site_code=body.site_code, timezone=body.timezone)
    db.add(forecourt)
    db.flush()
    _audit(db, principal, "create_forecourt", "forecourt", forecourt.id, body.name)
    db.commit()
    db.refresh(forecourt)
    return forecourt


@router.post("/forecourts/{forecourt_id}/pumps", response_model=PumpOut, status_code=201)
def create_pump(forecourt_id: int, body: PumpCreate, db: Session = Depends(get_db),
                principal: Principal = Depends(require_roles(Role.RETAILER_ADMIN, Role.FORECOURT_MANAGER))):
    forecourt = db.get(Forecourt, forecourt_id)
    if not forecourt:
        raise HTTPException(status_code=404, detail="forecourt not found")
    if principal.retailer_id is not None and forecourt.retailer_id != principal.retailer_id:
        raise HTTPException(status_code=403, detail="forecourt belongs to another retailer")
    pump = Pump(forecourt_id=forecourt_id, label=body.label, mode=body.mode,
                pos_device_id=body.pos_device_id, webhook_secret=secrets.token_hex(16))
    db.add(pump)
    db.flush()
    _audit(db, principal, "create_pump", "pump", pump.id, body.label)
    db.commit()
    db.refresh(pump)
    return pump
