"""Security primitives: password hashing, JWT issue/verify, and webhook HMAC.

Per TDS section 4: passwords are stored only as hashes, auth is stateless JWT,
and pump/PSP webhooks are authenticated with an HMAC-SHA256 signature.

The HMAC helpers depend only on the standard library; the password and JWT
helpers lazily import passlib/jose so HMAC can be used (and tested) without the
full web stack installed.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any

from app.core.config import settings


@lru_cache
def _pwd_context():
    from passlib.context import CryptContext
    # argon2 is preferred per the TDS; bcrypt is the portable fallback.
    return CryptContext(schemes=["bcrypt"], deprecated="auto")


# --- passwords ---
def hash_password(plain: str) -> str:
    return _pwd_context().hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context().verify(plain, hashed)


# --- jwt ---
def create_access_token(subject: str, claims: dict[str, Any]) -> str:
    """Issue a signed JWT. `claims` carries role + tenant/customer scope so the
    API can authorise server-side without a database hit on every request."""
    from jose import jwt
    to_encode: dict[str, Any] = {"sub": subject, **claims}
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    from jose import JWTError, jwt
    try:
        return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:  # pragma: no cover - exercised via API tests
        raise ValueError("invalid or expired token") from exc


# --- webhook hmac (stdlib only) ---
def sign_payload(secret: str, raw_body: bytes) -> str:
    """Return the hex HMAC-SHA256 of a raw request body (as a pump/PSP would)."""
    return hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, raw_body: bytes, provided: str) -> bool:
    """Constant-time comparison of a provided signature against the expected one.
    Accepts an optional 'hmac-sha256=' prefix as used in the TDS examples."""
    if provided.startswith("hmac-sha256="):
        provided = provided.split("=", 1)[1]
    expected = sign_payload(secret, raw_body)
    return hmac.compare_digest(expected, provided)
