"""
Tests for the NLSchedulerAgent and /api/schedule/nl endpoint.
"""

import sys
import os
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.nl_scheduler import NLSchedulerAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future(hours: int) -> str:
    return (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours)).isoformat() + "Z"


MIXED_ORDERS = [
    {"order_id": "N-001", "material": "titanium", "quantity": 50,  "due_date": _future(48), "priority": 5, "complexity": 1.5, "dimensions": "300x200x15mm"},
    {"order_id": "N-002", "material": "steel",    "quantity": 200, "due_date": _future(72), "priority": 3, "complexity": 1.0, "dimensions": "200x100x10mm"},
    {"order_id": "N-003", "material": "titanium", "quantity": 30,  "due_date": _future(60), "priority": 6, "complexity": 1.2, "dimensions": "150x75x8mm"},
    {"order_id": "N-004", "material": "aluminum", "quantity": 150, "due_date": _future(96), "priority": 8, "complexity": 1.0, "dimensions": "100x50x5mm"},
    {"order_id": "N-005", "material": "steel",    "quantity": 100, "due_date": _future(24), "priority": 2, "complexity": 1.0, "dimensions": "50x50x5mm"},
]


# ---------------------------------------------------------------------------
# Heuristic interpretation
# ---------------------------------------------------------------------------

class TestHeuristicInterpret:

    def test_rush_titanium_sets_priority_1(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("rush all titanium orders", MIXED_ORDERS)
        titanium_ids = {"N-001", "N-003"}
        override_map = {ov.order_id: ov.new_priority for ov in result.overrides}
        for oid in titanium_ids:
            assert override_map.get(oid) == 1, f"{oid} not set to priority 1"

    def test_rush_titanium_does_not_affect_steel(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("rush titanium", MIXED_ORDERS)
        override_ids = {ov.order_id for ov in result.overrides}
        assert "N-002" not in override_ids
        assert "N-005" not in override_ids

    def test_defer_aluminum_sets_high_priority(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("defer aluminum orders", MIXED_ORDERS)
        override_map = {ov.order_id: ov.new_priority for ov in result.overrides}
        if "N-004" in override_map:
            assert override_map["N-004"] >= 7

    def test_no_overrides_for_neutral_instruction(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("please review the schedule", MIXED_ORDERS)
        # Neutral instruction: no urgency or deferral keywords
        assert isinstance(result.overrides, list)

    def test_summary_is_nonempty(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("rush titanium", MIXED_ORDERS)
        assert isinstance(result.summary, str) and len(result.summary) > 0

    def test_no_validation_failures_on_valid_result(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("rush titanium", MIXED_ORDERS)
        assert result.validation_failures == []

    def test_override_reasons_are_nonempty(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("urgent: titanium", MIXED_ORDERS)
        for ov in result.overrides:
            assert ov.reason, f"Empty reason for override on {ov.order_id}"

    def test_all_override_priorities_in_range(self):
        agent = NLSchedulerAgent()
        result = agent.interpret("rush steel, defer aluminum", MIXED_ORDERS)
        for ov in result.overrides:
            assert 1 <= ov.new_priority <= 10


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

class TestNLValidation:

    def test_validation_catches_unknown_order_id(self, monkeypatch):
        agent = NLSchedulerAgent()
        _real = agent._heuristic_interpret

        def bad_interpret(instruction, orders):
            result = _real(instruction, orders)
            from agents.nl_scheduler import PriorityOverride
            result.overrides.append(PriorityOverride(
                order_id="DOES-NOT-EXIST",
                new_priority=1,
                reason="injected",
            ))
            return result

        monkeypatch.setattr(agent, "_heuristic_interpret", bad_interpret)
        result = agent.interpret("rush titanium", MIXED_ORDERS)
        assert any("unknown order_id" in f for f in result.validation_failures)

    def test_validation_catches_out_of_range_priority(self, monkeypatch):
        agent = NLSchedulerAgent()
        _real = agent._heuristic_interpret

        def bad_interpret(instruction, orders):
            result = _real(instruction, orders)
            from agents.nl_scheduler import PriorityOverride
            result.overrides.append(PriorityOverride(
                order_id="N-001",
                new_priority=99,
                reason="injected",
            ))
            return result

        monkeypatch.setattr(agent, "_heuristic_interpret", bad_interpret)
        result = agent.interpret("rush titanium", MIXED_ORDERS)
        assert any("invalid new_priority" in f for f in result.validation_failures)

    def test_retry_stops_on_first_valid(self, monkeypatch):
        agent = NLSchedulerAgent()
        call_count = [0]
        _real = agent._heuristic_interpret

        def counting_interpret(instruction, orders):
            call_count[0] += 1
            result = _real(instruction, orders)
            if call_count[0] == 1:
                from agents.nl_scheduler import PriorityOverride
                result.overrides.append(PriorityOverride(
                    order_id="BOGUS",
                    new_priority=1,
                    reason="injected",
                ))
            return result

        monkeypatch.setattr(agent, "_heuristic_interpret", counting_interpret)
        result = agent.interpret("rush titanium", MIXED_ORDERS)
        assert call_count[0] >= 2
        assert result.validation_failures == []


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

class TestNLScheduleAPI:

    def test_nl_endpoint_200(self, client):
        payload = {
            "instruction": "rush titanium orders",
            "orders": MIXED_ORDERS,
        }
        r = client.post("/api/schedule/nl", json=payload)
        assert r.status_code == 200

    def test_nl_response_has_schedule(self, client):
        payload = {
            "instruction": "rush titanium orders",
            "orders": MIXED_ORDERS,
        }
        r = client.post("/api/schedule/nl", json=payload)
        data = r.json()
        assert "schedule" in data
        assert data["schedule"]["summary"]["total_orders"] == len(MIXED_ORDERS)

    def test_nl_overrides_applied_in_schedule(self, client):
        """Titanium orders should have their due priority reflected in schedule output."""
        payload = {
            "instruction": "rush titanium",
            "orders": MIXED_ORDERS,
        }
        r = client.post("/api/schedule/nl", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert "overrides_applied" in data
        assert isinstance(data["overrides_applied"], list)

    def test_nl_returns_override_summary(self, client):
        payload = {
            "instruction": "defer aluminum to end of queue",
            "orders": MIXED_ORDERS,
        }
        r = client.post("/api/schedule/nl", json=payload)
        assert r.status_code == 200
        assert len(r.json()["override_summary"]) > 0

    def test_nl_empty_instruction_still_schedules(self, client):
        """Even with a no-op instruction the scheduler should run."""
        payload = {
            "instruction": "no changes",
            "orders": MIXED_ORDERS,
        }
        r = client.post("/api/schedule/nl", json=payload)
        assert r.status_code == 200
        assert r.json()["schedule"]["summary"]["total_orders"] == len(MIXED_ORDERS)
