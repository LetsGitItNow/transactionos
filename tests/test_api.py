import importlib
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient


# Import once, then point the app at an isolated test database before reinitializing it.
app_module = importlib.import_module("app")


def client_with_fresh_db(tmp_path: Path):
    db = tmp_path / "test.db"
    app_module.DB = str(db)
    app_module.init()
    return TestClient(app_module.app)


def auth_header(client: TestClient):
    r = client.post("/api/auth/register", json={"email": "test@example.com", "password": "password123"})
    assert r.status_code == 200
    r = client.post("/api/auth/login", json={"email": "test@example.com", "password": "password123"})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_health(tmp_path):
    c = client_with_fresh_db(tmp_path)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["version"] == "3.4.0"


def test_auth_property_transaction_offer_submission_and_brain(tmp_path):
    c = client_with_fresh_db(tmp_path)
    headers = auth_header(c)

    p = c.post("/api/properties/resolve", headers=headers, json={
        "address": "123 Main Street",
        "city": "Toronto",
        "region": "Ontario",
        "country": "Canada",
        "property_type": "Condo",
    })
    assert p.status_code == 200
    property_id = p.json()["property_id"]
    assert p.json()["jurisdiction"] == "CA-ON-TORONTO"

    tx = c.post("/api/transactions", headers=headers, json={"property_id": property_id})
    assert tx.status_code == 200
    tid = tx.json()["transaction_id"]

    offer = c.post(f"/api/transactions/{tid}/offers", headers=headers, json={"transaction_id": tid})
    assert offer.status_code == 200
    oid = offer.json()["offer_id"]

    # Submission is intentionally gated by identity + signature.
    blocked = c.post(f"/api/offers/{oid}/versions", headers=headers, json={"payload": {"price": "$900,000"}})
    assert blocked.status_code == 409
    assert "identity verification" in blocked.json()["detail"].lower()

    identity = c.post("/api/identity/verify", headers=headers, json={
        "transaction_id": tid,
        "legal_name": "Test Buyer",
        "email": "test@example.com",
        "method": "demo",
    })
    assert identity.status_code == 200

    sig = c.post("/api/signatures", headers=headers, json={
        "transaction_id": tid,
        "legal_name": "Test Buyer",
        "signature_data": "typed:Test Buyer",
        "method": "typed-demo",
    })
    assert sig.status_code == 200

    version = c.post(f"/api/offers/{oid}/versions", headers=headers, json={
        "payload": {"price": "$900,000", "deposit": "$50,000", "closing": "October 30, 2026"}
    })
    assert version.status_code == 200
    assert version.json()["version_number"] == 1

    accepted = c.post(f"/api/offers/{oid}/accept", headers=headers)
    assert accepted.status_code == 200

    brain = c.post(f"/api/transactions/{tid}/brain/evaluate", headers=headers)
    assert brain.status_code == 200
    assert brain.json()["priority"] in {"ACTION", "HOLD", "COMPLETE"}

    events = c.get(f"/api/transactions/{tid}/events", headers=headers)
    assert events.status_code == 200
    event_types = {e["type"] for e in events.json()}
    assert {"TRANSACTION_CREATED", "OFFER_CREATED", "BUYER_IDENTITY_VERIFIED", "SIGNATURE_COMPLETED", "OFFER_VERSION_SUBMITTED", "OFFER_ACCEPTED"}.issubset(event_types)
