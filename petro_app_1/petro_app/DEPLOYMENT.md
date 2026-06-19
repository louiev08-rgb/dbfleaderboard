# Deploying the Petro EV Platform

This guide covers a **demo / staging** deployment: the app runs with the **mock
PSP** and moves no real money. It is safe to put on the public internet for
demos, but the seeded accounts are well-known and the `/demo/pump-dispense`
helper is enabled, so do not treat it as private or production.

> **Before you take real payments**, see "Going to production" at the bottom.
> That is a separate, larger effort (a real PSP, PCI scope, secrets hardening)
> — not part of this staging deploy.

---

## Recommended: Render (managed, HTTPS, free Postgres)

A managed platform handles the OS, TLS certificate, and database for you. The
repo already contains everything needed: a `Dockerfile`, Alembic migrations
that run on startup, and a `render.yaml` blueprint.

### 1. Push to GitHub

```bash
cd petro_app
git init
git add .
git commit -m "Petro EV platform"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/petro-app.git
git push -u origin main
```

### 2. Create the services from the blueprint

1. Sign in at https://render.com and connect your GitHub account.
2. **New → Blueprint**, choose the `petro-app` repo.
3. Render reads `render.yaml` and proposes a **web service** (`petro-api`) plus a
   **PostgreSQL database** (`petro-db`). Approve it.
4. It builds the Docker image, provisions Postgres, injects `DATABASE_URL`,
   generates `JWT_SECRET` and `PSP_WEBHOOK_SECRET`, runs `alembic upgrade head`,
   then starts the API.

### 3. Open it

When the deploy goes green you get a URL like
`https://petro-api.onrender.com`.

- Console UI: `https://petro-api.onrender.com/`
- API docs: `https://petro-api.onrender.com/docs`
- Health check: `https://petro-api.onrender.com/health`

Sign in with a seeded account (password `password123`), e.g.
`attendant@acme.example` or `driver@example.com`.

> **Free-tier note:** the free web instance sleeps after ~15 minutes idle and
> takes a few seconds to wake on the next request. Fine for demos; choose the
> `starter` plan in `render.yaml` if you want it always-on.

---

## Alternatives

**Railway** (https://railway.app): New Project → Deploy from GitHub repo → add a
PostgreSQL plugin → set the `DATABASE_URL` variable Railway provides. The app
normalises a bare `postgres://` URL automatically.

**Fly.io** (https://fly.io): `fly launch` (it detects the Dockerfile) →
`fly postgres create` → `fly postgres attach`. The release command should run
`alembic upgrade head`.

**Any Docker host** (a VM you control): clone the repo and run
`docker compose up --build`. You then own TLS (put nginx or Caddy in front) and
database backups yourself — which is exactly the work a managed platform saves
you, hence the recommendation above.

---

## How startup works (so failures are debuggable)

- The container command is `alembic upgrade head && uvicorn app.main:app`.
  If the DB is unreachable, migrations fail fast with a clear error in the logs.
- `DATABASE_URL` is read at boot; a bare `postgres://` is rewritten to
  `postgresql+psycopg://` automatically (see `app/core/config.py`).
- `SEED_ON_STARTUP=1` seeds demo data **and** enables `/demo/pump-dispense`.
  The seed is idempotent — it only inserts if the admin user is absent.

## Environment variables

| Variable | Purpose | Staging value |
|----------|---------|---------------|
| `DATABASE_URL` | Postgres connection | provided by the platform |
| `JWT_SECRET` | signs login tokens | generated |
| `PSP_WEBHOOK_SECRET` | verifies PSP webhooks | generated |
| `CURRENCY` | display currency | `ZAR` |
| `SEED_ON_STARTUP` | seed + demo helper | `1` (set `0` for production) |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | token lifetime | `60` |
| `PREAUTH_CEILING` | pre-auth hold amount | `2000.00` |

---

## Going to production (real payments) — what changes

This is deliberately **not** a step in the staging deploy, because it is a
larger piece of work:

1. **Choose a PSP** and implement the `PSPAdapter` protocol in
   `app/services/psp.py` for it; bind it in `get_psp()`. (Strong recommendation
   from the analyst review: a PSP/gateway with tokenisation, not a direct
   acquirer integration — it keeps you in the lightest PCI-DSS scope.)
2. **Set `SEED_ON_STARTUP=0`** so no demo data or `/demo/pump-dispense` helper
   ships. Create real users through the admin API instead.
3. **Move secrets to a managed secret store**; never commit them.
4. **Configure the PSP settlement webhook** to point at `POST /webhooks/psp`
   and schedule `POST /settlements/run` (e.g. a daily cron / scheduled job).
5. **Pen-test and review** auth, rate limits, and tenant isolation before going
   live, and complete the relevant PCI-DSS self-assessment.
