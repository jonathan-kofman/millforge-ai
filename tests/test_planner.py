"""
Tests for ProductionPlannerAgent and /api/planner/week endpoint.

Run with: pytest tests/test_planner.py -v
"""

import sys
import os
import json
import pytest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.production_planner import (
    ProductionPlannerAgent,
    WeeklyPlan,
    DailyPlan,
    DAYS,
    THROUGHPUT,
    _get_throughput,
    _fetch_asm_throughput,
    _asm_cache,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

CAPACITY = {"steel": 40.0, "aluminum": 30.0, "titanium": 20.0, "copper": 10.0}
DEMAND = "Rush 500 titanium parts for aerospace, plus routine steel and aluminum"


@pytest.fixture
def heuristic_agent():
    """Agent with no API key — always uses heuristic fallback."""
    return ProductionPlannerAgent(api_key="")


@pytest.fixture
def mock_claude_agent(monkeypatch):
    """Agent with a mocked Anthropic client."""
    agent = ProductionPlannerAgent(api_key="sk-test-fake")

    # Build a valid Claude response
    valid_response = {
        "week_start": "2026-03-23",
        "total_units_planned": 2800,
        "daily_plans": [
            {"day": day, "material": mat, "units": 100, "machine_hours": 8.0}
            for day in DAYS
            for mat in ["steel", "aluminum"]
        ],
        "capacity_utilization_percent": 72.0,
        "bottlenecks": [],
        "recommendations": ["Increase titanium capacity"],
    }

    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(text=json.dumps(valid_response))]

    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_msg
    agent._client = mock_client

    return agent


# ---------------------------------------------------------------------------
# Heuristic planner tests
# ---------------------------------------------------------------------------

class TestHeuristicPlanner:

    def test_returns_weekly_plan(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert isinstance(plan, WeeklyPlan)

    def test_daily_plans_cover_all_days_and_materials(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        days_seen = {dp.day for dp in plan.daily_plans}
        assert days_seen == set(DAYS)

    def test_total_units_positive(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert plan.total_units_planned > 0

    def test_capacity_utilization_in_range(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert 0.0 <= plan.capacity_utilization_percent <= 100.0

    def test_machine_hours_within_capacity(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        usage: dict = {}
        for dp in plan.daily_plans:
            usage[dp.material] = usage.get(dp.material, 0.0) + dp.machine_hours
        for mat, hours in usage.items():
            assert hours <= CAPACITY[mat] * 1.05, f"{mat} exceeds capacity"

    def test_no_negative_units(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        for dp in plan.daily_plans:
            assert dp.units >= 0

    def test_no_negative_machine_hours(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        for dp in plan.daily_plans:
            assert dp.machine_hours >= 0

    def test_no_validation_failures_on_valid_output(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert plan.validation_failures == []

    def test_zero_capacity_material_excluded(self, heuristic_agent):
        cap = {"steel": 40.0, "aluminum": 0.0}
        plan = heuristic_agent.plan_week("Need steel parts", cap)
        for dp in plan.daily_plans:
            assert dp.material != "aluminum"

    def test_recommendations_non_empty(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert isinstance(plan.recommendations, list)


# ---------------------------------------------------------------------------
# Claude-backed planner (mocked)
# ---------------------------------------------------------------------------

class TestClaudePlanner:

    def test_calls_anthropic_client(self, mock_claude_agent):
        mock_claude_agent.plan_week(DEMAND, CAPACITY)
        assert mock_claude_agent._client.messages.create.called

    def test_returns_weekly_plan(self, mock_claude_agent):
        plan = mock_claude_agent.plan_week(DEMAND, CAPACITY)
        assert isinstance(plan, WeeklyPlan)

    def test_parses_total_units(self, mock_claude_agent):
        plan = mock_claude_agent.plan_week(DEMAND, CAPACITY)
        assert plan.total_units_planned == 2800

    def test_falls_back_to_heuristic_on_exception(self, monkeypatch):
        agent = ProductionPlannerAgent(api_key="sk-test-fake")
        mock_client = MagicMock()
        mock_client.messages.create.side_effect = RuntimeError("API down")
        agent._client = mock_client

        plan = agent.plan_week(DEMAND, CAPACITY)
        assert isinstance(plan, WeeklyPlan)
        assert plan.total_units_planned >= 0


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

class TestPlannerValidation:

    def test_validation_catches_negative_utilization(self, heuristic_agent, monkeypatch):
        bad_plan = WeeklyPlan(
            week_start="2026-03-23",
            total_units_planned=100,
            daily_plans=[DailyPlan("Monday", "steel", 10, 4.0)],
            capacity_utilization_percent=-5.0,   # invalid
            bottlenecks=[],
            recommendations=[],
        )
        monkeypatch.setattr(heuristic_agent, "_heuristic_plan", lambda *a, **kw: bad_plan)

        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert len(plan.validation_failures) > 0
        assert any("capacity_utilization_percent" in f for f in plan.validation_failures)

    def test_validation_catches_negative_units(self, heuristic_agent, monkeypatch):
        bad_plan = WeeklyPlan(
            week_start="2026-03-23",
            total_units_planned=100,
            daily_plans=[DailyPlan("Monday", "steel", -10, 4.0)],  # invalid
            capacity_utilization_percent=50.0,
            bottlenecks=[],
            recommendations=[],
        )
        monkeypatch.setattr(heuristic_agent, "_heuristic_plan", lambda *a, **kw: bad_plan)

        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert len(plan.validation_failures) > 0
        assert any("negative units" in f for f in plan.validation_failures)

    def test_retry_stops_on_first_valid(self, heuristic_agent, monkeypatch):
        call_count = {"n": 0}

        good_plan = WeeklyPlan(
            week_start="2026-03-23",
            total_units_planned=100,
            daily_plans=[DailyPlan("Monday", "steel", 10, 4.0)],
            capacity_utilization_percent=10.0,
            bottlenecks=[],
            recommendations=[],
        )
        bad_plan = WeeklyPlan(
            week_start="2026-03-23",
            total_units_planned=100,
            daily_plans=[DailyPlan("Monday", "steel", 10, 4.0)],
            capacity_utilization_percent=-1.0,  # triggers failure
            bottlenecks=[],
            recommendations=[],
        )

        def side_effect(*a, **kw):
            call_count["n"] += 1
            return bad_plan if call_count["n"] == 1 else good_plan

        monkeypatch.setattr(heuristic_agent, "_heuristic_plan", side_effect)

        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert call_count["n"] == 2
        assert plan.validation_failures == []


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

class TestPlannerAPI:

    def test_plan_week_endpoint(self, client):
        payload = {
            "demand_signal": "Need 200 steel parts and 100 aluminum parts this week",
            "capacity": {"steel": 40.0, "aluminum": 30.0, "titanium": 20.0, "copper": 10.0},
        }
        r = client.post("/api/planner/week", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert "week_start" in data
        assert "total_units_planned" in data
        assert "daily_plans" in data
        assert isinstance(data["daily_plans"], list)
        assert "capacity_utilization_percent" in data

    def test_plan_week_returns_valid_utilization(self, client):
        payload = {
            "demand_signal": "Routine production",
            "capacity": {"steel": 20.0, "aluminum": 10.0},
        }
        r = client.post("/api/planner/week", json=payload)
        assert r.status_code == 200
        util = r.json()["capacity_utilization_percent"]
        assert 0.0 <= util <= 100.0

    def test_plan_week_response_includes_data_source(self, client):
        payload = {
            "demand_signal": "Routine production",
            "capacity": {"steel": 20.0, "aluminum": 10.0},
        }
        r = client.post("/api/planner/week", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert "data_source" in data
        assert data["data_source"] in ("US_Census_ASM_2022", "internal_benchmarks")


# ---------------------------------------------------------------------------
# Real data source tests
# ---------------------------------------------------------------------------

class TestDataSource:

    def test_heuristic_plan_has_data_source_field(self, heuristic_agent):
        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert hasattr(plan, "data_source")
        assert plan.data_source in ("US_Census_ASM_2022", "internal_benchmarks")

    def test_fallback_uses_internal_benchmarks(self, heuristic_agent, monkeypatch):
        import agents.production_planner as pm
        monkeypatch.setattr(pm, "_fetch_asm_throughput", lambda: None)
        # Expire cache so the monkeypatched fetch is called
        pm._asm_cache["fetched_at"] = None

        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert plan.data_source == "internal_benchmarks"

    def test_real_asm_data_sets_census_source(self, heuristic_agent, monkeypatch):
        import agents.production_planner as pm
        fake_throughput = {"steel": 11.0, "aluminum": 15.0, "titanium": 6.5, "copper": 13.0}
        monkeypatch.setattr(pm, "_fetch_asm_throughput", lambda: fake_throughput)
        pm._asm_cache["fetched_at"] = None  # expire cache

        plan = heuristic_agent.plan_week(DEMAND, CAPACITY)
        assert plan.data_source == "US_Census_ASM_2022"

    def test_cache_reuses_throughput_within_ttl(self, monkeypatch):
        import time
        import agents.production_planner as pm

        call_count = {"n": 0}

        def counting_fetch():
            call_count["n"] += 1
            return {"steel": 10.0, "aluminum": 14.0, "titanium": 6.0, "copper": 12.0}

        monkeypatch.setattr(pm, "_fetch_asm_throughput", counting_fetch)
        pm._asm_cache["fetched_at"] = None  # prime first fetch

        _get_throughput()   # should call fetch
        _get_throughput()   # should hit cache
        _get_throughput()   # should hit cache

        assert call_count["n"] == 1

    def test_get_throughput_returns_all_materials(self):
        throughput, _ = _get_throughput()
        for mat in ("steel", "aluminum", "titanium", "copper"):
            assert mat in throughput
            assert throughput[mat] > 0
