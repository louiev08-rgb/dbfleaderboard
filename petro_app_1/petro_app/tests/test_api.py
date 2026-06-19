"""End-to-end API test of the phone-pays flow.

Requires the web stack installed (pip install -r requirements.txt) plus pytest.
Run: pytest -q

Exercises the full BRD/TDS happy path and the two control gates:
  - customer adds a card, attendant opens a session, customer pre-authorises,
    pump dispenses via signed webhook, capture + log on completion;
  - the stolen-vehicle gate refuses a session;
  - an unsigned pump event is rejected;
  - a duplicate webhook delivery does not double-bill.
"""
from __future__ import annotations

import json
import os

import pytest

# Use a throwaway SQLite file and fresh seed for the test run.
os.environ.setdefault("DATABASE_URL", "sqlite:///./petro_test.db")
os.environ.setdefault("SEED_ON_STARTUP", "1")

from fastapi.testclient import TestClient  # noqa: E402

from app.core.security import sign_payload  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    # Remove any prior test DB so seeding is deterministic.
    if os.path.exists("petro_test.db"):
        os.remove("petro_test.db")
    with TestClient(app) as c:
        yield c
    if os.path.exists("petro_test.db"):
        os.remove("petro_test.db")


def token(client, username, password="password123"):
    r = client.post("/auth/token", data={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def test_phone_pays_happy_path(client):
    attendant = token(client, "attendant@acme.example")
    customer = token(client, "driver@example.com")

    # customer has a seeded card on file
    methods = client.get("/customers/payment-methods", headers=auth(customer)).json()
    assert methods and methods[0]["type"] == "card"
    method_id = methods[0]["id"]

    # attendant opens a session on pump 1 for the customer's vehicle (id 1 seeded OK)
    r = client.post("/sessions", headers=auth(attendant), json={
        "pump_id": 1, "vehicle_id": 1, "customer_id": 1,
        "mode": "fuel", "target": "20", "price_per_unit": "23.50",
    })
    assert r.status_code == 201, r.text
    session = r.json()
    ref = session["session_ref"]

    # customer pre-authorises payment
    r = client.post(f"/sessions/{session['id']}/authorise", headers=auth(customer),
                    json={"method_id": method_id})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "authorised"

    # pump dispenses 20L then completes, via signed webhook
    def pump_post(body, key):
        raw = json.dumps(body).encode()
        sig = sign_payload("pump1secret", raw)
        return client.post("/pumps/events", content=raw, headers={
            "X-Pump-Id": "1", "X-Signature": sig, "X-Idempotency-Key": key,
            "Content-Type": "application/json",
        })

    r = pump_post({"event": "dispense_tick", "session_ref": ref, "units": 20, "unit_type": "L"}, "tick-1")
    assert r.status_code == 200, r.text
    r = pump_post({"event": "dispense_complete", "session_ref": ref, "units": 0, "unit_type": "L"}, "done-1")
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "completed"

    # logbook shows the transaction with the correct total (20 * 23.50 = 470.00)
    finance = token(client, "finance@acme.example")
    logs = client.get("/logbook", headers=auth(finance)).json()
    assert any(abs(float(e["total"]) - 470.00) < 0.001 for e in logs)


def test_settlement_reconciliation(client):
    """After captures exist, Finance can run reconciliation and read per-forecourt
    settlement rows with gross/fees/net (FR-28/29)."""
    finance = token(client, "finance@acme.example")
    r = client.post("/settlements/run", headers=auth(finance))
    assert r.status_code == 200, r.text
    rows = r.json()
    assert rows, "expected at least one settlement row"
    # gross should be positive and net = gross - fees for each row
    for row in rows:
        gross, fees, net = float(row["gross"]), float(row["fees"]), float(row["net"])
        assert gross > 0
        assert abs(net - (gross - fees)) < 0.01

    # the listing endpoint returns the same rows
    r = client.get("/settlements", headers=auth(finance))
    assert r.status_code == 200 and r.json()


def test_psp_settled_webhook(client):
    """A signed PSP 'settled' webhook advances a captured payment to settled."""
    import json as _json
    from app.core.config import settings as _settings

    # capture a fresh payment first
    attendant = token(client, "attendant@acme.example")
    customer = token(client, "driver@example.com")
    method_id = client.get("/customers/payment-methods", headers=auth(customer)).json()[0]["id"]
    s = client.post("/sessions", headers=auth(attendant), json={
        "pump_id": 1, "vehicle_id": 1, "customer_id": 1,
        "mode": "fuel", "target": "5", "price_per_unit": "21.00",
    }).json()
    pay_out = client.post(f"/sessions/{s['id']}/authorise", headers=auth(customer),
                          json={"method_id": method_id}).json()
    raw = _json.dumps({"event": "dispense_complete", "session_ref": s["session_ref"],
                       "units": 5, "unit_type": "L"}).encode()
    sig = sign_payload("pump1secret", raw)
    client.post("/pumps/events", content=raw, headers={
        "X-Pump-Id": "1", "X-Signature": sig, "X-Idempotency-Key": "settle-flow-1",
        "Content-Type": "application/json"})

    # PSP notifies settlement
    body = _json.dumps({"event": "settled", "psp_reference": pay_out["psp_reference"]}).encode()
    psp_sig = sign_payload(_settings.PSP_WEBHOOK_SECRET, body)
    r = client.post("/webhooks/psp", content=body, headers={
        "X-Signature": psp_sig, "X-Idempotency-Key": "psp-settle-1", "Content-Type": "application/json"})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "settled"


def test_stolen_vehicle_refused(client):
    attendant = token(client, "attendant@acme.example")
    # vehicle id 3 is seeded STOLEN
    r = client.post("/sessions", headers=auth(attendant), json={
        "pump_id": 1, "vehicle_id": 3, "mode": "fuel", "target": "10", "price_per_unit": "23.50",
    })
    assert r.status_code == 409
    assert "stolen" in r.json()["detail"].lower()


def test_demo_dispense_helper(client):
    """The console's server-side pump helper drives a full capture without the
    browser holding the pump secret."""
    attendant = token(client, "attendant@acme.example")
    customer = token(client, "driver@example.com")
    method_id = client.get("/customers/payment-methods", headers=auth(customer)).json()[0]["id"]
    s = client.post("/sessions", headers=auth(attendant), json={
        "pump_id": 1, "vehicle_id": 1, "customer_id": 1,
        "mode": "fuel", "target": "8", "price_per_unit": "22.00",
    }).json()
    client.post(f"/sessions/{s['id']}/authorise", headers=auth(customer), json={"method_id": method_id})

    r = client.post("/demo/pump-dispense", headers=auth(attendant),
                    json={"session_ref": s["session_ref"], "units": "8", "complete": True})
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "completed"


def test_unsigned_pump_event_rejected(client):
    body = json.dumps({"event": "dispense_tick", "session_ref": "S-nope", "units": 1}).encode()
    r = client.post("/pumps/events", content=body, headers={
        "X-Pump-Id": "1", "X-Signature": "hmac-sha256=deadbeef", "X-Idempotency-Key": "bad-1",
        "Content-Type": "application/json",
    })
    assert r.status_code == 401


def test_duplicate_webhook_not_double_billed(client):
    attendant = token(client, "attendant@acme.example")
    customer = token(client, "driver@example.com")
    method_id = client.get("/customers/payment-methods", headers=auth(customer)).json()[0]["id"]

    r = client.post("/sessions", headers=auth(attendant), json={
        "pump_id": 1, "vehicle_id": 1, "customer_id": 1,
        "mode": "fuel", "target": "10", "price_per_unit": "20.00",
    })
    session = r.json()
    ref = session["session_ref"]
    client.post(f"/sessions/{session['id']}/authorise", headers=auth(customer), json={"method_id": method_id})

    raw = json.dumps({"event": "dispense_complete", "session_ref": ref, "units": 10, "unit_type": "L"}).encode()
    sig = sign_payload("pump1secret", raw)
    headers = {"X-Pump-Id": "1", "X-Signature": sig, "X-Idempotency-Key": "dup-key", "Content-Type": "application/json"}

    r1 = client.post("/pumps/events", content=raw, headers=headers)
    r2 = client.post("/pumps/events", content=raw, headers=headers)  # same idempotency key
    assert r1.status_code == 200 and r2.status_code == 200
    # the payment captured exactly once: 10 * 20.00 = 200.00
    pid = session["id"]
    finance = token(client, "finance@acme.example")
    logs = client.get("/logbook", headers=auth(finance)).json()
    matching = [e for e in logs if e["session_id"] == pid]
    assert len(matching) == 1
    assert abs(float(matching[0]["total"]) - 200.00) < 0.001
