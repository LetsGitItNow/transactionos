import importlib
from pathlib import Path
from datetime import datetime, timezone, timedelta

from fastapi.testclient import TestClient

app_module = importlib.import_module("app")


def client_with_fresh_db(tmp_path: Path):
    db = tmp_path / "test.db"
    app_module.DB = str(db)
    app_module.init()
    return TestClient(app_module.app)


def register_and_login(client, email):
    password = "password123"
    r = client.post("/api/auth/register", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def make_transaction(client, headers):
    p = client.post("/api/properties/resolve", headers=headers, json={
        "address": "123 Main Street", "city": "Toronto", "region": "Ontario",
        "country": "Canada", "property_type": "Condo",
    })
    assert p.status_code == 200, p.text
    pid = p.json()["property_id"]
    tx = client.post("/api/transactions", headers=headers, json={"property_id": pid})
    assert tx.status_code == 200, tx.text
    return tx.json()["transaction_id"]


def prepare_offer(client, headers, deadline=None, deposit="$50,000"):
    tid = make_transaction(client, headers)
    offer = client.post(f"/api/transactions/{tid}/offers", headers=headers,
                        json={"transaction_id": tid})
    assert offer.status_code == 200, offer.text
    oid = offer.json()["offer_id"]
    assert client.post("/api/identity/verify", headers=headers, json={
        "transaction_id": tid, "legal_name": "Test Buyer", "email": "buyer@example.com", "method": "demo"
    }).status_code == 200
    assert client.post("/api/signatures", headers=headers, json={
        "transaction_id": tid, "legal_name": "Test Buyer", "signature_data": "typed:Test Buyer", "method": "typed-demo"
    }).status_code == 200
    payload = {"price": "$900,000", "deposit": deposit, "closing": "October 30, 2026", "conditions": ["Financing"]}
    body = {"payload": payload}
    if deadline is not None:
        body["deadline_at"] = deadline
    version = client.post(f"/api/offers/{oid}/versions", headers=headers, json=body)
    assert version.status_code == 200, version.text
    return tid, oid, version.json()["version_id"]


def test_health_and_baseline_flow(tmp_path):
    c = client_with_fresh_db(tmp_path)
    headers = register_and_login(c, "test@example.com")
    health = c.get("/api/health").json()
    assert health["ok"] is True
    assert health["version"] == "3.5.0"
    ready = c.get("/api/readyz")
    assert ready.status_code == 200
    assert ready.json()["ready"] is True
    tid, oid, version_id = prepare_offer(c, headers)

    accepted = c.post(f"/api/offers/{oid}/accept", headers=headers)
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["offer_version_id"] == version_id

    tasks = c.get(f"/api/transactions/{tid}/tasks", headers=headers)
    assert tasks.status_code == 200
    assert any(t["label"] == "Deposit" for t in tasks.json())


def test_old_offer_versions_are_preserved_and_only_current_can_be_accepted(tmp_path):
    c = client_with_fresh_db(tmp_path)
    headers = register_and_login(c, "versions@example.com")
    tid, oid, first_id = prepare_offer(c, headers)

    second = c.post(f"/api/offers/{oid}/versions", headers=headers, json={
        "payload": {"price": "$910,000", "deposit": "$50,000", "closing": "October 30, 2026"}
    })
    assert second.status_code == 200, second.text
    second_id = second.json()["version_id"]

    versions = c.get(f"/api/offers/{oid}/versions", headers=headers).json()
    assert [v["version_number"] for v in versions] == [1, 2]
    assert next(v for v in versions if v["version_id"] == first_id)["status"] == "PRESERVED"
    assert next(v for v in versions if v["version_id"] == second_id)["status"] == "CURRENT"

    accepted = c.post(f"/api/offers/{oid}/accept", headers=headers)
    assert accepted.status_code == 200
    assert accepted.json()["offer_version_id"] == second_id

    again = c.post(f"/api/offers/{oid}/accept", headers=headers)
    assert again.status_code == 409


def test_expired_current_offer_cannot_be_accepted(tmp_path):
    c = client_with_fresh_db(tmp_path)
    headers = register_and_login(c, "expired@example.com")
    deadline = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    tid, oid, version_id = prepare_offer(c, headers, deadline=deadline)

    accepted = c.post(f"/api/offers/{oid}/accept", headers=headers)
    assert accepted.status_code == 409
    assert "deadline" in accepted.json()["detail"].lower()

    offer = c.get(f"/api/offers/{oid}", headers=headers).json()
    assert offer["status"] == "EXPIRED"
    assert offer["versions"][0]["status"] == "EXPIRED"


def test_transaction_isolation_blocks_other_user(tmp_path):
    c = client_with_fresh_db(tmp_path)
    owner = register_and_login(c, "owner@example.com")
    stranger = register_and_login(c, "stranger@example.com")
    tid = make_transaction(c, owner)

    assert c.get(f"/api/transactions/{tid}", headers=stranger).status_code == 403
    assert c.get(f"/api/transactions/{tid}/events", headers=stranger).status_code == 403
    assert c.post(f"/api/transactions/{tid}/offers", headers=stranger,
                  json={"transaction_id": tid}).status_code == 403


def test_signature_requires_identity_verification(tmp_path):
    c = client_with_fresh_db(tmp_path)
    headers = register_and_login(c, "signature@example.com")
    tid = make_transaction(c, headers)

    sig = c.post("/api/signatures", headers=headers, json={
        "transaction_id": tid, "legal_name": "Test Buyer",
        "signature_data": "typed:Test Buyer", "method": "typed-demo"
    })
    assert sig.status_code == 409
    assert "identity verification" in sig.json()["detail"].lower()


def test_task_and_deposit_are_transaction_scoped(tmp_path):
    c = client_with_fresh_db(tmp_path)
    owner = register_and_login(c, "deposit-owner@example.com")
    stranger = register_and_login(c, "deposit-stranger@example.com")
    tid, oid, _ = prepare_offer(c, owner)
    assert c.post(f"/api/offers/{oid}/accept", headers=owner).status_code == 200

    dep = c.get(f"/api/transactions/{tid}/deposit", headers=owner)
    assert dep.status_code == 200
    did = dep.json()["deposit_id"]
    task = c.get(f"/api/transactions/{tid}/tasks", headers=owner).json()[0]["task_id"]

    assert c.get(f"/api/transactions/{tid}/deposit", headers=stranger).status_code == 403
    assert c.post(f"/api/deposits/{did}/simulate-receipt", headers=stranger).status_code == 403
    assert c.post(f"/api/tasks/{task}/complete", headers=stranger).status_code == 403

    held = c.post(f"/api/deposits/{did}/simulate-receipt", headers=owner)
    assert held.status_code == 200
    assert held.json()["status"] == "HELD"
    released = c.post(f"/api/deposits/{did}/simulate-release", headers=owner)
    assert released.status_code == 200
    assert released.json()["status"] == "RELEASED"
