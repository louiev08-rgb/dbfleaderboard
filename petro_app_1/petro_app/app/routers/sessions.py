"""Session lifecycle: attendant opens a session, customer/system pre-authorises
payment (FR-22, TDS 6). Dispensing and completion are driven by pump webhooks."""
from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import Principal, get_principal, require_roles
from app.models import PaymentMethod, Pump, Vehicle
from app.models.enums import Role
from app.schemas import PaymentOut, SessionAuthorise, SessionOpen, SessionOut
from app.services import billing
from app.services.psp import get_psp

router = APIRouter(tags=["sessions"])


@router.post("/sessions", response_model=SessionOut, status_code=201)
def open_session(body: SessionOpen, db: Session = Depends(get_db),
                 principal: Principal = Depends(require_roles(Role.STATION_OPERATOR, Role.FORECOURT_MANAGER))):
    pump = db.get(Pump, body.pump_id)
    if not pump:
        raise HTTPException(status_code=404, detail="pump not found")
    vehicle = db.get(Vehicle, body.vehicle_id) if body.vehicle_id else None
    try:
        session = billing.open_session(
            db, pump=pump, vehicle=vehicle, customer_id=body.customer_id,
            operator_id=principal.user_id, target=body.target,
            price_per_unit=body.price_per_unit, mode=body.mode,
        )
    except billing.SessionError as exc:
        db.commit()  # persist the REFUSED session for audit
        raise HTTPException(status_code=409, detail=str(exc))
    db.commit()
    db.refresh(session)
    return session


@router.post("/sessions/{session_id}/authorise", response_model=PaymentOut)
def authorise(session_id: int, body: SessionAuthorise, db: Session = Depends(get_db),
              principal: Principal = Depends(get_principal)):
    from app.models import ChargingSession
    session = db.get(ChargingSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")
    method = db.get(PaymentMethod, body.method_id)
    if not method:
        raise HTTPException(status_code=404, detail="payment method not found")
    # Customers may only authorise against their own card.
    if principal.role == Role.CUSTOMER and method.customer_id != principal.customer_id:
        raise HTTPException(status_code=403, detail="not your payment method")
    ceiling = body.ceiling if body.ceiling is not None else Decimal(settings.PREAUTH_CEILING)
    try:
        payment = billing.authorise_session(db, session, method, ceiling, get_psp())
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=402, detail=f"authorisation failed: {exc}")
    db.commit()
    db.refresh(payment)
    return payment
