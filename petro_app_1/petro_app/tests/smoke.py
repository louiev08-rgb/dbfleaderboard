"""Dependency-free smoke test of the core domain logic.

This runs with only the Python standard library, so it works even where the web
stack (FastAPI/SQLAlchemy) is not installed. It re-implements nothing — it
imports the real money helpers, HMAC verification, and PSP mock, and checks the
invariants the BRD/TDS require. The full HTTP flow is exercised separately by
tests/test_api.py once dependencies are installed.

Run: python -m tests.smoke
"""
from __future__ import annotations

import sys
from decimal import Decimal


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    return cond


def main() -> int:
    ok = True

    # --- money rounding (TDS 5.2) ---
    from app.services.money import money, units
    ok &= check("money rounds to 2dp half-up", money("23.505") == Decimal("23.51"))
    ok &= check("units round to 3dp", units("12.3456") == Decimal("12.346"))
    ok &= check("price x dispensed is exact", money(Decimal("23.50") * units("10")) == Decimal("235.00"))

    # --- HMAC webhook auth (TDS 4.3) ---
    from app.core.security import sign_payload, verify_signature
    body = b'{"event":"dispense_tick","units":12.34}'
    sig = sign_payload("pump1secret", body)
    ok &= check("valid signature verifies", verify_signature("pump1secret", body, sig))
    ok &= check("prefixed signature verifies", verify_signature("pump1secret", body, "hmac-sha256=" + sig))
    ok &= check("wrong secret rejected", not verify_signature("wrong", body, sig))
    ok &= check("tampered body rejected", not verify_signature("pump1secret", body + b" ", sig))

    # --- PSP mock + tokenisation (TDS 3.3) ---
    from app.services.psp import MockPSP
    psp = MockPSP()
    token, mask = psp.tokenise_card("4242424242424242", "12/29", "123")
    ok &= check("PSP returns a token, not the PAN", token.startswith("tok_") and "4242" in mask and "4242424242424242" not in token)
    ok &= check("PSP fee is 2.5%", psp.fee_for(Decimal("100.00")) == Decimal("2.50"))

    # --- payment state machine transitions (TDS 3.1) ---
    # Load the enums module directly (by path) so we don't trigger the models
    # package __init__, which imports SQLAlchemy. The transition table lives in
    # the same module the service uses, so this is the real source of truth.
    import importlib.util, os
    enums_path = os.path.join(os.path.dirname(__file__), "..", "app", "models", "enums.py")
    spec = importlib.util.spec_from_file_location("petro_enums", enums_path)
    enums = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(enums)
    T, PaymentState = enums.PAYMENT_TRANSITIONS, enums.PaymentState
    ok &= check("Created -> Authorised allowed", PaymentState.AUTHORISED in T[PaymentState.CREATED])
    ok &= check("Authorised -> Captured allowed", PaymentState.CAPTURED in T[PaymentState.AUTHORISED])
    ok &= check("Captured -> Refunded allowed", PaymentState.REFUNDED in T[PaymentState.CAPTURED])
    ok &= check("Created -> Captured FORBIDDEN", PaymentState.CAPTURED not in T[PaymentState.CREATED])
    ok &= check("Refunded is terminal", T[PaymentState.REFUNDED] == set())
    ok &= check("Captured -> Settled allowed", PaymentState.SETTLED in T[PaymentState.CAPTURED])
    ok &= check("Settled -> Refunded allowed", PaymentState.REFUNDED in T[PaymentState.SETTLED])
    ok &= check("Authorised -> Voided allowed", PaymentState.VOIDED in T[PaymentState.AUTHORISED])

    print()
    print("RESULT:", "ALL PASSED" if ok else "FAILURES PRESENT")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
