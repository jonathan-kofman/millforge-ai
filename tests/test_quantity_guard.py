"""
Unit tests for quantity guard warnings in scheduler.
"""

import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.scheduler import check_order_warnings, Order


def test_large_quantity_steel_generates_warning():
    """Order with quantity 50,000 steel should generate warning about machine-hours."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    orders = [
        Order(
            order_id="ORD-001",
            material="steel",
            quantity=50000,
            dimensions="100x100x10mm",
            due_date=now + timedelta(hours=72),
            priority=5,
            complexity=1.0
        )
    ]

    warnings = check_order_warnings(orders)
    assert len(warnings) == 1
    assert "50000" in warnings[0]
    assert "machine-hours" in warnings[0]
    assert "ORD-001" in warnings[0]


def test_small_quantity_no_warning():
    """Order with quantity 9,999 should NOT generate warning."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    orders = [
        Order(
            order_id="ORD-002",
            material="steel",
            quantity=9999,
            dimensions="100x100x10mm",
            due_date=now + timedelta(hours=72),
            priority=5,
            complexity=1.0
        )
    ]

    warnings = check_order_warnings(orders)
    assert len(warnings) == 0


def test_multiple_orders_mixed_warnings():
    """Multiple orders: only large ones generate warnings."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    orders = [
        Order("ORD-001", "steel", 500, "100x100x10mm", now + timedelta(hours=24), priority=5),
        Order("ORD-002", "titanium", 30000, "100x100x10mm", now + timedelta(hours=48), priority=5),
        Order("ORD-003", "aluminum", 8000, "100x100x10mm", now + timedelta(hours=72), priority=5),
    ]

    warnings = check_order_warnings(orders)
    assert len(warnings) == 1
    assert "ORD-002" in warnings[0]
    assert "30000" in warnings[0]


def test_warning_includes_estimated_machine_hours():
    """Warning should include estimated machine-hours calculation."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    orders = [
        Order(
            order_id="ORD-001",
            material="titanium",
            quantity=30000,
            dimensions="100x100x10mm",
            due_date=now + timedelta(hours=120),
            priority=5,
            complexity=1.0
        )
    ]

    warnings = check_order_warnings(orders)
    assert len(warnings) == 1
    # Titanium throughput is 2.5 units/hour, so 30000 units = 12000 machine-hours
    assert "12000" in warnings[0]
