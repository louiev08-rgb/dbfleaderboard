"""Customer self-service: register, manage card-on-file (FR-18..20).

Cards are tokenised by the PSP immediately; the platform stores only the token
and a display mask — never the PAN (TDS 3.3 / NFR-5).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require_customer
from app.core.security import hash_password
from app.models import Customer, PaymentMethod
from app.models.enums import PaymentMethodType
from app.schemas import CardOnFileCreate, CustomerOut, CustomerRegister, PaymentMethodOut
from app.services.psp import get_psp

router = APIRouter(tags=["customer"])


@router.post("/customers/register", response_model=CustomerOut, status_code=201)
def register(body: CustomerRegister, db: Session = Depends(get_db)):
    if db.scalar(select(Customer).where(Customer.email == body.email)):
        raise HTTPException(status_code=409, detail="email already registered")
    customer = Customer(email=body.email, name=body.name, phone=body.phone,
                        password_hash=hash_password(body.password))
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer


@router.post("/customers/payment-methods", response_model=PaymentMethodOut, status_code=201)
def add_card(body: CardOnFileCreate, db: Session = Depends(get_db),
             principal: Principal = Depends(require_customer)):
    if not body.consent:
        raise HTTPException(status_code=400, detail="explicit consent required to store a card")
    psp = get_psp()
    token, mask = psp.tokenise_card(body.card_number, body.exp, body.cvv)
    # If making default, clear existing defaults first.
    if body.make_default:
        for m in db.scalars(select(PaymentMethod).where(PaymentMethod.customer_id == principal.customer_id)):
            m.is_default = False
    method = PaymentMethod(customer_id=principal.customer_id, type=PaymentMethodType.CARD,
                           psp_token=token, card_mask=mask, is_default=body.make_default)
    db.add(method)
    db.commit()
    db.refresh(method)
    return method


@router.get("/customers/payment-methods", response_model=list[PaymentMethodOut])
def list_cards(db: Session = Depends(get_db), principal: Principal = Depends(require_customer)):
    return list(db.scalars(select(PaymentMethod).where(PaymentMethod.customer_id == principal.customer_id)))


@router.delete("/customers/payment-methods/{method_id}", status_code=204)
def remove_card(method_id: int, db: Session = Depends(get_db), principal: Principal = Depends(require_customer)):
    method = db.get(PaymentMethod, method_id)
    if not method or method.customer_id != principal.customer_id:
        raise HTTPException(status_code=404, detail="payment method not found")
    db.delete(method)
    db.commit()
