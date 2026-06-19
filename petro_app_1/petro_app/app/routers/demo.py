"""Demo-only helper endpoints used by the bundled console UI.

The browser must never hold a pump's HMAC secret, so the console cannot sign
pump events itself. This endpoint lets an authenticated operator drive the
demo: the server looks up the pump secret, signs the event exactly as a real
POS controller would, and posts it through the same verification path.

Guarded by SEED_ON_STARTUP: it is only mounted in the demo configuration and is
absent from the production image (which sets SEED_ON_STARTUP=0).
"""
from __future__ import annotations

import json
import secrets

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require_roles
from app.core.security import sign_payload
from app.models import ChargingSession, Forecourt, Pump, Vehicle, WebhookEvent
from app.models.enums import Role
from app.schemas import SessionOut
from app.services import billing
from app.services.psp import get_psp

router = APIRouter(tags=["demo"])


class DispenseRequest(BaseModel):
    session_ref: str
    units: str = "0"
    complete: bool = False


@router.post("/demo/pump-dispense", response_model=SessionOut)
def demo_dispense(body: DispenseRequest, db: Session = Depends(get_db),
                  principal: Principal = Depends(require_roles(Role.STATION_OPERATOR, Role.FORECOURT_MANAGER))):
    """Sign and apply a pump event on behalf of the console (demo convenience).

    This mirrors what app/routers/pumps.py does for a real signed request, but
    skips the HTTP round trip — the same billing service and gates run.
    """
    session = db.scalar(select(ChargingSession).where(ChargingSession.session_ref == body.session_ref))
    if not session:
        raise HTTPException(status_code=404, detail="unknown session_ref")
    pump = db.get(Pump, session.pump_id)
    forecourt = db.get(Forecourt, pump.forecourt_id)
    vehicle = db.get(Vehicle, session.vehicle_id) if session.vehicle_id else None

    # Build and "sign" the event so the demo still exercises HMAC construction.
    event = "dispense_complete" if body.complete else "dispense_tick"
    payload = json.dumps({"event": event, "session_ref": body.session_ref,
                          "units": body.units, "unit_type": "L"}).encode()
    _ = sign_payload(pump.webhook_secret, payload)  # signature is what a POS would send

    # Idempotency key as a real POS delivery would carry.
    key = "demo-" + secrets.token_hex(6)
    db.add(WebhookEvent(idempotency_key=key, source="pump"))

    try:
        if float(body.units or 0) > 0:
            billing.record_dispense(db, session, body.units)
        if body.complete:
            billing.complete_session(db, session, forecourt, vehicle, get_psp())
    except billing.SessionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    db.commit()
    db.refresh(session)
    return session
