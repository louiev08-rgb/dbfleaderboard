"""Application configuration.

Values are read from environment variables with sensible demo defaults so the
app runs out of the box on SQLite with a mock PSP. For the production skeleton
described in the TDS, override DATABASE_URL with a PostgreSQL DSN.
"""
from __future__ import annotations

import os
from functools import lru_cache


def _normalise_db_url(url: str) -> str:
    """Managed platforms (Render/Heroku/Railway) often hand out a bare
    'postgres://...' URL; normalise it to the psycopg v3 driver so SQLAlchemy
    connects without manual editing."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Settings:
    # --- general ---
    APP_NAME: str = "Petro EV Charging Platform"
    APP_VERSION: str = "0.1.0"

    # --- database ---
    # Demo default: local SQLite file. Override for Postgres:
    #   DATABASE_URL=postgresql+psycopg://user:pass@host:5432/petro
    # Managed platforms (Render/Heroku/Railway) often hand out a bare
    # "postgres://..." URL; it is normalised to the psycopg v3 driver below.
    DATABASE_URL: str = _normalise_db_url(os.getenv("DATABASE_URL", "sqlite:///./petro.db"))

    # --- auth / jwt ---
    # In production, set JWT_SECRET to a long random value held in a secret store.
    JWT_SECRET: str = os.getenv("JWT_SECRET", "dev-only-change-me-in-production")
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

    # --- currency ---
    CURRENCY: str = os.getenv("CURRENCY", "ZAR")

    # --- payments ---
    # Pre-authorisation ceiling used when the customer starts fuelling (TDS 10).
    PREAUTH_CEILING: str = os.getenv("PREAUTH_CEILING", "2000.00")
    # Shared secret the PSP uses to sign its settlement/lifecycle webhooks (TDS 4.3).
    PSP_WEBHOOK_SECRET: str = os.getenv("PSP_WEBHOOK_SECRET", "psp-demo-secret")

    # --- seeding ---
    SEED_ON_STARTUP: bool = os.getenv("SEED_ON_STARTUP", "1") == "1"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
