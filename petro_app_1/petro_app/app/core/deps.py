"""Authentication dependencies and server-side RBAC enforcement (TDS 4).

A bearer JWT carries the principal's role and tenant/customer scope. Endpoints
declare the roles they permit; scope (retailer/forecourt) is checked in handlers.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.core.security import decode_access_token
from app.models.enums import Role

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")


@dataclass
class Principal:
    subject: str
    role: Role
    retailer_id: int | None
    forecourt_id: int | None
    customer_id: int | None
    user_id: int | None


def get_principal(token: str = Depends(oauth2_scheme)) -> Principal:
    try:
        claims = decode_access_token(token)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or expired token")
    try:
        role = Role(claims["role"])
    except (KeyError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token claims")
    return Principal(
        subject=claims.get("sub", ""),
        role=role,
        retailer_id=claims.get("retailer_id"),
        forecourt_id=claims.get("forecourt_id"),
        customer_id=claims.get("customer_id"),
        user_id=claims.get("user_id"),
    )


def require_roles(*roles: Role):
    """Dependency factory: allow only the listed roles."""
    allowed = set(roles)

    def _dep(principal: Principal = Depends(get_principal)) -> Principal:
        if principal.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"role {principal.role.value} not permitted for this action",
            )
        return principal

    return _dep


def require_customer(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != Role.CUSTOMER or principal.customer_id is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="customer scope required")
    return principal
