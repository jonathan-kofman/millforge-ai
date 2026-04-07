"""
Tests for /api/aria scan bridge router endpoints.

Covers:
  - POST /api/aria/import — scan catalog → order + quote
  - POST /api/aria/quote — instant quote from scan
  - POST /api/aria/bulk-import — batch import
  - POST /api/aria/complexity-estimate — feature-based complexity
"""

import pytest


_CATALOG_ENTRY = {
    "part_id": "ARIA-TEST-001",
    "material": "6061-T6",
    "bounding_box": {"x": 100.0, "y": 50.0, "z": 25.0},
    "volume_mm3": 125000.0,
    "primitives_summary": [
        {"type": "hole", "count": 4, "key_dimensions": {"diameter_mm": 6.0}},
        {"type": "pocket", "count": 1},
    ],
    "priority": 5,
    "quantity": 10,
}


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def test_import_from_scan_ok(client):
    res = client.post("/api/aria/import", json={
        "catalog_entry": _CATALOG_ENTRY,
        "quantity": 10,
        "due_days": 14,
    })
    assert res.status_code == 200
    data = res.json()
    assert "order" in data
    assert "quote" in data
    assert "part_summary" in data
    assert data["quote"]["quantity"] == 10


def test_import_defaults_quantity(client):
    """Should use catalog_entry.quantity if not explicitly provided."""
    res = client.post("/api/aria/import", json={
        "catalog_entry": _CATALOG_ENTRY,
    })
    assert res.status_code == 200
    assert res.json()["quote"]["quantity"] == 10


def test_import_invalid_material(client):
    entry = dict(_CATALOG_ENTRY, material="unobtanium")
    res = client.post("/api/aria/import", json={"catalog_entry": entry})
    # Should either map to a default or return 422
    assert res.status_code in (200, 422)


def test_import_missing_bounding_box(client):
    entry = {"material": "steel", "quantity": 1}
    res = client.post("/api/aria/import", json={"catalog_entry": entry})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

def test_quote_from_scan_ok(client):
    res = client.post("/api/aria/quote", json={
        "catalog_entry": _CATALOG_ENTRY,
        "quantity": 5,
    })
    assert res.status_code == 200
    data = res.json()
    assert "quote" in data
    assert data["quote"]["total_price_usd"] > 0
    assert data["quote"]["estimated_lead_time_hours"] > 0


def test_quote_quantity_affects_price(client):
    res1 = client.post("/api/aria/quote", json={
        "catalog_entry": _CATALOG_ENTRY, "quantity": 1,
    })
    res100 = client.post("/api/aria/quote", json={
        "catalog_entry": _CATALOG_ENTRY, "quantity": 100,
    })
    assert res1.status_code == 200
    assert res100.status_code == 200
    # 100 units should cost more total
    assert res100.json()["quote"]["total_price_usd"] > res1.json()["quote"]["total_price_usd"]


# ---------------------------------------------------------------------------
# Bulk import
# ---------------------------------------------------------------------------

def test_bulk_import_ok(client):
    res = client.post("/api/aria/bulk-import", json={
        "catalog_entries": [
            _CATALOG_ENTRY,
            dict(_CATALOG_ENTRY, part_id="ARIA-TEST-002", material="steel"),
        ],
        "default_quantity": 5,
        "default_due_days": 7,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["imported"] == 2
    assert data["skipped"] == 0
    assert len(data["orders"]) == 2


def test_bulk_import_empty_list(client):
    res = client.post("/api/aria/bulk-import", json={
        "catalog_entries": [],
    })
    assert res.status_code == 422  # min_length=1


# ---------------------------------------------------------------------------
# Complexity estimate
# ---------------------------------------------------------------------------

def test_complexity_estimate_ok(client):
    res = client.post("/api/aria/complexity-estimate", json={
        "primitives_summary": [
            {"type": "hole", "count": 10},
            {"type": "pocket", "count": 2},
            {"type": "thread", "count": 4},
        ],
        "material": "titanium",
    })
    assert res.status_code == 200
    data = res.json()
    assert "complexity" in data
    assert "feature_count" in data
    assert data["feature_count"] == 16


def test_complexity_estimate_empty_features(client):
    res = client.post("/api/aria/complexity-estimate", json={
        "primitives_summary": [],
    })
    assert res.status_code == 200
    assert res.json()["complexity"] >= 1
