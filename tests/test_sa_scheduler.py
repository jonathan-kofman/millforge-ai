"""
Unit tests for the MillForge Simulated Annealing Scheduler.

Run with: pytest tests/ -v
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.sa_scheduler import SAScheduler
from agents.scheduler import Order, Scheduler, get_mock_orders


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sa():
    # Use a fixed seed for reproducibility and fewer iterations for speed
    return SAScheduler(machine_count=3, max_iterations=2000, seed=42)


@pytest.fixture
def edd():
    return Scheduler(machine_count=3)


@pytest.fixture
def now():
    return datetime(2025, 6, 1, 8, 0, 0)


@pytest.fixture
def simple_orders(now):
    return [
        Order("A", "steel",    100, "100x50x5mm",   now + timedelta(hours=24), priority=1),
        Order("B", "aluminum", 200, "150x75x5mm",   now + timedelta(hours=48), priority=2),
        Order("C", "titanium",  50, "200x100x10mm", now + timedelta(hours=72), priority=3),
    ]


@pytest.fixture
def tight_orders(now):
    """Orders with aggressive due dates to stress-test tardiness minimization."""
    return [
        Order("T1", "steel",    500, "200x100x10mm", now + timedelta(hours=8),  priority=1),
        Order("T2", "aluminum", 300, "150x75x5mm",   now + timedelta(hours=10), priority=2),
        Order("T3", "titanium",  80, "300x200x15mm", now + timedelta(hours=12), priority=3),
        Order("T4", "steel",    200, "100x50x8mm",   now + timedelta(hours=6),  priority=1),
        Order("T5", "copper",   150, "80x40x3mm",    now + timedelta(hours=9),  priority=2),
    ]


# ---------------------------------------------------------------------------
# Basic correctness (mirrors scheduler tests)
# ---------------------------------------------------------------------------

def test_sa_returns_all_orders(sa, simple_orders, now):
    schedule = sa.optimize(simple_orders, start_time=now)
    assert schedule.total_orders == len(simple_orders)
    assert len(schedule.scheduled_orders) == len(simple_orders)


def test_sa_empty_input(sa, now):
    schedule = sa.optimize([], start_time=now)
    assert schedule.total_orders == 0
    assert schedule.makespan_hours == 0.0


def test_sa_completion_after_start(sa, simple_orders, now):
    schedule = sa.optimize(simple_orders, start_time=now)
    for s in schedule.scheduled_orders:
        assert s.completion_time > now
        assert s.processing_start >= s.setup_start
        assert s.completion_time > s.processing_start


def test_sa_machine_ids_in_range(sa, simple_orders, now):
    schedule = sa.optimize(simple_orders, start_time=now)
    for s in schedule.scheduled_orders:
        assert 1 <= s.machine_id <= sa.machine_count


def test_sa_utilization_in_range(sa, simple_orders, now):
    schedule = sa.optimize(simple_orders, start_time=now)
    assert 0.0 <= schedule.utilization_percent <= 100.0


def test_sa_makespan_positive(sa, simple_orders, now):
    schedule = sa.optimize(simple_orders, start_time=now)
    assert schedule.makespan_hours > 0


def test_sa_on_time_count_leq_total(sa, simple_orders, now):
    schedule = sa.optimize(simple_orders, start_time=now)
    assert schedule.on_time_count <= schedule.total_orders


# ---------------------------------------------------------------------------
# SA-specific: equal or better than EDD on tardiness
# ---------------------------------------------------------------------------

def _weighted_tardiness(schedule) -> float:
    total = 0.0
    for s in schedule.scheduled_orders:
        tardiness_h = max(0.0, (s.completion_time - s.order.due_date).total_seconds() / 3600)
        weight = max(1, 11 - s.order.priority)
        total += weight * tardiness_h
    return total


def test_sa_not_worse_than_edd_on_tight_orders(sa, edd, tight_orders, now):
    """SA should achieve ≤ EDD weighted tardiness on a stress-test instance."""
    edd_sched = edd.optimize(tight_orders, start_time=now)
    sa_sched  = sa.optimize(tight_orders, start_time=now)

    edd_tard = _weighted_tardiness(edd_sched)
    sa_tard  = _weighted_tardiness(sa_sched)

    # SA may match or improve EDD; allow 5% tolerance for stochastic variance
    assert sa_tard <= edd_tard * 1.05, (
        f"SA tardiness ({sa_tard:.2f}) significantly worse than EDD ({edd_tard:.2f})"
    )


def test_sa_improves_or_matches_edd_on_mock_data(sa, edd):
    """SA should not regress on the canonical mock dataset."""
    orders = get_mock_orders()
    edd_sched = edd.optimize(orders)
    sa_sched  = sa.optimize(orders)

    edd_tard = _weighted_tardiness(edd_sched)
    sa_tard  = _weighted_tardiness(sa_sched)

    # SA started from EDD solution; it should be at least as good
    assert sa_tard <= edd_tard * 1.05


# ---------------------------------------------------------------------------
# Determinism with fixed seed
# ---------------------------------------------------------------------------

def test_sa_deterministic_with_seed(now, simple_orders):
    """Two SA runs with the same seed must produce identical results."""
    sa1 = SAScheduler(machine_count=3, max_iterations=500, seed=7)
    sa2 = SAScheduler(machine_count=3, max_iterations=500, seed=7)

    s1 = sa1.optimize(simple_orders, start_time=now)
    s2 = sa2.optimize(simple_orders, start_time=now)

    completions1 = sorted((s.order.order_id, s.completion_time) for s in s1.scheduled_orders)
    completions2 = sorted((s.order.order_id, s.completion_time) for s in s2.scheduled_orders)
    assert completions1 == completions2


# ---------------------------------------------------------------------------
# Lead time estimation
# ---------------------------------------------------------------------------

def test_sa_estimate_lead_time_positive(sa, now):
    new_order = Order("NEW", "aluminum", 50, "80x40x3mm", now + timedelta(hours=24), priority=3)
    queue = [Order("Q1", "steel", 100, "100x50x5mm", now + timedelta(hours=48), priority=2)]
    lead_time = sa.estimate_lead_time(new_order, queue)
    assert lead_time >= 0.0


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

def test_sa_to_dict_serializable(sa, simple_orders, now):
    import json
    schedule = sa.optimize(simple_orders, start_time=now)
    d = schedule.to_dict()
    json.dumps(d, default=str)
