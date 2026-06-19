"""Payment read + refund endpoints (FR-25, TDS 6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require_roles
from app.models import AuditLog, Payment
from app.models.enums import Role
from app.schemas import PaymentOut, RefundRequest
from app.services import payments as pay
from app.services.psp import get_psp

router = APIRouter(tags=["payments"])


@router.get("/payments/{payment_id}", response_model=PaymentOut)
def get_payment(payment_id: int, db: Session = Depends(get_db),
                principal: Principal = Depends(require_roles(
                    Role.RETAILER_ADMIN, Role.FINANCE_AUDIT, Role.FORECOURT_MANAGER))):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    return payment


@router.post("/payments/{payment_id}/refund", response_model=PaymentOut)
def refund(payment_id: int, body: RefundRequest, db: Session = Depends(get_db),
           principal: Principal = Depends(require_roles(Role.RETAILER_ADMIN))):
    payment = db.get(Payment, payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="payment not found")
    try:
        pay.refund(db, payment, body.amount, get_psp())
    except pay.PaymentError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    db.add(AuditLog(user_id=principal.user_id, retailer_id=principal.retailer_id,
                    action="refund", entity="payment", entity_id=str(payment.id),
                    detail=str(body.amount)))
    db.commit()
    db.refresh(payment)
    return payment
