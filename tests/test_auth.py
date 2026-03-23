"""
Tests for /api/auth endpoints (register + login).
"""

import pytest


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def test_register_success(client):
    res = client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "securepass123",
        "name": "Alice",
        "company": "Acme",
    })
    assert res.status_code == 201
    data = res.json()
    assert data["email"] == "alice@example.com"
    assert data["name"] == "Alice"
    assert "access_token" in data
    assert data["token_type"] == "bearer"


def test_register_duplicate_email(client):
    payload = {"email": "bob@example.com", "password": "pass1234", "name": "Bob"}
    client.post("/api/auth/register", json=payload)
    res = client.post("/api/auth/register", json=payload)
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_register_email_normalised_to_lowercase(client):
    res = client.post("/api/auth/register", json={
        "email": "UPPER@Example.COM",
        "password": "pass1234",
        "name": "Upper",
    })
    assert res.status_code == 201
    assert res.json()["email"] == "upper@example.com"


def test_register_short_password(client):
    res = client.post("/api/auth/register", json={
        "email": "short@example.com",
        "password": "abc",   # too short
        "name": "Short",
    })
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

def test_login_success(client):
    client.post("/api/auth/register", json={
        "email": "carol@example.com",
        "password": "mypassword",
        "name": "Carol",
    })
    res = client.post("/api/auth/login", json={
        "email": "carol@example.com",
        "password": "mypassword",
    })
    assert res.status_code == 200
    data = res.json()
    assert "access_token" in data
    assert data["email"] == "carol@example.com"


def test_login_wrong_password(client):
    client.post("/api/auth/register", json={
        "email": "dave@example.com",
        "password": "correctpass",
        "name": "Dave",
    })
    res = client.post("/api/auth/login", json={
        "email": "dave@example.com",
        "password": "wrongpass",
    })
    assert res.status_code == 401


def test_login_unknown_email(client):
    res = client.post("/api/auth/login", json={
        "email": "nobody@example.com",
        "password": "anything",
    })
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# JWT token validation
# ---------------------------------------------------------------------------

def test_token_allows_protected_endpoint(client):
    """A valid token should allow access to /api/orders."""
    reg = client.post("/api/auth/register", json={
        "email": "eve@example.com",
        "password": "evespass1",
        "name": "Eve",
    })
    token = reg.json()["access_token"]
    res = client.get("/api/orders", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200


def test_no_token_rejected(client):
    res = client.get("/api/orders")
    assert res.status_code == 401


def test_invalid_token_rejected(client):
    res = client.get("/api/orders", headers={"Authorization": "Bearer not.a.real.token"})
    assert res.status_code == 401
