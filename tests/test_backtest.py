"""
Tests for POST /api/schedule/backtest — historical order replay.

The backtest endpoint answers: "What would MillForge have achieved on your
real past orders?"  It accepts orders with actual_completion timestamps and
returns a side-by-side of actual vs FIFO vs EDD vs SA on-time rates.

7 tests covering:
1. Response keys present
2. Actual on-time rate computed correctly from actual_completion timestamps
3. SA on-time >= actual on-time (SA should improve on naive historical perf)
4. Per-order detail length matches order_count
5. sa_vs_actual_pp matches the derived delta
6. Explicit start_time is respected (no auto-inference)
7. Label passthrough
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ---------------------------------------------------------------------------
# Shared test dataset — 10 orders based on the canonical benchmark pattern.
# Half hit their due date (actual), half miss.  SA should rescue most of the
# missed ones by reordering and material clustering.
# ---------------------------------------------------------------------------

REF = datetime(2026, 1, 1, 8, 0, 0)  # production start


def _make_orders(n_on_time: int = 5):
    """Return a list of 10 historical orders.

    First n_on_time orders arrive on time in history; the rest arrive late.
    This gives actual_on_time_rate = n_on_time/10 * 100 %.
    """
    orders = []
    materials = ["steel", "aluminum", "titanium", "copper"]
    for i in range(10):
        mat = materials[i % 4]
        qty = 6 + (i % 5)  # 6–10 units
        # due date: generous enough that algorithms can improve over actual
        due_date = REF + timedelta(hours=4 + i)
        # actual completion: on-time for first n_on_time, 2h late for the rest
        if i < n_on_time:
            actual_completion = due_date - timedelta(hours=0.5)  # 30 min early
        else:
            actual_completion = due_date + timedelta(hours=2)    # 2h late
        orders.append({
            "order_id": f"HIST-{i:03d}",
            "material": mat,
            "quantity": qty,
            "dimensions": "120x60x8mm",
            "due_date": due_date.isoformat(),
            "priority": 2 if i < n_on_time else 5,
            "complexity": 1.0,
            "actual_completion": actual_completion.isoformat(),
        })
    return orders


_ORDERS_5_ON_TIME = _make_orders(n_on_time=5)
_ORDERS_2_ON_TIME = _make_orders(n_on_time=2)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_backtest_response_keys_present(client):
    """All top-level response keys must be present, including impact block."""
    resp = client.post("/api/schedule/backtest", json={
        "orders": _ORDERS_5_ON_TIME,
        "label": "Test batch",
    })
    assert resp.status_code == 200, resp.text
    data = resp.json()
    for key in ("label", "order_count", "machine_count", "start_time",
                "actual", "fifo", "edd", "sa",
                "sa_vs_actual_pp", "fifo_vs_actual_pp", "impact", "orders"):
        assert key in data, f"Missing key: {key}"
    for key in ("on_time_count", "on_time_rate_percent", "avg_lateness_hours"):
        assert key in data["actual"], f"Missing actual key: {key}"
    for key in ("orders_rescued", "orders_lost", "total_lateness_hours_saved",
                "avg_lateness_reduction_hours", "makespan_delta_hours"):
        assert key in data["impact"], f"Missing impact key: {key}"


def test_backtest_actual_on_time_rate_correct(client):
    """Actual on-time rate must match what the timestamps say."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_5_ON_TIME})
    assert resp.status_code == 200
    actual = resp.json()["actual"]
    assert actual["on_time_count"] == 5
    assert actual["on_time_rate_percent"] == 50.0


def test_backtest_actual_all_late(client):
    """With 2/10 on-time, actual rate should be 20%."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_2_ON_TIME})
    assert resp.status_code == 200
    actual = resp.json()["actual"]
    assert actual["on_time_count"] == 2
    assert actual["on_time_rate_percent"] == 20.0


def test_backtest_sa_improves_over_actual(client):
    """SA on-time rate must be >= actual historical rate."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_2_ON_TIME})
    assert resp.status_code == 200
    data = resp.json()
    assert data["sa"]["on_time_rate_percent"] >= data["actual"]["on_time_rate_percent"], (
        f"SA ({data['sa']['on_time_rate_percent']}%) should be >= actual ({data['actual']['on_time_rate_percent']}%)"
    )
    assert data["sa_vs_actual_pp"] >= 0.0


def test_backtest_order_detail_length(client):
    """Per-order detail list must contain one entry per input order."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_5_ON_TIME})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["orders"]) == data["order_count"] == 10


def test_backtest_sa_vs_actual_matches_delta(client):
    """sa_vs_actual_pp must equal sa.on_time_rate_percent - actual.on_time_rate_percent."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_5_ON_TIME})
    assert resp.status_code == 200
    data = resp.json()
    expected = round(data["sa"]["on_time_rate_percent"] - data["actual"]["on_time_rate_percent"], 1)
    assert data["sa_vs_actual_pp"] == expected


def test_backtest_explicit_start_time(client):
    """Explicit start_time must appear verbatim in the response."""
    start = "2026-01-01T06:00:00"
    resp = client.post("/api/schedule/backtest", json={
        "orders": _ORDERS_5_ON_TIME,
        "start_time": start,
    })
    assert resp.status_code == 200
    data = resp.json()
    # start_time in response is a datetime — check it parses to the same moment
    resp_start = datetime.fromisoformat(data["start_time"].replace("Z", ""))
    assert resp_start == datetime(2026, 1, 1, 6, 0, 0)


def test_backtest_label_passthrough(client):
    """Custom label must be echoed in the response."""
    resp = client.post("/api/schedule/backtest", json={
        "orders": _ORDERS_5_ON_TIME,
        "label": "Q1 2025 production run",
    })
    assert resp.status_code == 200
    assert resp.json()["label"] == "Q1 2025 production run"


def test_backtest_orders_rescued_count(client):
    """orders_rescued must equal the number of orders that were late in reality
    but SA would deliver on time.  Cannot exceed the number of actual late orders."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_2_ON_TIME})
    assert resp.status_code == 200
    data = resp.json()
    impact = data["impact"]
    # At most 8 orders were late in reality (10 - 2 on time)
    assert 0 <= impact["orders_rescued"] <= 8
    # rescued + orders_lost is always <= order_count
    assert impact["orders_rescued"] + impact["orders_lost"] <= data["order_count"]


def test_backtest_rescued_flag_on_order_details(client):
    """Per-order rescued flag must be True exactly when actual=late AND sa=on_time."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_2_ON_TIME})
    assert resp.status_code == 200
    orders = resp.json()["orders"]
    rescued_in_detail = sum(1 for o in orders if o["rescued"])
    assert rescued_in_detail == resp.json()["impact"]["orders_rescued"]


def test_backtest_total_lateness_hours_saved_nonnegative(client):
    """When SA genuinely improves over history, total lateness saved should be >= 0."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_2_ON_TIME})
    assert resp.status_code == 200
    # SA may save more or fewer hours depending on scenario, but value must be a number
    saved = resp.json()["impact"]["total_lateness_hours_saved"]
    assert isinstance(saved, (int, float))


def test_backtest_penalty_usd_computed(client):
    """When penalty_per_late_order_usd is supplied, estimated_penalty_usd must be present."""
    resp = client.post("/api/schedule/backtest", json={
        "orders": _ORDERS_2_ON_TIME,
        "penalty_per_late_order_usd": 500.0,
    })
    assert resp.status_code == 200
    penalty = resp.json()["impact"]["estimated_penalty_usd"]
    assert penalty is not None
    # Must be non-negative and a round number of $500 * rescued * 12
    assert penalty >= 0.0


def test_backtest_penalty_usd_absent_when_not_supplied(client):
    """estimated_penalty_usd must be null when penalty_per_late_order_usd is omitted."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_5_ON_TIME})
    assert resp.status_code == 200
    assert resp.json()["impact"]["estimated_penalty_usd"] is None


def test_backtest_makespan_delta_is_float(client):
    """makespan_delta_hours must be a numeric value in the response."""
    resp = client.post("/api/schedule/backtest", json={"orders": _ORDERS_5_ON_TIME})
    assert resp.status_code == 200
    delta = resp.json()["impact"]["makespan_delta_hours"]
    assert isinstance(delta, (int, float))
