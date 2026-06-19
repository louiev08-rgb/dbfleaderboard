"""Pump POS webhook (FR-50..53, TDS 3.4).

Inbound dispensing events are authenticated by an HMAC-SHA256 signature over the
raw body using the pump's secret, and de-duplicated by idempotency key so a
retried delivery never double-bills. A 'dispense_complete' event triggers
capture and writes the transaction log atomically.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import verify_signature
from app.models import ChargingSession, Forecourt, Pump, Vehicle, WebhookEvent
from app.schemas import SessionOut
from app.services import billing
from app.services.psp import get_psp

router = APIRouter(tags=["pump-webhook"])


@router.post("/pumps/events", response_model=SessionOut)
async def pump_event(
    request: Request,
    db: Session = Depends(get_db),
    x_pump_id: int = Header(..., alias="X-Pump-Id"),
    x_signature: str = Header(..., alias="X-Signature"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
):
    raw = await request.body()

    pump = db.get(Pump, x_pump_id)
    if not pump:
        raise HTTPException(status_code=404, detail="unknown pump")

    # 1) Authenticate the event (FR-51).
    if not verify_signature(pump.webhook_secret, raw, x_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    # 2) Idempotency: a seen key returns the current session state without re-applying (FR-52).
    import json
    try:
        body = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    session = db.scalar(select(ChargingSession).where(ChargingSession.session_ref == body.get("session_ref")))
    if not session:
        raise HTTPException(status_code=404, detail="unknown session_ref")

    if db.scalar(select(WebhookEvent).where(WebhookEvent.idempotency_key == x_idempotency_key)):
        return session  # already processed; no double-billing

    db.add(WebhookEvent(idempotency_key=x_idempotency_key, source="pump"))

    event = body.get("event")
    forecourt = db.get(Forecourt, pump.forecourt_id)
    vehicle = db.get(Vehicle, session.vehicle_id) if session.vehicle_id else None

    try:
        if event == "dispense_tick":
            billing.record_dispense(db, session, body.get("units", 0))
        elif event == "dispense_complete":
            if body.get("units"):
                billing.record_dispense(db, session, body.get("units", 0))
            billing.complete_session(db, session, forecourt, vehicle, get_psp())
        else:
            raise HTTPException(status_code=400, detail=f"unknown event type: {event}")
    except billing.SessionError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))

    db.commit()
    db.refresh(session)
    return session
