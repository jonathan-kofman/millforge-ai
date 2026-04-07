"""
Tests for the ARIA Scan Bridge pipeline.

Coverage:
  1-4:   ARIABridgeAgent — material mapping
  5-7:   Complexity estimation
  8-9:   Machining time estimation
  10-11: catalog_to_quote / catalog_to_order
  12:    bulk_catalog_to_orders
  13-14: part_summary
  15-16: STLAnalyzer header fallback
  17-18: Router — /api/aria/import and /api/aria/quote (HTTP)
  19:    Router — /api/aria/bulk-import (HTTP)
  20:    Router — /api/aria/complexity-estimate (HTTP)
"""

import sys
import os
import struct
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.aria_bridge_agent import ARIABridgeAgent, MATERIAL_MAP, MATERIAL_MRR
from agents.stl_analyzer import STLAnalyzer


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

TEST_CATALOG_ENTRY = {
    "part_id": "PART-001",
    "material": "6061-T6",
    "bounding_box": {"x": 200.0, "y": 100.0, "z": 30.0},
    "volume_mm3": 250_000.0,
    "primitives_summary": [
        {"type": "hole", "count": 4},
        {"type": "pocket", "count": 2},
        {"type": "thread", "count": 4},
    ],
    "priority": 3,
}

STEEL_ENTRY = {
    "part_id": "STEEL-001",
    "material": "4140",
    "bounding_box": {"x": 100.0, "y": 80.0, "z": 20.0},
    "volume_mm3": 80_000.0,
    "primitives_summary": [{"type": "hole", "count": 2}],
}

MINIMAL_ENTRY = {
    "material": "steel",
    "bounding_box": {"x": 50.0, "y": 50.0, "z": 10.0},
}


def _make_binary_stl(n_triangles: int = 4) -> bytes:
    """Build a minimal valid binary STL with n_triangles."""
    header = b"\x00" * 80
    count = struct.pack("<I", n_triangles)
    triangle = struct.pack("<12f", 0, 0, 1,  # normal
                           0, 0, 0,           # v1
                           10, 0, 0,          # v2
                           5, 10, 0)          # v3
    triangle += struct.pack("<H", 0)          # attribute
    return header + count + triangle * n_triangles


# ---------------------------------------------------------------------------
# 1. Material mapping — known alloys
# ---------------------------------------------------------------------------

def test_material_map_aluminum_alloy():
    agent = ARIABridgeAgent()
    assert agent.map_material("6061-T6") == "aluminum"
    assert agent.map_material("7075-T6") == "aluminum"


def test_material_map_steel_alloy():
    agent = ARIABridgeAgent()
    assert agent.map_material("4140") == "steel"
    assert agent.map_material("316L") == "steel"


def test_material_map_titanium():
    agent = ARIABridgeAgent()
    assert agent.map_material("Ti-6Al-4V") == "titanium"
    assert agent.map_material("titanium") == "titanium"


def test_material_map_unknown_raises():
    agent = ARIABridgeAgent()
    with pytest.raises(ValueError, match="Unknown ARIA material"):
        agent.map_material("unobtanium-99")


# ---------------------------------------------------------------------------
# 5. Complexity — minimal entry
# ---------------------------------------------------------------------------

def test_complexity_no_primitives():
    agent = ARIABridgeAgent()
    complexity = agent.estimate_complexity(MINIMAL_ENTRY)
    assert complexity == 1.0


def test_complexity_with_features():
    agent = ARIABridgeAgent()
    complexity = agent.estimate_complexity(TEST_CATALOG_ENTRY)
    # 4 holes × 0.10 + 2 pockets × 0.20 + 4 threads × 0.12 = 0.40 + 0.40 + 0.48 = 1.28 above base
    assert complexity > 1.0
    assert complexity <= 5.0


def test_complexity_clamped_at_5():
    agent = ARIABridgeAgent()
    heavy = {
        "material": "steel",
        "bounding_box": {"x": 100, "y": 100, "z": 100},
        "primitives_summary": [{"type": "surface", "count": 50}],  # 50 × 0.35 = 17.5 + 1 = 18.5 → clamped
    }
    assert agent.estimate_complexity(heavy) == 5.0


# ---------------------------------------------------------------------------
# 8. Machining time
# ---------------------------------------------------------------------------

def test_machining_time_positive():
    agent = ARIABridgeAgent()
    minutes = agent.estimate_machining_minutes(TEST_CATALOG_ENTRY)
    assert minutes > 0.0


def test_machining_time_steel_slower_than_aluminum():
    agent = ARIABridgeAgent()
    al_entry = dict(TEST_CATALOG_ENTRY, material="6061-T6")
    steel_entry = dict(TEST_CATALOG_ENTRY, material="steel")
    al_min = agent.estimate_machining_minutes(al_entry)
    steel_min = agent.estimate_machining_minutes(steel_entry)
    # Steel MRR < aluminum MRR → steel takes longer
    assert steel_min > al_min


# ---------------------------------------------------------------------------
# 10. catalog_to_quote
# ---------------------------------------------------------------------------

def test_catalog_to_quote_returns_material_and_dimensions():
    agent = ARIABridgeAgent()
    q = agent.catalog_to_quote(TEST_CATALOG_ENTRY, quantity=10)
    assert q["material"] == "aluminum"
    assert "x" in q["dimensions"].lower() or "X" in q["dimensions"]
    assert q["quantity"] == 10
    assert q["complexity"] >= 1.0


def test_catalog_to_order_has_order_id():
    agent = ARIABridgeAgent()
    from datetime import datetime, timedelta, timezone
    due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)
    order = agent.catalog_to_order(TEST_CATALOG_ENTRY, quantity=5, due_date=due)
    assert order["order_id"].startswith("ARIA-")
    assert order["material"] == "aluminum"
    assert order["quantity"] == 5


# ---------------------------------------------------------------------------
# 12. bulk_catalog_to_orders
# ---------------------------------------------------------------------------

def test_bulk_import_skips_bad_material():
    agent = ARIABridgeAgent()
    entries = [
        TEST_CATALOG_ENTRY,
        {"material": "unobtanium-99", "bounding_box": {"x": 10, "y": 10, "z": 5}},
        STEEL_ENTRY,
    ]
    orders = agent.bulk_catalog_to_orders(entries)
    assert len(orders) == 2  # bad entry skipped
    materials = {o["material"] for o in orders}
    assert "aluminum" in materials
    assert "steel" in materials


# ---------------------------------------------------------------------------
# 13. part_summary
# ---------------------------------------------------------------------------

def test_part_summary_valid_material():
    agent = ARIABridgeAgent()
    summary = agent.part_summary(TEST_CATALOG_ENTRY)
    assert summary["material_valid"] is True
    assert summary["material_mapped"] == "aluminum"
    assert summary["feature_count"] == 10  # 4+2+4


def test_part_summary_invalid_material():
    agent = ARIABridgeAgent()
    entry = dict(TEST_CATALOG_ENTRY, material="unobtanium-99")
    summary = agent.part_summary(entry)
    assert summary["material_valid"] is False


# ---------------------------------------------------------------------------
# 15. STLAnalyzer — header fallback
# ---------------------------------------------------------------------------

def test_stl_analyzer_binary_header():
    analyzer = STLAnalyzer()
    stl_bytes = _make_binary_stl(n_triangles=4)
    result = analyzer.analyze(stl_bytes)
    assert result["face_count"] == 4
    assert result["bounding_box"]["x"] > 0 or result["bounding_box"]["y"] > 0
    assert 1.0 <= result["complexity"] <= 5.0


def test_stl_analyzer_empty_returns_zeros():
    analyzer = STLAnalyzer()
    result = analyzer.analyze(b"")
    assert result["face_count"] == 0
    assert result["bounding_box"] == {"x": 0.0, "y": 0.0, "z": 0.0}


# ---------------------------------------------------------------------------
# 17–20. HTTP tests via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from main import app
    with TestClient(app) as c:
        yield c


def test_http_import_returns_order_and_quote(client):
    payload = {
        "catalog_entry": {
            "material": "6061-T6",
            "bounding_box": {"x": 200.0, "y": 100.0, "z": 30.0},
            "volume_mm3": 250000.0,
            "primitives_summary": [{"type": "hole", "count": 4}],
        },
        "quantity": 10,
    }
    resp = client.post("/api/aria/import", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "order" in data
    assert "quote" in data
    assert data["order"]["material"] == "aluminum"
    assert data["quote"]["total_price_usd"] > 0


def test_http_quote_only(client):
    payload = {
        "catalog_entry": {
            "material": "steel",
            "bounding_box": {"x": 100.0, "y": 80.0, "z": 20.0},
        },
        "quantity": 50,
    }
    resp = client.post("/api/aria/quote", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["quote"]["material"] == "steel"
    assert data["quote"]["quantity"] == 50


def test_http_bulk_import(client):
    payload = {
        "catalog_entries": [
            {"material": "aluminum", "bounding_box": {"x": 50, "y": 50, "z": 10}},
            {"material": "titanium", "bounding_box": {"x": 80, "y": 60, "z": 20}},
            {"material": "bad-material-xyz", "bounding_box": {"x": 10, "y": 10, "z": 5}},
        ],
        "default_quantity": 5,
        "default_due_days": 10,
    }
    resp = client.post("/api/aria/bulk-import", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 2
    assert data["skipped"] == 1


def test_http_complexity_estimate(client):
    payload = {
        "primitives_summary": [
            {"type": "hole", "count": 3},
            {"type": "pocket", "count": 1},
        ],
        "material": "aluminum",
    }
    resp = client.post("/api/aria/complexity-estimate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["complexity"] >= 1.0
    assert data["feature_count"] == 4
