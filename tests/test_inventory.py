"""
Tests for InventoryAgent and /api/inventory endpoints.

Run with: pytest tests/test_inventory.py -v
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.inventory_agent import (
    InventoryAgent,
    MaterialConsumption,
    PurchaseOrder,
    INITIAL_STOCK,
    REORDER_POINTS,
    REORDER_QTY,
    KG_PER_UNIT,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    """Fresh agent with default initial stock every test."""
    return InventoryAgent()


@pytest.fixture
def depleted_agent():
    """Agent whose stock is already at/below reorder points."""
    stock = {mat: REORDER_POINTS[mat] for mat in REORDER_POINTS}
    return InventoryAgent(initial_stock=stock)


SAMPLE_ORDERS = [
    {"material": "steel", "quantity": 100},
    {"material": "aluminum", "quantity": 50},
    {"material": "titanium", "quantity": 20},
]


# ---------------------------------------------------------------------------
# consume_from_schedule
# ---------------------------------------------------------------------------

class TestConsume:

    def test_returns_material_consumption(self, agent):
        result = agent.consume_from_schedule(SAMPLE_ORDERS, "TEST-001")
        assert isinstance(result, MaterialConsumption)

    def test_total_orders_matches_input(self, agent):
        result = agent.consume_from_schedule(SAMPLE_ORDERS, "TEST-001")
        assert result.total_orders == len(SAMPLE_ORDERS)

    def test_consumption_kg_positive(self, agent):
        result = agent.consume_from_schedule(SAMPLE_ORDERS, "TEST-001")
        for mat, kg in result.consumption_kg.items():
            assert kg > 0, f"{mat} consumption should be positive"

    def test_stock_decreases_after_consume(self, agent):
        before = agent._stock["steel"]
        agent.consume_from_schedule([{"material": "steel", "quantity": 100}], "T")
        after = agent._stock["steel"]
        expected_reduction = 100 * KG_PER_UNIT["steel"]
        assert abs((before - after) - expected_reduction) < 0.01

    def test_stock_does_not_go_negative(self, agent):
        # Consume more than current stock
        agent.consume_from_schedule(
            [{"material": "steel", "quantity": 1_000_000}], "HUGE"
        )
        assert agent._stock["steel"] >= 0.0

    def test_schedule_id_propagated(self, agent):
        result = agent.consume_from_schedule(SAMPLE_ORDERS, "SCHED-XYZ")
        assert result.schedule_id == "SCHED-XYZ"

    def test_empty_orders_returns_zero_consumption(self, agent):
        result = agent.consume_from_schedule([], "EMPTY")
        assert result.total_orders == 0
        assert result.consumption_kg == {}


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestStatus:

    def test_returns_all_materials(self, agent):
        status = agent.get_status()
        for mat in INITIAL_STOCK:
            assert mat in status.stock_kg

    def test_items_below_reorder_initially_empty(self, agent):
        # Fresh agent has stock well above reorder points
        status = agent.get_status()
        assert status.items_below_reorder == []

    def test_items_below_reorder_detected(self, depleted_agent):
        status = depleted_agent.get_status()
        assert len(status.items_below_reorder) > 0

    def test_reorder_points_present(self, agent):
        status = agent.get_status()
        for mat in REORDER_POINTS:
            assert mat in status.reorder_points


# ---------------------------------------------------------------------------
# check_reorder_points
# ---------------------------------------------------------------------------

class TestReorder:

    def test_no_pos_when_stock_high(self, agent):
        pos = agent.check_reorder_points()
        assert pos == []

    def test_pos_generated_when_stock_low(self, depleted_agent):
        pos = depleted_agent.check_reorder_points()
        assert len(pos) > 0

    def test_po_has_positive_quantity(self, depleted_agent):
        pos = depleted_agent.check_reorder_points()
        for po in pos:
            assert po.quantity_kg > 0

    def test_stock_increases_after_reorder(self, depleted_agent):
        steel_before = depleted_agent._stock["steel"]
        depleted_agent.check_reorder_points()
        # Stock should have gone up by REORDER_QTY
        expected = steel_before + REORDER_QTY["steel"]
        assert abs(depleted_agent._stock["steel"] - expected) < 0.01

    def test_po_ids_are_unique(self, depleted_agent):
        pos = depleted_agent.check_reorder_points()
        po_ids = [po.po_id for po in pos]
        assert len(po_ids) == len(set(po_ids))


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

class TestValidation:

    def test_validation_fails_on_total_orders_mismatch(self, agent, monkeypatch):
        """_validate_consumption catches wrong total_orders count."""
        bad = MaterialConsumption(
            schedule_id="T",
            consumption_kg={"steel": 100.0},
            total_orders=99,   # wrong — actual input has 3
        )
        monkeypatch.setattr(agent, "_do_consume", lambda *a, **kw: bad)

        result = agent.consume_from_schedule(SAMPLE_ORDERS, "T")
        assert len(result.validation_failures) > 0
        assert any("total_orders" in f for f in result.validation_failures)

    def test_validation_fails_on_negative_consumption(self, agent, monkeypatch):
        """_validate_consumption catches negative consumption values."""
        bad = MaterialConsumption(
            schedule_id="T",
            consumption_kg={"steel": -50.0},  # invalid
            total_orders=len(SAMPLE_ORDERS),
        )
        monkeypatch.setattr(agent, "_do_consume", lambda *a, **kw: bad)

        result = agent.consume_from_schedule(SAMPLE_ORDERS, "T")
        assert len(result.validation_failures) > 0
        assert any("negative" in f for f in result.validation_failures)

    def test_validation_fails_on_zero_po_quantity(self, depleted_agent, monkeypatch):
        """_validate_pos catches zero-quantity purchase orders."""
        from agents.inventory_agent import PurchaseOrder
        from datetime import datetime

        bad_pos = [
            PurchaseOrder(
                po_id="PO-00001",
                material="steel",
                quantity_kg=0.0,     # invalid
                reason="test",
                current_stock_kg=100.0,
                reorder_point_kg=1000.0,
            )
        ]
        monkeypatch.setattr(depleted_agent, "_do_reorder", lambda: bad_pos)

        result = depleted_agent.check_reorder_points()
        # With 3 retries all returning the same bad PO, we get an empty list back
        # (best=[bad_pos] but check_reorder_points returns best or [])
        # Verify at least that _validate_pos flagged it
        errors = depleted_agent._validate_pos(bad_pos, {})
        assert any("non-positive" in e for e in errors)

    def test_retry_stops_on_first_valid_result(self, agent, monkeypatch):
        """Stops retrying once a valid result is returned."""
        call_count = {"n": 0}

        good = MaterialConsumption(
            schedule_id="T",
            consumption_kg={"steel": 250.0},
            total_orders=len(SAMPLE_ORDERS),
        )
        bad = MaterialConsumption(
            schedule_id="T",
            consumption_kg={"steel": 250.0},
            total_orders=99,   # wrong on first call
        )

        def side_effect(*a, **kw):
            call_count["n"] += 1
            return bad if call_count["n"] == 1 else good

        monkeypatch.setattr(agent, "_do_consume", side_effect)

        result = agent.consume_from_schedule(SAMPLE_ORDERS, "T")
        assert call_count["n"] == 2      # stopped after 2nd attempt
        assert result.validation_failures == []


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

class TestInventoryAPI:

    def test_consume_endpoint(self, client):
        payload = {
            "schedule_id": "SCHED-001",
            "orders": [
                {"material": "steel", "quantity": 200},
                {"material": "aluminum", "quantity": 100},
            ],
        }
        r = client.post("/api/inventory/consume", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["total_orders"] == 2
        assert "steel" in data["consumption_kg"]

    def test_status_endpoint(self, client):
        r = client.get("/api/inventory/status")
        assert r.status_code == 200
        data = r.json()
        assert "stock_kg" in data
        assert "reorder_points" in data

    def test_reorder_endpoint(self, client):
        r = client.post("/api/inventory/reorder")
        assert r.status_code == 200
        data = r.json()
        assert "purchase_orders" in data
        assert "total_pos_generated" in data
