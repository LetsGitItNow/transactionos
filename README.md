# TransactionOS v2.4 — Functional Transaction Engine

v2.4 connects the browser prototype's core buyer/offer flow to the local persistent TransactionOS API.

## What is now real

- SQLite persistence
- Local authentication/session layer
- Canonical property resolution boundary
- Property → transaction creation
- Transaction → offer creation
- Offer version persistence
- Offer acceptance persistence
- Offer/version audit events
- Deposit obligation persistence
- Simulated deposit receipt/hold state
- Provider-neutral property service boundary
- Provider-neutral deposit/custody boundary

## Core flow

PROPERTY → TRANSACTION → OFFER → OFFER_VERSION → ACCEPTANCE → DEPOSIT → EVENTS

The browser demo now persists the critical offer lifecycle through the API instead of relying only on in-memory JavaScript state.

## Run locally

```bash
cd transactionos_v2
python -m pip install -r requirements.txt
python -m uvicorn app:app --reload --port 8765
```

Open the API docs at `/docs` and serve/open the frontend in the same development environment as configured by the project.

## Important prototype boundary

Real money is **not** moved or held. Deposit endpoints only create a transaction ledger record and simulate receipt/hold/release. A production financial/trust provider must be integrated later.

Real legal forms, identity/authority verification, signatures, notifications, and jurisdiction-specific compliance are also not represented as production-ready services.

## Next engineering step

Continue consolidating the remaining UI-only transaction states (delivery, counteroffer, withdrawal, expiry, workspace tasks) into the persistent event/state model, then build the provider integration boundary for real address/property data.


## v3.1 — Transaction Brain
- Next-best-action orchestration endpoint with priority/hold/action states.
- AI prepares safe administrative tasks without completing human-controlled actions.
- High-severity risks can place automation on HOLD.
- Workspace presents Transaction Brain as the primary action surface.
- Backend state remains the source of truth for tasks and exceptions.


## v3.1 — Transaction Brain
- Deterministic transaction-state evaluation before AI explanation.
- Explicit states: POST_ACCEPTANCE, EXCEPTION, PAUSED, READY_FOR_CLOSING.
- Priority model: ACTION, HOLD, COMPLETE.
- High-severity risks block automation.
- Deposit obligations and earliest incomplete workflow tasks drive next-best-action selection.
- Brain evaluations are persisted with immutable timestamps and reasons.
- Exception & recovery lab in the prototype lets users pause, resume, inject a test high-severity risk, and re-evaluate.
- The UI presents one next action while keeping system state, automation level, and human escalation visible.

Engineering principle: the workflow engine is the source of truth; AI explains, prepares, and coordinates around it rather than inventing transaction state.
