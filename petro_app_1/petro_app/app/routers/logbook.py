"""Logbook & reporting: list transactions and export CSV (FR-35..37)."""
from __future__ import annotations

import csv
import io

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.deps import Principal, require_roles
from app.models import Forecourt, TransactionLog
from app.models.enums import Role
from app.schemas import LogEntryOut

router = APIRouter(tags=["logbook"])

_VIEW_ROLES = (Role.STATION_OPERATOR, Role.FORECOURT_MANAGER, Role.RETAILER_ADMIN, Role.FINANCE_AUDIT)


def _scope_stmt(principal: Principal):
    stmt = select(TransactionLog).order_by(TransactionLog.ts.desc())
    # Finance/retailer roles see their retailer's forecourts only.
    if principal.retailer_id is not None:
        stmt = stmt.join(Forecourt, Forecourt.id == TransactionLog.forecourt_id).where(
            Forecourt.retailer_id == principal.retailer_id)
    return stmt


@router.get("/logbook", response_model=list[LogEntryOut])
def list_log(db: Session = Depends(get_db), principal: Principal = Depends(require_roles(*_VIEW_ROLES))):
    return list(db.scalars(_scope_stmt(principal)))


@router.get("/logbook/export")
def export_csv(db: Session = Depends(get_db),
               principal: Principal = Depends(require_roles(Role.FINANCE_AUDIT, Role.RETAILER_ADMIN))):
    rows = list(db.scalars(_scope_stmt(principal)))
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["timestamp", "plate", "mode", "units", "unit_type",
                     "price_per_unit", "total", "payment_outcome", "forecourt_id"])
    for r in rows:
        writer.writerow([r.ts.isoformat(), r.plate or "", r.mode, r.units, r.unit_type,
                         r.price_per_unit, r.total, r.payment_outcome, r.forecourt_id])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": "attachment; filename=petro_logbook.csv"})
