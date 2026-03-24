"""
Tests for GET /api/orders/schedule-history.
"""

import pytest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers (copied from test_order_schedule.py)
# ---------------------------------------------------------------------------

def _register_and_token(client, email="hist@example.com"):
    res = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "Hist User"
    })
    assert res.status_code == 201
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_order(client, token, material="steel"):
    due = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()
    res = client.post("/api/orders", json={
        "material": material, "dimensions": "200x100x10mm",
        "quantity": 100, "priority": 5, "due_date": due,
    }, headers=_auth(token))
    assert res.status_code == 201


def _run_schedule(client, token, algorithm="sa"):
    res = client.post(f"/api/orders/schedule?algorithm={algorithm}", headers=_auth(token))
    assert res.status_code == 200
    return res.json()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_history_empty_initially(client):
    token = _register_and_token(client)
    res = client.get("/api/orders/schedule-history", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["runs"] == []


def test_history_requires_auth(client):
    res = client.get("/api/orders/schedule-history")
    assert res.status_code == 401


def test_history_appears_after_schedule_run(client):
    token = _register_and_token(client)
    _create_order(client, token)
    _run_schedule(client, token)

    res = client.get("/api/orders/schedule-history", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    run = data["runs"][0]
    assert run["algorithm"] == "sa"
    assert isinstance(run["on_time_rate"], float)
    assert run["makespan_hours"] > 0
    assert isinstance(run["order_ids"], list)
    assert len(run["order_ids"]) == 1
    assert "total_orders" in run["summary"]


def test_history_multiple_runs_newest_first(client):
    token = _register_and_token(client)

    # Run 1: steel order
    _create_order(client, token, "steel")
    run1 = _run_schedule(client, token)

    # Run 2: aluminum order
    _create_order(client, token, "aluminum")
    run2 = _run_schedule(client, token)

    res = client.get("/api/orders/schedule-history", headers=_auth(token))
    data = res.json()
    assert data["total"] == 2
    # Newest first
    assert data["runs"][0]["id"] == run2["schedule_run_id"]
    assert data["runs"][1]["id"] == run1["schedule_run_id"]


def test_history_isolated_between_users(client):
    token1 = _register_and_token(client, "hist_a@example.com")
    token2 = _register_and_token(client, "hist_b@example.com")

    _create_order(client, token1)
    _run_schedule(client, token1)

    # user2 has no history
    res = client.get("/api/orders/schedule-history", headers=_auth(token2))
    assert res.json()["total"] == 0


def test_history_pagination(client):
    token = _register_and_token(client)

    # Create 3 separate schedule runs (one order each)
    for _ in range(3):
        _create_order(client, token)
        _run_schedule(client, token)

    res = client.get("/api/orders/schedule-history?limit=2&offset=0", headers=_auth(token))
    data = res.json()
    assert data["total"] == 3
    assert len(data["runs"]) == 2

    res2 = client.get("/api/orders/schedule-history?limit=2&offset=2", headers=_auth(token))
    data2 = res2.json()
    assert len(data2["runs"]) == 1


def test_history_item_has_required_fields(client):
    token = _register_and_token(client)
    _create_order(client, token)
    _run_schedule(client, token)

    res = client.get("/api/orders/schedule-history", headers=_auth(token))
    run = res.json()["runs"][0]
    for field in ("id", "algorithm", "order_ids", "summary", "on_time_rate", "makespan_hours", "created_at"):
        assert field in run, f"Missing field: {field}"


def test_history_edd_algorithm_recorded(client):
    token = _register_and_token(client)
    _create_order(client, token)
    _run_schedule(client, token, algorithm="edd")

    res = client.get("/api/orders/schedule-history", headers=_auth(token))
    assert res.json()["runs"][0]["algorithm"] == "edd"
