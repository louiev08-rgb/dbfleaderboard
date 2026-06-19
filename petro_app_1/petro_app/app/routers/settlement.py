"""PSP webhook + settlement/reconciliation endpoints (TDS 3.3, FR-28..31).

The PSP notifies the platform of payment lifecycle events (captured, settled,
refunded, failed) at a signed, idempotent endpoint. Settled events advance the
Payment to SETTLED. Finance/Retailer Admin can trigger and read reconciliation.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import Principal, require_roles
from app.core.security import verify_signature
from app.models import Payment, Settlement, WebhookEvent
from app.models.enums import Role
from app.services import payments as pay
from app.services import settlement as settle_svc

router = APIRouter(tags=["settlement"])


@router.post("/webhooks/psp")
async def psp_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_signature: str = Header(..., alias="X-Signature"),
    x_idempotency_key: str = Header(..., alias="X-Idempotency-Key"),
):
    raw = await request.body()

    # Authenticate the PSP callback (TDS 4.3).
    if not verify_signature(settings.PSP_WEBHOOK_SECRET, raw, x_signature):
        raise HTTPException(status_code=401, detail="invalid signature")

    # Idempotency: a retried PSP delivery is a no-op.
    if db.scalar(select(WebhookEvent).where(WebhookEvent.idempotency_key == x_idempotency_key)):
        return {"status": "duplicate-ignored"}
    db.add(WebhookEvent(idempotency_key=x_idempotency_key, source="psp"))

    try:
        body = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    event = body.get("event")
    psp_reference = body.get("psp_reference")
    payment = db.scalar(select(Payment).where(Payment.psp_reference == psp_reference)) if psp_reference else None
    if payment is None:
        # Unknown reference: acknowledge so the PSP stops retrying, but record nothing.
        db.commit()
        return {"status": "unknown-reference"}

    if event == "settled":
        try:
            pay.mark_settled(db, payment)
        except pay.PaymentError as exc:
            db.rollback()
            raise HTTPException(status_code=409, detail=str(exc))
    # 'captured'/'refunded'/'failed' are already reflected by our own flow in the
    # demo; in production they would reconcile asynchronous PSP state here.

    db.commit()
    return {"status": "ok", "payment_id": payment.id, "state": payment.state}


@router.post("/settlements/run", response_model=list[dict])
def run_settlement(period: str | None = None, db: Session = Depends(get_db),
                   principal: Principal = Depends(require_roles(Role.FINANCE_AUDIT, Role.RETAILER_ADMIN))):
    rows = settle_svc.run_reconciliation(db, retailer_id=principal.retailer_id, period=period)
    db.commit()
    return [
        {"forecourt_id": s.forecourt_id, "period": s.period, "gross": str(s.gross),
         "fees": str(s.fees), "net": str(s.net), "status": s.status}
        for s in rows
    ]


@router.get("/settlements", response_model=list[dict])
def list_settlements(db: Session = Depends(get_db),
                     principal: Principal = Depends(require_roles(Role.FINANCE_AUDIT, Role.RETAILER_ADMIN))):
    stmt = select(Settlement)
    if principal.retailer_id is not None:
        stmt = stmt.where(Settlement.retailer_id == principal.retailer_id)
    return [
        {"forecourt_id": s.forecourt_id, "period": s.period, "gross": str(s.gross),
         "fees": str(s.fees), "net": str(s.net), "status": s.status}
        for s in db.scalars(stmt)
    ]


@router.get("/settlements/exceptions", response_model=list[dict])
def settlement_exceptions(db: Session = Depends(get_db),
                          principal: Principal = Depends(require_roles(Role.FINANCE_AUDIT, Role.RETAILER_ADMIN))):
    """Sessions dispensed without a matching successful payment (FR-31)."""
    rows = settle_svc.find_unmatched_sessions(db, retailer_id=principal.retailer_id)
    return [{"session_id": s.id, "session_ref": s.session_ref, "dispensed": str(s.dispensed)} for s in rows]
