"""FastAPI application entrypoint for the Petro EV Charging Platform.

Run locally:
    pip install -r requirements.txt
    uvicorn app.main:app --reload
Then open http://127.0.0.1:8000/docs for the interactive OpenAPI UI.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.routers import admin, auth, customers, logbook, payments, pumps, sessions, settlement, vehicles


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables (demo). The production skeleton uses Alembic migrations instead.
    Base.metadata.create_all(bind=engine)
    if settings.SEED_ON_STARTUP:
        from app.seed import seed
        db = SessionLocal()
        try:
            seed(db)
        finally:
            db.close()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    summary="Phone-based fuel payment platform replacing the forecourt card terminal.",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(customers.router)
app.include_router(vehicles.router)
app.include_router(sessions.router)
app.include_router(pumps.router)
app.include_router(payments.router)
app.include_router(settlement.router)
app.include_router(logbook.router)

# Demo-only helper used by the bundled console (server-side pump signing).
if settings.SEED_ON_STARTUP:
    from app.routers import demo
    app.include_router(demo.router)


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


# Serve the single-page console at the root, if present. API routes above take
# precedence; the SPA is the fallback for everything else.
_frontend = Path(__file__).resolve().parent.parent / "frontend"
if _frontend.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend), html=True), name="console")
else:
    @app.get("/", tags=["meta"])
    def root():
        return {"app": settings.APP_NAME, "version": settings.APP_VERSION, "docs": "/docs"}
