"""
Tests for /api/inventory router endpoints.

Covers:
  - GET /api/inventory/status — current stock levels
  - POST /api/inventory/reorder — trigger reorder check
  - POST /api/inventory/consume — consume stock from a schedule
  - GET /api/inventory/reorder-with-suppliers — reorder with supplier suggestions
"""

import pytest


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_inventory_status_ok(client):
    res = client.get("/api/inventory/status")
    assert res.status_code == 200
    data = res.json()
    assert "stock_kg" in data
    assert "reorder_points" in data
    assert "items_below_reorder" in data
    assert isinstance(data["stock_kg"], dict)


def test_inventory_status_has_materials(client):
    """Stock should include at least the core materials."""
    res = client.get("/api/inventory/status")
    data = res.json()
    materials = set(data["stock_kg"].keys())
    assert len(materials) > 0


# ---------------------------------------------------------------------------
# Reorder
# ---------------------------------------------------------------------------

def test_reorder_ok(client):
    res = client.post("/api/inventory/reorder")
    assert res.status_code == 200
    data = res.json()
    assert "purchase_orders" in data
    assert "total_pos_generated" in data
    assert isinstance(data["purchase_orders"], list)


def test_reorder_pos_have_required_fields(client):
    res = client.post("/api/inventory/reorder")
    data = res.json()
    for po in data["purchase_orders"]:
        assert "po_id" in po
        assert "material" in po
        assert "quantity_kg" in po
        assert po["quantity_kg"] > 0


# ---------------------------------------------------------------------------
# Consume
# ---------------------------------------------------------------------------

def test_consume_ok(client):
    res = client.post("/api/inventory/consume", json={
        "schedule_id": "TEST-SCH-001",
        "orders": [
            {"order_id": "ORD-001", "material": "steel", "quantity": 50},
            {"order_id": "ORD-002", "material": "aluminum", "quantity": 30},
        ],
    })
    assert res.status_code == 200
    data = res.json()
    assert data["schedule_id"] == "TEST-SCH-001"
    assert data["total_orders"] == 2
    assert "consumption_kg" in data


def test_consume_missing_orders(client):
    """Missing orders list should be rejected."""
    res = client.post("/api/inventory/consume", json={
        "schedule_id": "SCH-EMPTY",
    })
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Reorder with suppliers
# ---------------------------------------------------------------------------

def test_reorder_with_suppliers_no_geo(client):
    """Without lat/lng, should return suppliers in alphabetical order."""
    res = client.get("/api/inventory/reorder-with-suppliers")
    assert res.status_code == 200
    data = res.json()
    assert "purchase_orders" in data
    assert "total_pos_generated" in data


def test_reorder_with_suppliers_with_geo(client):
    """With lat/lng, should return geo-ranked suppliers."""
    res = client.get("/api/inventory/reorder-with-suppliers?lat=41.5&lng=-81.7&radius_miles=500")
    assert res.status_code == 200
    data = res.json()
    assert "purchase_orders" in data
