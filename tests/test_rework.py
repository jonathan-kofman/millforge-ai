"""
Tests for the POST /api/schedule/rework endpoint.
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from routers.rework import _item_to_order, _rework_order_id
from models.schemas import ReworkItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future(hours: int) -> str:
    return (datetime.utcnow() + timedelta(hours=hours)).isoformat() + "Z"


def _make_item(**kwargs) -> dict:
    defaults = {
        "order_id": "ORD-001",
        "material": "steel",
        "quantity": 50,
        "defect_severity": "critical",
        "dimensions": "200x100x10mm",
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Unit: _item_to_order helper
# ---------------------------------------------------------------------------

class TestItemToOrder:

    def test_rework_order_id_prefixed(self):
        assert _rework_order_id("ORD-001") == "RW-ORD-001"

    def test_critical_complexity_is_2_5(self):
        item = ReworkItem(**_make_item(defect_severity="critical"))
        order, mult = _item_to_order(item)
        assert mult == 2.5
        assert order.complexity == 2.5

    def test_major_complexity_is_1_8(self):
        item = ReworkItem(**_make_item(defect_severity="major"))
        order, mult = _item_to_order(item)
        assert mult == 1.8
        assert order.complexity == 1.8

    def test_minor_complexity_is_1_3(self):
        item = ReworkItem(**_make_item(defect_severity="minor"))
        order, mult = _item_to_order(item)
        assert mult == 1.3
        assert order.complexity == 1.3

    def test_priority_is_always_1(self):
        for sev in ("critical", "major", "minor"):
            item = ReworkItem(**_make_item(defect_severity=sev))
            order, _ = _item_to_order(item)
            assert order.priority == 1

    def test_default_due_date_critical_is_24h(self):
        item = ReworkItem(**_make_item(defect_severity="critical"))
        order, _ = _item_to_order(item)
        # Should be approximately 24h from now (allow 5s tolerance)
        expected = datetime.utcnow() + timedelta(hours=24)
        diff = abs((order.due_date - expected).total_seconds())
        assert diff < 5

    def test_default_due_date_major_is_48h(self):
        item = ReworkItem(**_make_item(defect_severity="major"))
        order, _ = _item_to_order(item)
        expected = datetime.utcnow() + timedelta(hours=48)
        diff = abs((order.due_date - expected).total_seconds())
        assert diff < 5

    def test_default_due_date_minor_is_72h(self):
        item = ReworkItem(**_make_item(defect_severity="minor"))
        order, _ = _item_to_order(item)
        expected = datetime.utcnow() + timedelta(hours=72)
        diff = abs((order.due_date - expected).total_seconds())
        assert diff < 5

    def test_explicit_due_date_respected(self):
        explicit = datetime.utcnow() + timedelta(hours=10)
        item = ReworkItem(**_make_item(defect_severity="critical", due_date=explicit))
        order, _ = _item_to_order(item)
        diff = abs((order.due_date - explicit).total_seconds())
        assert diff < 1

    def test_material_preserved(self):
        item = ReworkItem(**_make_item(material="titanium"))
        order, _ = _item_to_order(item)
        assert order.material == "titanium"

    def test_quantity_preserved(self):
        item = ReworkItem(**_make_item(quantity=123))
        order, _ = _item_to_order(item)
        assert order.quantity == 123


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

class TestReworkAPI:

    def test_rework_endpoint_200(self, client):
        payload = {"items": [_make_item()]}
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200

    def test_rework_response_shape(self, client):
        payload = {"items": [_make_item()]}
        r = client.post("/api/schedule/rework", json=payload)
        data = r.json()
        assert "rework_orders_count" in data
        assert "complexity_boosts" in data
        assert "schedule" in data

    def test_rework_orders_count_matches_input(self, client):
        payload = {
            "items": [
                _make_item(order_id="ORD-001", defect_severity="critical"),
                _make_item(order_id="ORD-002", defect_severity="major"),
                _make_item(order_id="ORD-003", defect_severity="minor"),
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.json()["rework_orders_count"] == 3

    def test_complexity_boosts_keyed_by_rework_id(self, client):
        payload = {"items": [_make_item(order_id="ORD-001", defect_severity="critical")]}
        r = client.post("/api/schedule/rework", json=payload)
        boosts = r.json()["complexity_boosts"]
        assert "RW-ORD-001" in boosts
        assert boosts["RW-ORD-001"] == 2.5

    def test_critical_boost_is_2_5(self, client):
        payload = {"items": [_make_item(defect_severity="critical")]}
        r = client.post("/api/schedule/rework", json=payload)
        boosts = r.json()["complexity_boosts"]
        assert list(boosts.values())[0] == 2.5

    def test_major_boost_is_1_8(self, client):
        payload = {"items": [_make_item(defect_severity="major")]}
        r = client.post("/api/schedule/rework", json=payload)
        boosts = r.json()["complexity_boosts"]
        assert list(boosts.values())[0] == 1.8

    def test_minor_boost_is_1_3(self, client):
        payload = {"items": [_make_item(defect_severity="minor")]}
        r = client.post("/api/schedule/rework", json=payload)
        boosts = r.json()["complexity_boosts"]
        assert list(boosts.values())[0] == 1.3

    def test_schedule_contains_rework_order_ids(self, client):
        payload = {"items": [_make_item(order_id="ORD-ALPHA", defect_severity="major")]}
        r = client.post("/api/schedule/rework", json=payload)
        schedule_ids = [o["order_id"] for o in r.json()["schedule"]["schedule"]]
        assert "RW-ORD-ALPHA" in schedule_ids

    def test_schedule_orders_have_priority_1(self, client):
        """Verify rework orders entered the scheduler as priority=1 (on-time for near-term deadline)."""
        payload = {
            "items": [
                _make_item(order_id="ORD-001", defect_severity="critical"),
                _make_item(order_id="ORD-002", defect_severity="minor"),
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["schedule"]["summary"]["total_orders"] == 2

    def test_invalid_severity_returns_422(self, client):
        payload = {"items": [_make_item(defect_severity="catastrophic")]}
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 422

    def test_empty_items_returns_422(self, client):
        r = client.post("/api/schedule/rework", json={"items": []})
        assert r.status_code == 422

    def test_multiple_materials_all_scheduled(self, client):
        payload = {
            "items": [
                _make_item(order_id="A", material="steel",    defect_severity="critical"),
                _make_item(order_id="B", material="aluminum", defect_severity="major"),
                _make_item(order_id="C", material="titanium", defect_severity="minor"),
                _make_item(order_id="D", material="copper",   defect_severity="critical"),
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200
        assert r.json()["rework_orders_count"] == 4
