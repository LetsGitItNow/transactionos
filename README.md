# TransactionOS v3.4.1 — Transaction Platform Prototype

TransactionOS is a global real-estate transaction platform prototype: the transaction engine is the core product, with marketplace discovery layered on top.

## Current prototype

- FastAPI backend with SQLite for local development
- Account registration, login, and bearer sessions
- Canonical property-resolution boundary for a future address/geocoding provider
- Property → transaction → offer → immutable offer-version lifecycle
- Identity gate and prototype e-signature flow
- Accepted-offer transaction workspace primitives
- Transaction tasks, conditions, documents, events, risks, pause/resume
- Deposit obligation ledger with simulated receipt/release states
- Deterministic Transaction Brain with persisted evaluations and human escalation
- Browser marketplace / buyer / seller flows
- Local-document mapping architecture and jurisdiction-rule data

## Prototype boundaries

This repository is **not production-ready** and does not provide legal, financial, identity, or e-signature services.

- SQLite is for local development only.
- Deposit endpoints simulate ledger state; they do not move or custody money.
- Signature records are explicitly prototype evidence, not a claim of legal validity in every jurisdiction.
- Legal documents and jurisdiction rules are illustrative; production requires authorized/current forms, applicable rules, and legal/compliance review.
- Property resolution is provider-neutral and currently uses the local canonical store rather than a live geocoding provider.
- Authentication is suitable for the prototype but requires production hardening before public use.

## Run locally

```bash
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8000
```

Open `http://127.0.0.1:8000`.

## Run tests

```bash
python -m pip install -r requirements-dev.txt
pytest -q
```

The test suite uses an isolated temporary SQLite database and does not modify the local development database.

## Engineering direction

The workflow engine remains the source of truth. AI may explain, prepare, validate, and coordinate administrative work, but legally significant decisions remain human-controlled.

v3.5.0 establishes the runtime configuration and deployment boundary. The next steps are stronger authentication, production database migrations, deployment, and a clearly isolated demo environment.

## PostgreSQL foundation

TransactionOS 3.5.0 can use PostgreSQL through the `DATABASE_URL` environment variable. If it is not set, local development continues to use SQLite.

For a managed PostgreSQL deployment:

1. Create the PostgreSQL database.
2. Set `DATABASE_URL` to the provider connection string.
3. Install dependencies with `pip install -r requirements.txt`.
4. Start the API; TransactionOS initializes the transaction schema on startup.

`postgres_schema.sql` is included as an explicit schema reference. `.env.example` documents the environment variable without containing credentials.

The local SQLite database is deliberately not version-controlled. Production should use a managed PostgreSQL instance with encrypted connections, backups, access controls, and provider-level monitoring.

## v3.4.1 transaction-engine hardening

- Added transaction-scoped authorization checks across transaction, offer, task, deposit, identity, signature, overview, and event operations.
- Prevented acceptance of expired or already-finalized offers.
- Preserved immutable prior offer versions while allowing only the current version to be actionable.
- Required verified buyer identity before creating a prototype signature.
- Added regression tests covering offer lifecycle, expiry, transaction isolation, signature gating, tasks, and deposit state transitions.

Run the test suite with `pytest -q`.


## v3.5.0 production-foundation boundary

- Runtime configuration is environment-driven through `APP_ENV`, `DATABASE_URL`, `SESSION_TTL_HOURS`, `LOG_LEVEL`, and `CORS_ORIGINS`.
- CORS is restricted to configured origins instead of allowing every origin by default.
- `/api/health` reports application/runtime identity; `/api/readyz` verifies database readiness.
- Session lifetime is configurable and defaults to 24 hours.
- No secrets belong in the repository; use environment variables or the deployment platform's secret store.
- This remains an alpha prototype: production deployment still requires security review, migrations, backups, monitoring, real identity/e-signature/payment integrations, and jurisdiction-specific compliance.
