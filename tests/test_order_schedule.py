"""
Tests for POST /api/orders/schedule — orders-to-scheduler integration.
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
    client.cookies.clear()
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_order(client, token, material="steel", quantity=100, days_ahead=30):
    due_date = (datetime.now(timezone.utc) + timedelta(days=days_ahead)).isoformat()
    res = client.post("/api/orders", json={
        "material": material,
        "dimensions": "200x100x10mm",
        "quantity": quantity,
        "priority": 5,
        "due_date": due_date,
    }, headers=_auth(token))
    assert res.status_code == 201
    return res.json()


# ---------------------------------------------------------------------------
# schedule_pending_orders
# ---------------------------------------------------------------------------

def test_schedule_pending_orders_success(client):
    token = _register_and_token(client)
    _create_order(client, token, "steel", 100)
    _create_order(client, token, "aluminum", 200)

    res = client.post("/api/orders/schedule", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()

    assert data["orders_scheduled"] == 2
    assert data["schedule_run_id"] >= 1
    assert data["algorithm"] == "sa"
    assert len(data["schedule"]) == 2
    assert data["summary"]["total_orders"] == 2
    assert "generated_at" in data


def test_schedule_uses_edd_algorithm(client):
    token = _register_and_token(client)
    _create_order(client, token)

    res = client.post("/api/orders/schedule?algorithm=edd", headers=_auth(token))
    assert res.status_code == 200
    assert res.json()["algorithm"] == "edd"


def test_schedule_marks_orders_as_scheduled(client):
    token = _register_and_token(client)
    _create_order(client, token)
    _create_order(client, token)

    client.post("/api/orders/schedule", headers=_auth(token))

    # All orders should now be "scheduled"
    res = client.get("/api/orders?status=pending", headers=_auth(token))
    assert res.json()["total"] == 0

    res = client.get("/api/orders?status=scheduled", headers=_auth(token))
    assert res.json()["total"] == 2


def test_schedule_no_pending_orders_returns_400(client):
    token = _register_and_token(client)
    # No orders created
    res = client.post("/api/orders/schedule", headers=_auth(token))
    assert res.status_code == 400
    assert "pending" in res.json()["detail"].lower()


def test_schedule_skips_non_pending_orders(client):
    token = _register_and_token(client)
    created = _create_order(client, token)

    # Manually mark the one order as "in_progress"
    client.patch(
        f"/api/orders/{created['order_id']}",
        json={"status": "in_progress"},
        headers=_auth(token),
    )

    res = client.post("/api/orders/schedule", headers=_auth(token))
    assert res.status_code == 400  # nothing pending


def test_schedule_only_affects_own_orders(client):
    token1 = _register_and_token(client, "user1@example.com")
    token2 = _register_and_token(client, "user2@example.com")

    _create_order(client, token1)  # user1's order
    _create_order(client, token2)  # user2's order

    # user1 schedules
    res = client.post("/api/orders/schedule", headers=_auth(token1))
    assert res.status_code == 200
    assert res.json()["orders_scheduled"] == 1

    # user2's order is still pending
    res2 = client.get("/api/orders?status=pending", headers=_auth(token2))
    assert res2.json()["total"] == 1


def test_schedule_requires_auth(client):
    res = client.post("/api/orders/schedule")
    assert res.status_code == 401


def test_schedule_response_has_gantt_data(client):
    """Each scheduled order should have machine assignment and timing data."""
    token = _register_and_token(client)
    _create_order(client, token, "titanium", 50)

    res = client.post("/api/orders/schedule", headers=_auth(token))
    assert res.status_code == 200
    item = res.json()["schedule"][0]

    assert "machine_id" in item
    assert "setup_start" in item
    assert "processing_start" in item
    assert "completion_time" in item
    assert "on_time" in item
    assert isinstance(item["machine_id"], int)
