"""
Tests for the public GET /api/orders/{order_id}/status endpoint.
No authentication required — customer-facing order tracking.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta

import pytest

from db_models import OrderRecord, ScheduleRun, InspectionRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_order(client, material="steel") -> str:
    """Register + login + create an order; return the order_id string."""
    client.post("/api/auth/register", json={
        "email": f"status_test_{material}@example.com",
        "password": "testpass123",
        "name": "Status Test",
    })
    resp = client.post("/api/auth/login", json={
        "email": f"status_test_{material}@example.com",
        "password": "testpass123",
    })
    assert resp.status_code == 200

    due = (datetime.now(timezone.utc) + timedelta(days=14)).strftime("%Y-%m-%dT%H:%M:%S")
    resp = client.post("/api/orders", json={
        "material": material,
        "dimensions": "100x50x25mm",
        "quantity": 10,
        "due_date": due,
    })
    assert resp.status_code == 201
    return resp.json()["order_id"]


# ---------------------------------------------------------------------------
# Status endpoint — public access
# ---------------------------------------------------------------------------

def test_status_returns_200_no_auth(client):
    order_id = _create_order(client, "steel")
    # Call WITHOUT any auth cookie / header
    resp = client.get(f"/api/orders/{order_id}/status")
    assert resp.status_code == 200


def test_status_404_for_unknown_order(client):
    resp = client.get("/api/orders/ORD-DOESNOTEXIST/status")
    assert resp.status_code == 404


def test_status_has_required_fields(client):
    order_id = _create_order(client, "aluminum")
    resp = client.get(f"/api/orders/{order_id}/status")
    body = resp.json()
    for key in [
        "order_id", "status", "material", "quantity",
        "due_date", "scheduled_completion", "on_time",
        "quality_passed", "checked_at",
    ]:
        assert key in body, f"Missing field: {key}"


def test_status_order_id_matches(client):
    order_id = _create_order(client, "copper")
    resp = client.get(f"/api/orders/{order_id}/status")
    assert resp.json()["order_id"] == order_id


def test_status_initial_state_is_pending(client):
    order_id = _create_order(client, "titanium")
    resp = client.get(f"/api/orders/{order_id}/status")
    assert resp.json()["status"] == "pending"


def test_status_no_schedule_completion_when_pending(client):
    order_id = _create_order(client, "steel")
    resp = client.get(f"/api/orders/{order_id}/status")
    body = resp.json()
    assert body["scheduled_completion"] is None
    assert body["on_time"] is None


def test_status_no_quality_when_not_inspected(client):
    order_id = _create_order(client, "aluminum")
    resp = client.get(f"/api/orders/{order_id}/status")
    body = resp.json()
    assert body["quality_passed"] is None
    assert body["quality_checked_at"] is None


def test_status_does_not_expose_internal_fields(client):
    order_id = _create_order(client, "steel")
    body = client.get(f"/api/orders/{order_id}/status").json()
    # These fields must NOT appear in the public status response
    for forbidden in ["created_by_id", "notes", "priority", "complexity", "machine_id", "setup_minutes"]:
        assert forbidden not in body, f"Internal field exposed: {forbidden}"


def test_status_material_correct(client):
    order_id = _create_order(client, "titanium")
    body = client.get(f"/api/orders/{order_id}/status").json()
    assert body["material"] == "titanium"


def test_status_quantity_correct(client):
    """quantity from the order is echoed in the status response."""
    client.post("/api/auth/register", json={
        "email": "qty_check@example.com", "password": "testpass123", "name": "QCheck"
    })
    client.post("/api/auth/login", json={"email": "qty_check@example.com", "password": "testpass123"})
    due = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%S")
    resp = client.post("/api/orders", json={
        "material": "copper", "dimensions": "10x10x10mm", "quantity": 42, "due_date": due,
    })
    order_id = resp.json()["order_id"]
    body = client.get(f"/api/orders/{order_id}/status").json()
    assert body["quantity"] == 42


def test_status_checked_at_is_iso8601(client):
    order_id = _create_order(client, "steel")
    body = client.get(f"/api/orders/{order_id}/status").json()
    # Should parse without raising
    datetime.fromisoformat(body["checked_at"].replace("Z", "+00:00"))


def test_status_shows_scheduled_completion_after_schedule_run(client):
    """After scheduling, scheduled_completion and on_time should be populated."""
    client.post("/api/auth/register", json={
        "email": "sched_status@example.com", "password": "testpass123", "name": "SchedStatus"
    })
    client.post("/api/auth/login", json={"email": "sched_status@example.com", "password": "testpass123"})
    due = (datetime.now(timezone.utc) + timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%S")
    create_resp = client.post("/api/orders", json={
        "material": "steel", "dimensions": "50x50x50mm", "quantity": 5, "due_date": due,
    })
    order_id = create_resp.json()["order_id"]

    # Run the scheduler for this user
    sched_resp = client.post("/api/orders/schedule?algorithm=edd")
    assert sched_resp.status_code == 200

    # Now the status endpoint should have a scheduled_completion
    status_resp = client.get(f"/api/orders/{order_id}/status")
    body = status_resp.json()
    assert body["status"] == "scheduled"
    assert body["scheduled_completion"] is not None
    assert body["on_time"] is not None
    assert body["schedule_run_id"] is not None
