"""
Tests for /api/orders CRUD endpoints.
"""

import pytest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_token(client, email="user@example.com"):
    res = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "Test User"
    })
    assert res.status_code == 201
    # Clear the session cookie so Bearer tokens aren't shadowed by the cookie jar
    # when multiple users are registered in the same test.
    client.cookies.clear()
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _due_date():
    return (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def test_create_order_success(client):
    token = _register_and_token(client)
    res = client.post("/api/orders", json={
        "material": "steel",
        "dimensions": "200x100x10mm",
        "quantity": 500,
        "priority": 2,
        "due_date": _due_date(),
    }, headers=_auth(token))
    assert res.status_code == 201
    data = res.json()
    assert data["material"] == "steel"
    assert data["quantity"] == 500
    assert data["status"] == "pending"
    assert data["order_id"].startswith("ORD-")


def test_create_order_requires_auth(client):
    res = client.post("/api/orders", json={
        "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
    })
    assert res.status_code == 401


def test_create_order_invalid_material(client):
    token = _register_and_token(client)
    res = client.post("/api/orders", json={
        "material": "unobtanium",
        "dimensions": "100x50x5mm",
        "quantity": 100,
    }, headers=_auth(token))
    assert res.status_code == 422


def test_create_order_defaults_due_date(client):
    """If no due_date is given, the backend should set one automatically."""
    token = _register_and_token(client)
    res = client.post("/api/orders", json={
        "material": "aluminum",
        "dimensions": "150x75x5mm",
        "quantity": 200,
    }, headers=_auth(token))
    assert res.status_code == 201
    assert res.json()["due_date"] is not None


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

def test_list_orders_empty(client):
    token = _register_and_token(client)
    res = client.get("/api/orders", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["orders"] == []


def test_list_orders_returns_own_orders_only(client):
    token1 = _register_and_token(client, "user1@example.com")
    token2 = _register_and_token(client, "user2@example.com")

    # user1 creates 2 orders
    for _ in range(2):
        client.post("/api/orders", json={
            "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
        }, headers=_auth(token1))

    # user2 creates 1 order
    client.post("/api/orders", json={
        "material": "copper", "dimensions": "50x25x3mm", "quantity": 50
    }, headers=_auth(token2))

    res1 = client.get("/api/orders", headers=_auth(token1))
    res2 = client.get("/api/orders", headers=_auth(token2))

    assert res1.json()["total"] == 2
    assert res2.json()["total"] == 1


def test_list_orders_status_filter(client):
    token = _register_and_token(client)
    # create 2 orders
    for i in range(2):
        client.post("/api/orders", json={
            "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
        }, headers=_auth(token))

    res = client.get("/api/orders?status=pending", headers=_auth(token))
    assert res.json()["total"] == 2

    res = client.get("/api/orders?status=completed", headers=_auth(token))
    assert res.json()["total"] == 0


# ---------------------------------------------------------------------------
# Get single
# ---------------------------------------------------------------------------

def test_get_order_success(client):
    token = _register_and_token(client)
    created = client.post("/api/orders", json={
        "material": "titanium", "dimensions": "300x200x15mm", "quantity": 50
    }, headers=_auth(token)).json()

    res = client.get(f"/api/orders/{created['order_id']}", headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["order_id"] == created["order_id"]


def test_get_order_not_found(client):
    token = _register_and_token(client)
    res = client.get("/api/orders/ORD-DOESNOTEXIST", headers=_auth(token))
    assert res.status_code == 404


def test_get_order_cant_access_other_users(client):
    token1 = _register_and_token(client, "owner@example.com")
    token2 = _register_and_token(client, "other@example.com")
    created = client.post("/api/orders", json={
        "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
    }, headers=_auth(token1)).json()

    res = client.get(f"/api/orders/{created['order_id']}", headers=_auth(token2))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def test_update_order_priority(client):
    token = _register_and_token(client)
    created = client.post("/api/orders", json={
        "material": "steel", "dimensions": "100x50x5mm", "quantity": 100, "priority": 5
    }, headers=_auth(token)).json()

    res = client.patch(f"/api/orders/{created['order_id']}", json={"priority": 1},
                       headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["priority"] == 1


def test_update_order_status(client):
    token = _register_and_token(client)
    created = client.post("/api/orders", json={
        "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
    }, headers=_auth(token)).json()

    res = client.patch(
        f"/api/orders/{created['order_id']}",
        json={"status": "scheduled"},
        headers=_auth(token),
    )
    assert res.status_code == 200
    assert res.json()["status"] == "scheduled"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_order_success(client):
    token = _register_and_token(client)
    created = client.post("/api/orders", json={
        "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
    }, headers=_auth(token)).json()

    res = client.delete(f"/api/orders/{created['order_id']}", headers=_auth(token))
    assert res.status_code == 204

    # Confirm gone
    res2 = client.get(f"/api/orders/{created['order_id']}", headers=_auth(token))
    assert res2.status_code == 404


def test_delete_other_users_order(client):
    token1 = _register_and_token(client, "owner2@example.com")
    token2 = _register_and_token(client, "other2@example.com")
    created = client.post("/api/orders", json={
        "material": "steel", "dimensions": "100x50x5mm", "quantity": 100
    }, headers=_auth(token1)).json()

    res = client.delete(f"/api/orders/{created['order_id']}", headers=_auth(token2))
    assert res.status_code == 404
