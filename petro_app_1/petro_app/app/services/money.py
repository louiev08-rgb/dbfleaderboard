"""Money helpers. All monetary maths uses Decimal with 2dp rounding (TDS 5.2)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def units(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
