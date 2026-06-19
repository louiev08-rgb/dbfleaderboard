# Petro EV Charging Platform — API (Demo Build)

A FastAPI backend implementing the **phone-based fuel payment platform** from the
BRD (v3.0) and TDS (v2.0): a customer pays for fuel on their own phone using a
card on file, an attendant starts the pump, and the bank's handheld speedpoint is
removed from the forecourt.

This is the **runnable demo target**: SQLite, a swappable **mock PSP**, seeded
data, and API-only (interactive OpenAPI docs). It maps directly onto the TDS
architecture and is structured so the production skeleton (PostgreSQL + Alembic +
real PSP adapter) is a configuration/adapter swap, not a rewrite.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://127.0.0.1:8000/docs** for the interactive API, or
**http://127.0.0.1:8000/** for the bundled **Forecourt Console** (a single-page
UI served by the backend). The database is created and seeded automatically on
first run.

### The Forecourt Console (web UI)

The console at `/` is a self-contained single-page app (no build step) that
drives the whole platform through the API. What you see is filtered by the role
you sign in as:

- **Attendant** — *Run a session*: open a pump for a vehicle, watch the live
  dispenser meter fill, and complete the sale. A stolen vehicle is refused.
- **Customer** — *My wallet & pay*: add/remove a tokenised card on file and
  pre-authorise a session.
- **Manager / Retailer admin** — vehicles, forecourts, and pump registration
  (each new pump shows its webhook secret for the POS).
- **Finance** — logbook (with CSV export) and settlement/reconciliation.
- **Platform admin** — enable/suspend retailers.

Sign in with any seeded account below (or tap a demo-account chip on the login
screen). The browser never holds a pump's HMAC secret: when the console
"dispenses", it calls a demo-only `/demo/pump-dispense` helper that signs and
applies the event server-side (this helper is absent from the production image).

### Seeded accounts (password `password123`)

| Email | Role |
|-------|------|
| admin@petro.example | Platform Administrator |
| retailer@acme.example | Retailer Admin |
| manager@acme.example | Forecourt Manager |
| attendant@acme.example | Station Operator / Attendant |
| finance@acme.example | Finance / Audit |
| driver@example.com | Customer (payer), with a card on file |

Seeded data: retailer **ACME Fuel Co**, forecourt **ACME N1 Plaza**, **Pump 1**
(fuel, webhook secret `pump1secret`) and **Pump 2** (EV, `pump2secret`), and three
vehicles including one flagged **stolen** to demonstrate the gate.

## The phone-pays flow (end to end)

1. `POST /auth/token` — log in as the attendant and as the customer.
2. Customer: `GET /customers/payment-methods` (a card is pre-seeded), or
   `POST /customers/payment-methods` to add one (tokenised by the mock PSP).
3. Attendant: `POST /sessions` — open a session for a pump + vehicle/customer.
   A **stolen** vehicle is refused here (409).
4. Customer: `POST /sessions/{id}/authorise` — pre-authorise the card (a hold).
5. Pump POS: `POST /pumps/events` — **HMAC-signed**, **idempotent** dispensing
   events (`dispense_tick`, then `dispense_complete`). On completion the platform
   captures the **exact dispensed amount** and writes the transaction log
   atomically.
6. Finance: `GET /logbook` / `GET /logbook/export` (CSV).
7. Retailer Admin: `POST /payments/{id}/refund` for full/partial refunds.
8. PSP: `POST /webhooks/psp` — signed settlement/lifecycle events; a `settled`
   event advances the payment `Captured → Settled`.
9. Finance: `POST /settlements/run` then `GET /settlements` for per-forecourt,
   per-day gross/fees/net; `GET /settlements/exceptions` lists any session that
   dispensed fuel without a matching capture (FR-31).

### Signing a pump event (example)

```python
import json, hmac, hashlib, requests
body = json.dumps({"event":"dispense_complete","session_ref":"S-...","units":20,"unit_type":"L"}).encode()
sig = hmac.new(b"pump1secret", body, hashlib.sha256).hexdigest()
requests.post("http://127.0.0.1:8000/pumps/events", data=body, headers={
    "X-Pump-Id":"1","X-Signature":sig,"X-Idempotency-Key":"evt-001","Content-Type":"application/json"})
```

## Design notes (traceable to the TDS)

- **PCI scope**: raw card data never reaches the API. The PSP tokenises the card
  and only the token + display mask are stored (`app/services/psp.py`, TDS 3.3/4.2).
- **Payment state machine** (`Created → Authorised → Captured → Settled`, plus
  `Voided/Refunded/Declined`) is enforced in `app/services/payments.py`; the
  transition table lives in `app/models/enums.py` (TDS 3.1).
- **Two control gates** (`app/services/billing.py`): stolen-vehicle refusal
  before dispensing, and completion only when an authorisation covers the
  dispensed total — capturing the exact dispensed amount (TDS 3.4).
- **Webhook security**: HMAC-SHA256 signature per pump + idempotency ledger so a
  retried delivery never double-bills (`app/routers/pumps.py`, TDS 4.3).
- **RBAC**: JWT carries role + tenant/customer scope; enforced server-side
  (`app/core/deps.py`, TDS 4.1).
- **Money**: `Decimal`, `NUMERIC(12,2)` / `(12,3)`, 2dp rounding (TDS 5.2).

## Tests

```bash
# Pure-domain checks, no web stack required:
python -m tests.smoke

# Full HTTP flow (after installing requirements):
pytest -q
```

## Moving to the production skeleton (PostgreSQL + Alembic + Docker)

The repo now ships the production scaffolding alongside the demo. Two ways to run:

**A. Docker (Postgres + API):**

```bash
docker compose up --build
```

This starts PostgreSQL, runs the Alembic migrations (`alembic upgrade head`),
and serves the API on `:8000`. Seeding is off in this mode (`SEED_ON_STARTUP=0`).

**B. Local against your own Postgres:**

```bash
export DATABASE_URL=postgresql+psycopg://petro:petro@localhost:5432/petro
export SEED_ON_STARTUP=0
alembic upgrade head
uvicorn app.main:app
```

Migrations live in `migrations/`; the baseline is `0001_initial`. After changing
ORM models, generate a new revision with:

```bash
alembic revision --autogenerate -m "describe change"
```

Remaining production hardening: put `JWT_SECRET` and the PSP credentials in a
managed secret store, run the settlement job (`POST /settlements/run`) on a
schedule, and replace the `MockPSP` with your provider's adapter.

## Swapping in a real PSP

Implement the `PSPAdapter` protocol in `app/services/psp.py` (tokenise /
authorise / capture / void / refund) for your provider and bind it in
`get_psp()`. The PSP signs its callbacks to `POST /webhooks/psp` with
`PSP_WEBHOOK_SECRET` (HMAC-SHA256). No domain or router code changes.

## Project layout

```
app/
  core/        config, database, security (hash/JWT/HMAC), deps (RBAC)
  models/      SQLAlchemy ORM + enums (incl. payment transition table)
  schemas/     Pydantic request/response models
  services/    money, psp (mock), payments (state machine), billing (gates), settlement (reconciliation)
  routers/     auth, admin, customers, vehicles, sessions, pumps, payments, settlement, logbook, demo (demo-only)
  seed.py      demo data
  main.py      FastAPI app (also serves the console + mounts the SPA)
frontend/
  index.html   single-file Forecourt Console (vanilla JS, no build)
migrations/    Alembic env + initial schema migration (production skeleton)
tests/
  smoke.py     dependency-free domain checks
  test_api.py  end-to-end HTTP flow (pytest)
Dockerfile, docker-compose.yml   Postgres + API container stack
alembic.ini    Alembic configuration
```
