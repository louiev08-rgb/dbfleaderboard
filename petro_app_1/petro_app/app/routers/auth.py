"""Authentication endpoints. Staff and customers are separate principals that
both obtain a JWT here (TDS 6 / FR-44)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, verify_password
from app.models import Customer, User
from app.models.enums import Role
from app.schemas import Token

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=Token)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)) -> Token:
    """Authenticate by email (username field) + password.

    Tries staff users first, then customers. Returns a JWT carrying role and
    tenant/customer scope claims used for server-side authorisation.
    """
    user = db.scalar(select(User).where(User.email == form.username))
    if user and user.is_active and verify_password(form.password, user.password_hash):
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        token = create_access_token(
            subject=user.email,
            claims={
                "role": user.role.value if hasattr(user.role, "value") else user.role,
                "user_id": user.id,
                "retailer_id": user.retailer_id,
                "forecourt_id": user.forecourt_id,
                "customer_id": None,
            },
        )
        return Token(access_token=token, role=Role(user.role))

    customer = db.scalar(select(Customer).where(Customer.email == form.username))
    if customer and verify_password(form.password, customer.password_hash):
        token = create_access_token(
            subject=customer.email,
            claims={
                "role": Role.CUSTOMER.value,
                "customer_id": customer.id,
                "retailer_id": None,
                "forecourt_id": None,
                "user_id": None,
            },
        )
        return Token(access_token=token, role=Role.CUSTOMER)

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="incorrect email or password")
