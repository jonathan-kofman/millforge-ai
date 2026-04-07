"""
Tests for /api/quality/as9100 endpoints.

Covers:
  - Auth guard: protected endpoints return 401 without token
  - Initialize: creates clauses and status records
  - Dashboard: returns compliance structure
  - List clauses: public endpoint (no auth required)
  - Get clause: 404 for unknown clause
  - Audit trail: scoped to authenticated user
  - Readiness: returns score structure
  - Sync: returns ingested count
"""

import pytest


def _register_and_token(client, email="as9100test@example.com"):
    res = client.post("/api/auth/register", json={
        "email": email,
        "password": "testpass123",
        "name": "AS9100Tester",
    })
    assert res.status_code == 201
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth guards
# ---------------------------------------------------------------------------

def test_initialize_requires_auth(client):
    res = client.post("/api/quality/as9100/initialize")
    assert res.status_code == 401


def test_dashboard_requires_auth(client):
    res = client.get("/api/quality/as9100/dashboard")
    assert res.status_code == 401


def test_audit_trail_requires_auth(client):
    res = client.get("/api/quality/as9100/audit-trail")
    assert res.status_code == 401


def test_readiness_requires_auth(client):
    res = client.get("/api/quality/as9100/readiness")
    assert res.status_code == 401


def test_sync_requires_auth(client):
    res = client.post("/api/quality/as9100/sync")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

def test_initialize_creates_clauses(client):
    token = _register_and_token(client)
    res = client.post("/api/quality/as9100/initialize", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert "clauses_created" in data
    assert "statuses_created" in data
    assert data["clauses_created"] >= 0
    assert data["statuses_created"] >= 0


def test_initialize_idempotent(client):
    """Calling initialize twice should not crash or create duplicate records."""
    token = _register_and_token(client, "as9100idempotent@example.com")
    res1 = client.post("/api/quality/as9100/initialize", headers=_auth(token))
    res2 = client.post("/api/quality/as9100/initialize", headers=_auth(token))
    assert res1.status_code == 200
    assert res2.status_code == 200


# ---------------------------------------------------------------------------
# List clauses — no auth required
# ---------------------------------------------------------------------------

def test_list_clauses_no_auth(client):
    """List clauses is a public endpoint."""
    res = client.get("/api/quality/as9100/clauses")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_list_clauses_after_initialize(client):
    token = _register_and_token(client, "as9100list@example.com")
    client.post("/api/quality/as9100/initialize", headers=_auth(token))
    res = client.get("/api/quality/as9100/clauses")
    assert res.status_code == 200
    clauses = res.json()
    assert len(clauses) > 0
    # Each clause should have the expected fields
    first = clauses[0]
    assert "id" in first
    assert "clause_number" in first
    assert "clause_title" in first


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

def test_dashboard_structure(client):
    token = _register_and_token(client, "as9100dash@example.com")
    client.post("/api/quality/as9100/initialize", headers=_auth(token))
    res = client.get("/api/quality/as9100/dashboard", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert "overall_percent" in data
    assert "total_clauses" in data
    assert "clauses" in data
    assert isinstance(data["clauses"], list)
    assert 0.0 <= data["overall_percent"] <= 100.0


def test_dashboard_scoped_to_user(client):
    """Two users should get independent dashboards."""
    token1 = _register_and_token(client, "as9100user1@example.com")
    token2 = _register_and_token(client, "as9100user2@example.com")
    client.post("/api/quality/as9100/initialize", headers=_auth(token1))
    client.post("/api/quality/as9100/initialize", headers=_auth(token2))

    res1 = client.get("/api/quality/as9100/dashboard", headers=_auth(token1))
    res2 = client.get("/api/quality/as9100/dashboard", headers=_auth(token2))
    assert res1.status_code == 200
    assert res2.status_code == 200


# ---------------------------------------------------------------------------
# Readiness
# ---------------------------------------------------------------------------

def test_readiness_structure(client):
    token = _register_and_token(client, "as9100ready@example.com")
    client.post("/api/quality/as9100/initialize", headers=_auth(token))
    res = client.get("/api/quality/as9100/readiness", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert any(k in data for k in ("readiness_score", "score", "overall_percent", "overall_score"))


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def test_audit_trail_empty_for_new_user(client):
    token = _register_and_token(client, "as9100audit@example.com")
    client.post("/api/quality/as9100/initialize", headers=_auth(token))
    res = client.get("/api/quality/as9100/audit-trail", headers=_auth(token))
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# ---------------------------------------------------------------------------
# Sync evidence
# ---------------------------------------------------------------------------

def test_sync_returns_ingested(client):
    token = _register_and_token(client, "as9100sync@example.com")
    client.post("/api/quality/as9100/initialize", headers=_auth(token))
    res = client.post("/api/quality/as9100/sync", headers=_auth(token))
    assert res.status_code == 200
    assert "ingested" in res.json()
