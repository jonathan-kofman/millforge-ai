"""
Tests for GET /api/dashboard/live and the DashboardAgent.
"""

import sys
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.dashboard import DashboardAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    db.query.return_value.order_by.return_value.first.return_value = None
    db.query.return_value.filter.return_value.order_by.return_value.first.return_value = None
    return db


def _make_schedule_run(on_time_rate=0.857, makespan_hours=12.5, algorithm="sa"):
    run = MagicMock()
    run.id = 1
    run.algorithm = algorithm
    run.on_time_rate = on_time_rate
    run.makespan_hours = makespan_hours
    run.created_at = datetime.now(timezone.utc).replace(tzinfo=None)
    run.summary = {
        "total_orders": 10,
        "on_time_count": 9,
        "on_time_rate_percent": 90.0,
        "makespan_hours": 12.5,
        "utilization_percent": 85.0,
    }
    return run


def _make_machine_log_row(machine_id: int, to_state: str, hours_ago: float = 0.5):
    row = MagicMock()
    row.machine_id = machine_id
    row.to_state = to_state
    row.occurred_at = (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours_ago))
    return row


# ---------------------------------------------------------------------------
# DashboardAgent unit tests
# ---------------------------------------------------------------------------

class TestDashboardAgentExceptions:

    def test_exceptions_returns_counts(self, monkeypatch):
        agent = DashboardAgent()
        db = _make_db()

        from agents import exception_queue as eq_module

        mock_items = [
            MagicMock(source="machine_fault", severity="critical", resolved=False),
            MagicMock(source="held_order",    severity="critical", resolved=False),
            MagicMock(source="low_inventory", severity="warning",  resolved=False),
        ]

        monkeypatch.setattr(
            eq_module.ExceptionQueueAgent,
            "gather",
            lambda self, db, **kw: mock_items,
        )

        result = agent._exceptions(db)
        assert result["total"] == 3
        assert result["critical"] == 2
        assert result["warning"] == 1
        assert result["by_source"]["machine_fault"] == 1

    def test_exceptions_returns_degraded_on_failure(self):
        agent = DashboardAgent()
        db = _make_db()

        with patch("agents.exception_queue.ExceptionQueueAgent.gather", side_effect=RuntimeError("boom")):
            result = agent._exceptions(db)
        assert result["total"] is None
        assert "error" in result


class TestDashboardAgentScheduleHealth:

    def test_schedule_health_no_runs(self):
        agent = DashboardAgent()
        db = _make_db()
        result = agent._schedule_health(db)
        assert result["status"] == "no_runs"
        assert result["on_time_rate_percent"] is None

    def test_schedule_health_with_run(self):
        agent = DashboardAgent()
        db = _make_db()
        run = _make_schedule_run(on_time_rate=0.857, algorithm="sa")
        db.query.return_value.order_by.return_value.first.return_value = run

        result = agent._schedule_health(db)
        assert result["status"] == "ok"
        assert result["on_time_rate_percent"] == 85.7
        assert result["algorithm"] == "sa"
        assert result["makespan_hours"] == 12.5


class TestDashboardAgentMachineStates:

    def test_machine_states_empty_history(self):
        agent = DashboardAgent()
        db = _make_db()
        result = agent._machine_states(db)
        assert result["total_machines"] == 0
        assert result["running"] == 0

    def test_machine_states_latest_per_machine(self):
        agent = DashboardAgent()
        db = _make_db()

        rows = [
            _make_machine_log_row(machine_id=1, to_state="RUNNING", hours_ago=0.1),
            _make_machine_log_row(machine_id=1, to_state="SETUP",   hours_ago=0.5),
            _make_machine_log_row(machine_id=2, to_state="IDLE",    hours_ago=0.2),
            _make_machine_log_row(machine_id=3, to_state="FAULT",   hours_ago=0.3),
        ]
        db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = rows

        result = agent._machine_states(db)
        assert result["total_machines"] == 3
        assert result["running"] == 1
        assert result["idle"] == 1
        assert result["fault"] == 1
        assert result["per_machine"][1] == "RUNNING"


class TestDashboardAgentMaintenanceRisk:

    def test_maintenance_risk_aggregates_levels(self, monkeypatch):
        agent = DashboardAgent()
        db = _make_db()

        from agents import predictive_maintenance as pm_module
        signals = [
            {"machine_id": 1, "risk_level": "urgent",       "fault_count_24h": 3},
            {"machine_id": 2, "risk_level": "service_soon", "fault_count_24h": 2},
            {"machine_id": 3, "risk_level": "watch",        "fault_count_24h": 1},
            {"machine_id": 4, "risk_level": "ok",           "fault_count_24h": 0},
        ]
        monkeypatch.setattr(
            pm_module.PredictiveMaintenanceAgent,
            "signals",
            lambda self, db: signals,
        )

        result = agent._maintenance_risk(db)
        assert result["total_monitored"] == 4
        assert result["urgent"] == 1
        assert result["service_soon"] == 1
        assert result["watch"] == 1
        assert result["ok"] == 1
        assert result["urgent_machine_ids"] == [1]


class TestDashboardAgentInventoryHealth:

    def test_inventory_health_unavailable_without_agent(self):
        agent = DashboardAgent(inventory_agent=None)
        result = agent._inventory_health()
        assert result["status"] == "unavailable"

    def test_inventory_health_with_items_below_reorder(self):
        mock_inventory = MagicMock()
        mock_status = MagicMock()
        mock_status.items_below_reorder = ["steel", "aluminum"]

        def make_detail(current, reorder):
            d = MagicMock()
            d.current_stock_kg = current
            d.reorder_point_kg = reorder
            return d

        mock_status.stock = {
            "steel":    make_detail(50, 200),    # critical (50 < 100)
            "aluminum": make_detail(120, 200),   # not critical
        }
        mock_inventory.check_reorder_points.return_value = mock_status

        agent = DashboardAgent(inventory_agent=mock_inventory)
        result = agent._inventory_health()
        assert result["status"] == "ok"
        assert "steel" in result["items_below_reorder"]
        assert result["critical_count"] == 1


class TestDashboardAgentEnergyToday:

    def test_energy_today_returns_cost(self):
        agent = DashboardAgent()
        result = agent._energy_today()
        assert result["status"] == "ok"
        assert result["shift_cost_usd"] > 0
        assert result["shift_carbon_kg"] > 0
        assert isinstance(result["cheapest_hours"], list)
        assert len(result["cheapest_hours"]) == 4


class TestLightsOutScore:

    def test_perfect_score_no_issues(self):
        agent = DashboardAgent()
        exceptions = {"critical": 0, "warning": 0, "info": 0}
        schedule   = {"on_time_rate_percent": 96.0}
        maintenance = {"urgent": 0, "service_soon": 0}
        result = agent._lights_out_score(exceptions, schedule, maintenance)
        assert result["score"] == 100
        assert result["level"] == "optimal"

    def test_critical_exceptions_reduce_score(self):
        agent = DashboardAgent()
        exceptions  = {"critical": 3, "warning": 0, "info": 0}
        schedule    = {"on_time_rate_percent": 95.0}
        maintenance = {"urgent": 0, "service_soon": 0}
        result = agent._lights_out_score(exceptions, schedule, maintenance)
        assert result["score"] == 70  # 100 - 30

    def test_low_on_time_reduces_score(self):
        agent = DashboardAgent()
        exceptions  = {"critical": 0, "warning": 0, "info": 0}
        schedule    = {"on_time_rate_percent": 75.0}  # < 80 → -15
        maintenance = {"urgent": 0, "service_soon": 0}
        result = agent._lights_out_score(exceptions, schedule, maintenance)
        assert result["score"] == 85

    def test_urgent_machines_reduce_score(self):
        agent = DashboardAgent()
        exceptions  = {"critical": 0, "warning": 0}
        schedule    = {"on_time_rate_percent": 95.0}
        maintenance = {"urgent": 2, "service_soon": 0}  # 2 * 20 = 40 → max -40
        result = agent._lights_out_score(exceptions, schedule, maintenance)
        assert result["score"] == 60

    def test_score_clamped_at_zero(self):
        agent = DashboardAgent()
        exceptions  = {"critical": 10, "warning": 10}  # -40 + -20 = -60
        schedule    = {"on_time_rate_percent": 50.0}    # -15
        maintenance = {"urgent": 5, "service_soon": 5}  # -40 + -20 = -60
        result = agent._lights_out_score(exceptions, schedule, maintenance)
        assert result["score"] == 0
        assert result["level"] == "critical"

    def test_score_none_on_time_ignored(self):
        agent = DashboardAgent()
        exceptions  = {"critical": 0, "warning": 0}
        schedule    = {"on_time_rate_percent": None}
        maintenance = {"urgent": 0, "service_soon": 0}
        result = agent._lights_out_score(exceptions, schedule, maintenance)
        assert result["score"] == 100


# ---------------------------------------------------------------------------
# Full live() integration
# ---------------------------------------------------------------------------

class TestDashboardLiveFull:

    def test_live_returns_all_sections(self, monkeypatch):
        agent = DashboardAgent()
        db = _make_db()

        # Stub all collectors
        monkeypatch.setattr(agent, "_exceptions",      lambda db: {"total": 0, "critical": 0, "warning": 0, "info": 0, "by_source": {}})
        monkeypatch.setattr(agent, "_schedule_health", lambda db: {"status": "no_runs", "on_time_rate_percent": None})
        monkeypatch.setattr(agent, "_machine_states",  lambda db: {"total_machines": 0, "running": 0, "idle": 0, "fault": 0, "per_machine": {}, "state_counts": {}})
        monkeypatch.setattr(agent, "_maintenance_risk", lambda db: {"total_monitored": 0, "urgent": 0, "service_soon": 0, "watch": 0, "ok": 0, "urgent_machine_ids": []})
        monkeypatch.setattr(agent, "_inventory_health", lambda: {"status": "unavailable"})
        monkeypatch.setattr(agent, "_energy_today",    lambda: {"status": "ok", "shift_cost_usd": 22.4, "shift_carbon_kg": 215.0, "cheapest_hours": [2, 3, 4, 5], "avg_rate_usd_kwh": 0.04})

        result = agent.live(db)
        for key in ("collected_at", "lights_out_score", "open_exceptions", "schedule_health",
                    "machine_states", "maintenance_risk", "inventory_health", "energy_today"):
            assert key in result, f"Missing key: {key}"

    def test_live_score_is_dict_with_level(self, monkeypatch):
        agent = DashboardAgent()
        db = _make_db()
        monkeypatch.setattr(agent, "_exceptions",      lambda db: {"total": 0, "critical": 0, "warning": 0, "info": 0, "by_source": {}})
        monkeypatch.setattr(agent, "_schedule_health", lambda db: {"status": "no_runs", "on_time_rate_percent": None})
        monkeypatch.setattr(agent, "_machine_states",  lambda db: {"total_machines": 0, "running": 0, "idle": 0, "fault": 0, "per_machine": {}, "state_counts": {}})
        monkeypatch.setattr(agent, "_maintenance_risk", lambda db: {"total_monitored": 0, "urgent": 0, "service_soon": 0, "watch": 0, "ok": 0, "urgent_machine_ids": []})
        monkeypatch.setattr(agent, "_inventory_health", lambda: {"status": "unavailable"})
        monkeypatch.setattr(agent, "_energy_today",    lambda: {"status": "ok", "shift_cost_usd": 22.4, "shift_carbon_kg": 215.0, "cheapest_hours": [], "avg_rate_usd_kwh": 0.04})

        result = agent.live(db)
        score = result["lights_out_score"]
        assert "score" in score
        assert "level" in score
        assert score["level"] in ("optimal", "healthy", "degraded", "critical")


# ---------------------------------------------------------------------------
# REST endpoint
# ---------------------------------------------------------------------------

class TestDashboardRouter:

    def test_live_requires_auth(self, client):
        r = client.get("/api/dashboard/live")
        assert r.status_code == 401

    def test_live_ok_when_authenticated(self, client):
        client.post("/api/auth/register", json={
            "email": "dash_user@example.com",
            "password": "testpass123",
            "name": "Dash User",
        })
        client.post("/api/auth/login", json={
            "email": "dash_user@example.com",
            "password": "testpass123",
        })
        r = client.get("/api/dashboard/live")
        assert r.status_code == 200

    def test_live_response_structure(self, client):
        client.post("/api/auth/register", json={
            "email": "dash_struct@example.com",
            "password": "testpass123",
            "name": "Dash Struct",
        })
        client.post("/api/auth/login", json={
            "email": "dash_struct@example.com",
            "password": "testpass123",
        })
        r = client.get("/api/dashboard/live")
        body = r.json()
        for key in ("collected_at", "lights_out_score", "open_exceptions",
                    "schedule_health", "machine_states", "maintenance_risk",
                    "inventory_health", "energy_today"):
            assert key in body, f"Missing top-level key: {key}"

    def test_live_score_in_range(self, client):
        client.post("/api/auth/register", json={
            "email": "dash_score@example.com",
            "password": "testpass123",
            "name": "Dash Score",
        })
        client.post("/api/auth/login", json={
            "email": "dash_score@example.com",
            "password": "testpass123",
        })
        r = client.get("/api/dashboard/live")
        score = r.json()["lights_out_score"]["score"]
        assert 0 <= score <= 100

    def test_live_energy_has_cheapest_hours(self, client):
        client.post("/api/auth/register", json={
            "email": "dash_energy@example.com",
            "password": "testpass123",
            "name": "Dash Energy",
        })
        client.post("/api/auth/login", json={
            "email": "dash_energy@example.com",
            "password": "testpass123",
        })
        r = client.get("/api/dashboard/live")
        energy = r.json()["energy_today"]
        assert energy["status"] == "ok"
        assert len(energy["cheapest_hours"]) == 4
