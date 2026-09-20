# TransactionOS v3.3.4 — Transaction Platform Prototype

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

The next production-foundation steps are PostgreSQL, stronger authentication/session controls, automated testing expansion, deployment, and a clearly isolated demo environment.
