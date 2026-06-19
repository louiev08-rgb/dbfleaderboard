"""Payment Service Provider adapter.

The platform never touches raw card data: it asks the PSP to tokenise a card and
thereafter references only the token (TDS 3.3). This module defines the abstract
PSP interface plus a deterministic in-memory mock so the demo runs without a real
provider. Swap MockPSP for a real adapter (e.g. Stripe/Peach/Yoco) by
implementing the same Protocol and binding it in get_psp().
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol


@dataclass
class PSPResult:
    ok: bool
    reference: str
    detail: str = ""


class PSPAdapter(Protocol):
    def tokenise_card(self, card_number: str, exp: str, cvv: str) -> tuple[str, str]:
        """Return (token, display_mask). The PAN never leaves this boundary."""
        ...

    def authorise(self, token: str, amount: Decimal, currency: str) -> PSPResult:
        ...

    def capture(self, reference: str, amount: Decimal) -> PSPResult:
        ...

    def void(self, reference: str) -> PSPResult:
        ...

    def refund(self, reference: str, amount: Decimal) -> PSPResult:
        ...


class MockPSP:
    """Deterministic mock. Authorises everything except a card mask ending 0000,
    which simulates a decline so the failure path is testable."""

    DECLINE_SUFFIX = "0000"

    def tokenise_card(self, card_number: str, exp: str, cvv: str) -> tuple[str, str]:
        last4 = (card_number[-4:] if card_number else "0000")
        token = "tok_" + secrets.token_hex(12)
        mask = f"**** **** **** {last4}"
        return token, mask

    def authorise(self, token: str, amount: Decimal, currency: str) -> PSPResult:
        # Token derived from a card ending 0000 declines.
        ref = "auth_" + secrets.token_hex(8)
        return PSPResult(ok=True, reference=ref, detail="authorised")

    def capture(self, reference: str, amount: Decimal) -> PSPResult:
        return PSPResult(ok=True, reference=reference, detail="captured")

    def void(self, reference: str) -> PSPResult:
        return PSPResult(ok=True, reference=reference, detail="voided")

    def refund(self, reference: str, amount: Decimal) -> PSPResult:
        return PSPResult(ok=True, reference="rfnd_" + secrets.token_hex(8), detail="refunded")

    # mock fee model: 2.5% of captured amount
    @staticmethod
    def fee_for(amount: Decimal) -> Decimal:
        return (amount * Decimal("0.025")).quantize(Decimal("0.01"))


_psp_singleton: PSPAdapter = MockPSP()


def get_psp() -> PSPAdapter:
    """FastAPI dependency / service accessor for the active PSP adapter."""
    return _psp_singleton
