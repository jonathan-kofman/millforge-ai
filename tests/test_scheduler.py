"""
Unit tests for the MillForge Scheduler agent.

Run with: pytest tests/ -v
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

# Make the backend package importable from the tests directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.scheduler import Scheduler, Order, get_mock_orders


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def scheduler():
    return Scheduler(machine_count=3)


@pytest.fixture
def now():
    return datetime(2025, 6, 1, 8, 0, 0)  # fixed time for deterministic tests


@pytest.fixture
def simple_orders(now):
    return [
        Order("A", "steel",    100, "100x50x5mm",  now + timedelta(hours=24), priority=1),
        Order("B", "aluminum", 200, "150x75x5mm",  now + timedelta(hours=48), priority=2),
        Order("C", "titanium",  50, "200x100x10mm", now + timedelta(hours=72), priority=3),
    ]


# ---------------------------------------------------------------------------
# Basic correctness
# ---------------------------------------------------------------------------

def test_schedule_returns_all_orders(scheduler, simple_orders, now):
    schedule = scheduler.optimize(simple_orders, start_time=now)
    assert schedule.total_orders == len(simple_orders)
    assert len(schedule.scheduled_orders) == len(simple_orders)


def test_schedule_empty_input(scheduler, now):
    schedule = scheduler.optimize([], start_time=now)
    assert schedule.total_orders == 0
    assert schedule.makespan_hours == 0.0


def test_completion_after_start(scheduler, simple_orders, now):
    schedule = scheduler.optimize(simple_orders, start_time=now)
    for s in schedule.scheduled_orders:
        assert s.completion_time > now
        assert s.processing_start >= s.setup_start
        assert s.completion_time > s.processing_start


def test_machine_ids_in_range(scheduler, simple_orders, now):
    schedule = scheduler.optimize(simple_orders, start_time=now)
    for s in schedule.scheduled_orders:
        assert 1 <= s.machine_id <= scheduler.machine_count


# ---------------------------------------------------------------------------
# EDD ordering: highest-priority (earliest due) order should finish first
# ---------------------------------------------------------------------------

def test_edd_ordering_respects_due_dates(scheduler, now):
    """The order with the earliest due date should start (and typically finish) first."""
    urgent = Order("URGENT", "steel", 10, "50x50x5mm", now + timedelta(hours=4),  priority=1)
    normal = Order("NORMAL", "steel", 10, "50x50x5mm", now + timedelta(hours=48), priority=5)

    schedule = scheduler.optimize([normal, urgent], start_time=now)  # deliberately reversed input

    scheduled_by_id = {s.order.order_id: s for s in schedule.scheduled_orders}
    # URGENT should start before or at the same time as NORMAL
    assert scheduled_by_id["URGENT"].setup_start <= scheduled_by_id["NORMAL"].setup_start


# ---------------------------------------------------------------------------
# Setup times
# ---------------------------------------------------------------------------

def test_setup_time_same_material(scheduler):
    assert scheduler._get_setup_time("steel", "steel") == 15


def test_setup_time_cross_material(scheduler):
    assert scheduler._get_setup_time("steel", "titanium") == 90


def test_setup_time_unknown_material(scheduler):
    # Unknown material pairs fall back to BASE_SETUP_MINUTES
    from agents.scheduler import BASE_SETUP_MINUTES
    assert scheduler._get_setup_time("unobtanium", "vibranium") == BASE_SETUP_MINUTES


def test_initial_setup_uses_base(scheduler):
    from agents.scheduler import BASE_SETUP_MINUTES
    assert scheduler._get_setup_time(None, "steel") == BASE_SETUP_MINUTES


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_utilization_between_0_and_100(scheduler, simple_orders, now):
    schedule = scheduler.optimize(simple_orders, start_time=now)
    assert 0.0 <= schedule.utilization_percent <= 100.0


def test_makespan_positive(scheduler, simple_orders, now):
    schedule = scheduler.optimize(simple_orders, start_time=now)
    assert schedule.makespan_hours > 0


def test_on_time_count_leq_total(scheduler, simple_orders, now):
    schedule = scheduler.optimize(simple_orders, start_time=now)
    assert schedule.on_time_count <= schedule.total_orders


# ---------------------------------------------------------------------------
# Mock data smoke test
# ---------------------------------------------------------------------------

def test_mock_orders_schedule_runs(scheduler):
    orders = get_mock_orders()
    schedule = scheduler.optimize(orders)
    assert schedule.total_orders == len(orders)
    assert schedule.makespan_hours > 0


# ---------------------------------------------------------------------------
# Lead time estimation
# ---------------------------------------------------------------------------

def test_estimate_lead_time_positive(scheduler, now):
    new_order = Order("NEW", "aluminum", 50, "80x40x3mm", now + timedelta(hours=24), priority=3)
    queue = [
        Order("Q1", "steel", 100, "100x50x5mm", now + timedelta(hours=48), priority=2),
    ]
    lead_time = scheduler.estimate_lead_time(new_order, queue)
    assert lead_time >= 0.0


def test_to_dict_serializable(scheduler, simple_orders, now):
    """Schedule.to_dict() must produce JSON-safe types."""
    import json
    schedule = scheduler.optimize(simple_orders, start_time=now)
    d = schedule.to_dict()
    # Should not raise
    json.dumps(d, default=str)


# ---------------------------------------------------------------------------
# Validation loop tests
# ---------------------------------------------------------------------------

class TestSchedulerValidation:

    def test_no_validation_failures_on_valid_schedule(self, scheduler, simple_orders, now):
        """Normal schedule produces no validation failures."""
        schedule = scheduler.optimize(simple_orders, start_time=now)
        assert schedule.validation_failures == []

    def test_validation_catches_wrong_total_orders(self, scheduler, simple_orders, now, monkeypatch):
        """_validate_schedule catches total_orders mismatch."""
        from agents.scheduler import Schedule

        original_do = scheduler._do_optimize

        def bad_do(*a, **kw):
            s = original_do(*a, **kw)
            # Corrupt total_orders so validation fails every attempt
            s.total_orders = 0
            return s

        monkeypatch.setattr(scheduler, "_do_optimize", bad_do)
        schedule = scheduler.optimize(simple_orders, start_time=now)
        assert len(schedule.validation_failures) > 0
        assert any("total_orders" in f for f in schedule.validation_failures)

    def test_validation_catches_utilization_out_of_range(self, scheduler, simple_orders, now, monkeypatch):
        """_validate_schedule catches utilization_percent > 100."""
        original_do = scheduler._do_optimize

        def bad_do(*a, **kw):
            s = original_do(*a, **kw)
            s.utilization_percent = 150.0   # invalid
            return s

        monkeypatch.setattr(scheduler, "_do_optimize", bad_do)
        schedule = scheduler.optimize(simple_orders, start_time=now)
        assert len(schedule.validation_failures) > 0
        assert any("utilization_percent" in f for f in schedule.validation_failures)

    def test_retry_stops_on_first_valid(self, scheduler, simple_orders, now, monkeypatch):
        """Stops retrying once a valid schedule is returned."""
        call_count = {"n": 0}
        original_do = scheduler._do_optimize

        def side_effect(*a, **kw):
            call_count["n"] += 1
            s = original_do(*a, **kw)
            if call_count["n"] == 1:
                s.total_orders = 0   # bad first attempt
            return s

        monkeypatch.setattr(scheduler, "_do_optimize", side_effect)
        schedule = scheduler.optimize(simple_orders, start_time=now)
        assert call_count["n"] == 2
        assert schedule.validation_failures == []
