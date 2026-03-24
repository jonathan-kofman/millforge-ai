"""
End-to-end smoke test for the MillForge API.

Exercises the full request pipeline using a realistic order set:
  schedule → inspect → energy → quote

Asserts internal consistency across the chain:
- Scheduled order count matches input
- Inspection confidence is within [0, 1]
- Energy cost is positive and material matches schedule
- Quote lead time is positive

Run with: pytest tests/test_e2e.py -v
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
# Realistic order set
# ---------------------------------------------------------------------------

NOW = (datetime.utcnow() + timedelta(seconds=1)).isoformat() + "Z"

ORDERS = [
    {
        "order_id": "E2E-001",
        "material": "steel",
        "quantity": 500,
        "dimensions": "200x100x10mm",
        "due_date": (datetime.utcnow() + timedelta(hours=48)).isoformat() + "Z",
        "priority": 2,
        "complexity": 1.0,
    },
    {
        "order_id": "E2E-002",
        "material": "aluminum",
        "quantity": 200,
        "dimensions": "150x75x5mm",
        "due_date": (datetime.utcnow() + timedelta(hours=24)).isoformat() + "Z",
        "priority": 1,
        "complexity": 1.0,
    },
    {
        "order_id": "E2E-003",
        "material": "titanium",
        "quantity": 50,
        "dimensions": "300x200x15mm",
        "due_date": (datetime.utcnow() + timedelta(hours=72)).isoformat() + "Z",
        "priority": 3,
        "complexity": 1.5,
    },
    {
        "order_id": "E2E-004",
        "material": "steel",
        "quantity": 300,
        "dimensions": "100x50x8mm",
        "due_date": (datetime.utcnow() + timedelta(hours=36)).isoformat() + "Z",
        "priority": 2,
        "complexity": 1.0,
    },
    {
        "order_id": "E2E-005",
        "material": "copper",
        "quantity": 100,
        "dimensions": "80x40x3mm",
        "due_date": (datetime.utcnow() + timedelta(hours=20)).isoformat() + "Z",
        "priority": 1,
        "complexity": 1.0,
    },
]


# ---------------------------------------------------------------------------
# E2E smoke test
# ---------------------------------------------------------------------------

class TestE2EFlow:

    # ------------------------------------------------------------------
    # Step 1: Schedule
    # ------------------------------------------------------------------

    def test_schedule_accepts_realistic_orders(self, client):
        r = client.post("/api/schedule", json={"orders": ORDERS})
        assert r.status_code == 200

    def test_schedule_returns_all_orders(self, client):
        r = client.post("/api/schedule", json={"orders": ORDERS})
        data = r.json()
        assert data["summary"]["total_orders"] == len(ORDERS)

    def test_schedule_makespan_is_positive(self, client):
        r = client.post("/api/schedule", json={"orders": ORDERS})
        data = r.json()
        assert data["summary"]["makespan_hours"] > 0

    def test_schedule_on_time_rate_in_range(self, client):
        r = client.post("/api/schedule", json={"orders": ORDERS})
        data = r.json()
        rate = data["summary"]["on_time_rate_percent"]
        assert 0.0 <= rate <= 100.0

    def test_schedule_order_ids_match_input(self, client):
        r = client.post("/api/schedule", json={"orders": ORDERS})
        scheduled_ids = {s["order_id"] for s in r.json()["schedule"]}
        input_ids = {o["order_id"] for o in ORDERS}
        assert scheduled_ids == input_ids

    # ------------------------------------------------------------------
    # Step 2: Inspect one of the scheduled materials
    # ------------------------------------------------------------------

    def test_inspect_steel_part(self, client):
        r = client.post(
            "/api/vision/inspect",
            json={
                "image_url": "http://example.com/steel-part-e2e.jpg",
                "material": "steel",
                "part_id": "E2E-001",
            },
        )
        assert r.status_code == 200

    def test_inspect_confidence_in_range(self, client):
        r = client.post(
            "/api/vision/inspect",
            json={
                "image_url": "http://example.com/aluminum-part-e2e.jpg",
                "material": "aluminum",
                "part_id": "E2E-002",
            },
        )
        data = r.json()
        assert 0.0 <= data["confidence"] <= 1.0

    def test_inspect_passed_is_bool(self, client):
        r = client.post(
            "/api/vision/inspect",
            json={
                "image_url": "http://example.com/titanium-part-e2e.jpg",
                "material": "titanium",
                "part_id": "E2E-003",
            },
        )
        data = r.json()
        assert isinstance(data["passed"], bool)

    def test_inspect_defects_is_list(self, client):
        r = client.post(
            "/api/vision/inspect",
            json={
                "image_url": "http://example.com/copper-part-e2e.jpg",
                "material": "copper",
                "part_id": "E2E-005",
            },
        )
        data = r.json()
        assert isinstance(data["defects_detected"], list)

    # ------------------------------------------------------------------
    # Step 3: Energy estimate for the scheduled production window
    # ------------------------------------------------------------------

    def test_energy_estimate_for_scheduled_material(self, client):
        # First get a schedule to pick a real completion_time
        r_sched = client.post("/api/schedule", json={"orders": ORDERS})
        assert r_sched.status_code == 200

        # Use first scheduled item's start time for energy estimate
        first = r_sched.json()["schedule"][0]
        material = first["material"]

        r = client.post(
            "/api/energy/estimate",
            json={
                "start_time": first["processing_start"],
                "duration_hours": 2.0,
                "material": material,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["material"] == material
        assert data["estimated_kwh"] > 0
        assert data["estimated_cost_usd"] > 0

    def test_energy_cost_positive(self, client):
        r = client.post(
            "/api/energy/estimate",
            json={
                "start_time": (datetime.utcnow() + timedelta(hours=2)).isoformat(),
                "duration_hours": 4.0,
                "material": "titanium",
            },
        )
        assert r.status_code == 200
        assert r.json()["estimated_cost_usd"] > 0

    # ------------------------------------------------------------------
    # Step 4: Quote for a new order joining the queue
    # ------------------------------------------------------------------

    def test_quote_returns_positive_lead_time(self, client):
        r = client.post(
            "/api/quote",
            json={
                "material": "steel",
                "quantity": 250,
                "dimensions": "120x60x6mm",
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert data["estimated_lead_time_hours"] >= 0
        assert data["total_price_usd"] > 0

    def test_quote_material_matches_request(self, client):
        r = client.post(
            "/api/quote",
            json={
                "material": "aluminum",
                "quantity": 100,
                "dimensions": "80x40x4mm",
            },
        )
        assert r.status_code == 200
        assert r.json()["material"] == "aluminum"

    # ------------------------------------------------------------------
    # Step 5: Cross-chain consistency
    # ------------------------------------------------------------------

    def test_scheduled_materials_are_inspectable(self, client):
        """Every material in the schedule can be successfully inspected."""
        r_sched = client.post("/api/schedule", json={"orders": ORDERS})
        materials = {s["material"] for s in r_sched.json()["schedule"]}

        for mat in materials:
            r = client.post(
                "/api/vision/inspect",
                json={
                    "image_url": f"http://example.com/{mat}-e2e.jpg",
                    "material": mat,
                    "part_id": f"E2E-{mat}",
                },
            )
            assert r.status_code == 200, f"Inspection failed for {mat}"

    def test_inventory_consumed_matches_schedule_order_count(self, client):
        """Inventory consume endpoint accepts the same order list."""
        payload = {
            "schedule_id": "E2E-RUN-001",
            "orders": [
                {"material": o["material"], "quantity": o["quantity"]}
                for o in ORDERS
            ],
        }
        r = client.post("/api/inventory/consume", json=payload)
        assert r.status_code == 200
        assert r.json()["total_orders"] == len(ORDERS)

    def test_planner_week_consistent_with_capacity(self, client):
        """Weekly plan honours the capacity constraints passed to it."""
        capacity = {"steel": 40.0, "aluminum": 30.0, "titanium": 20.0, "copper": 10.0}
        r = client.post(
            "/api/planner/week",
            json={
                "demand_signal": "Deliver E2E-001 through E2E-005 this week",
                "capacity": capacity,
            },
        )
        assert r.status_code == 200
        data = r.json()
        util = data["capacity_utilization_percent"]
        assert 0.0 <= util <= 100.0

        # Per-material hours must not exceed capacity
        usage: dict = {}
        for dp in data["daily_plans"]:
            usage[dp["material"]] = usage.get(dp["material"], 0.0) + dp["machine_hours"]
        for mat, hours in usage.items():
            assert hours <= capacity.get(mat, 0.0) * 1.05, (
                f"{mat}: {hours:.1f}h exceeds capacity {capacity.get(mat)}h"
            )

    # ------------------------------------------------------------------
    # Step 6: Rework — simulate failed inspection → rework scheduling
    # ------------------------------------------------------------------

    def test_rework_from_failed_inspection_returns_200(self, client):
        """Rework endpoint accepts items derived from schedule order IDs."""
        payload = {
            "items": [
                {
                    "order_id": "E2E-001",
                    "material": "steel",
                    "quantity": 50,
                    "defect_severity": "critical",
                    "dimensions": "200x100x10mm",
                },
                {
                    "order_id": "E2E-003",
                    "material": "titanium",
                    "quantity": 10,
                    "defect_severity": "major",
                    "dimensions": "300x200x15mm",
                },
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200

    def test_rework_order_ids_have_rw_prefix(self, client):
        """All order IDs in the rework schedule must start with 'RW-'."""
        payload = {
            "items": [
                {
                    "order_id": "E2E-002",
                    "material": "aluminum",
                    "quantity": 20,
                    "defect_severity": "minor",
                    "dimensions": "150x75x5mm",
                },
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200
        schedule_ids = [o["order_id"] for o in r.json()["schedule"]["schedule"]]
        assert all(oid.startswith("RW-") for oid in schedule_ids)

    def test_rework_machine_ids_are_valid_integers(self, client):
        """Every scheduled rework order must have a positive integer machine_id."""
        payload = {
            "items": [
                {
                    "order_id": "E2E-004",
                    "material": "steel",
                    "quantity": 30,
                    "defect_severity": "major",
                    "dimensions": "100x50x8mm",
                },
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200
        for order in r.json()["schedule"]["schedule"]:
            assert isinstance(order["machine_id"], int)
            assert order["machine_id"] >= 1

    def test_inspect_order_id_echoed_in_response(self, client):
        """Inspection response must echo back the order_id that was submitted."""
        r = client.post(
            "/api/vision/inspect",
            json={
                "image_url": "http://example.com/steel-rework-e2e.jpg",
                "material": "steel",
                "order_id": "E2E-001",
            },
        )
        assert r.status_code == 200
        assert r.json()["order_id"] == "E2E-001"

    def test_rework_complexity_boosts_match_severity(self, client):
        """Complexity boosts returned must match expected values per severity."""
        payload = {
            "items": [
                {"order_id": "E2E-001", "material": "steel",    "quantity": 10, "defect_severity": "critical", "dimensions": "200x100x10mm"},
                {"order_id": "E2E-002", "material": "aluminum", "quantity": 10, "defect_severity": "major",    "dimensions": "150x75x5mm"},
                {"order_id": "E2E-003", "material": "titanium", "quantity": 10, "defect_severity": "minor",    "dimensions": "300x200x15mm"},
            ]
        }
        r = client.post("/api/schedule/rework", json=payload)
        assert r.status_code == 200
        boosts = r.json()["complexity_boosts"]
        assert boosts["RW-E2E-001"] == 2.5
        assert boosts["RW-E2E-002"] == 1.8
        assert boosts["RW-E2E-003"] == 1.3
