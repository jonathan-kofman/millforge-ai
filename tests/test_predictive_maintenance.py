"""
Tests for PredictiveMaintenanceAgent and GET /api/maintenance/signals endpoints.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from agents.predictive_maintenance import PredictiveMaintenanceAgent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log_row(machine_id=1, from_state="IDLE", to_state="SETUP", hours_ago=1.0, job_id=None):
    row = MagicMock()
    row.machine_id = machine_id
    row.from_state = from_state
    row.to_state = to_state
    row.job_id = job_id
    row.occurred_at = _now() - timedelta(hours=hours_ago)
    return row


def _fault(machine_id=1, hours_ago=1.0):
    return _log_row(machine_id=machine_id, from_state="RUNNING", to_state="FAULT", hours_ago=hours_ago)


def _recover(machine_id=1, hours_ago=0.9):
    """Transition from FAULT → IDLE (operator reset)."""
    return _log_row(machine_id=machine_id, from_state="FAULT", to_state="IDLE", hours_ago=hours_ago)


def _make_db(rows=None):
    db = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.order_by.return_value = mock_q
    mock_q.all.return_value = rows or []
    db.query.return_value = mock_q
    return db


# ---------------------------------------------------------------------------
# Agent — empty DB
# ---------------------------------------------------------------------------

def test_signals_empty_db_returns_empty_list():
    agent = PredictiveMaintenanceAgent()
    db = _make_db()
    result = agent.signals(db)
    assert result == []


def test_signals_empty_db_with_machine_ids_returns_safe_defaults():
    agent = PredictiveMaintenanceAgent()
    db = _make_db()
    result = agent.signals(db, machine_ids=[1, 2])
    assert len(result) == 2
    for sig in result:
        assert sig["risk_level"] == "ok"
        assert sig["risk_score"] == 0
        assert sig["fault_count_24h"] == 0


# ---------------------------------------------------------------------------
# Agent — risk scoring
# ---------------------------------------------------------------------------

def test_no_faults_is_ok():
    agent = PredictiveMaintenanceAgent()
    # Only normal transitions, no FAULT
    rows = [
        _log_row(1, "IDLE", "SETUP", hours_ago=2),
        _log_row(1, "SETUP", "RUNNING", hours_ago=1.5),
        _log_row(1, "RUNNING", "COOLDOWN", hours_ago=0.5),
    ]
    db = _make_db(rows)
    result = agent.signals(db)
    assert result[0]["risk_level"] == "ok"
    assert result[0]["fault_count_24h"] == 0


def test_one_fault_in_24h_is_watch():
    agent = PredictiveMaintenanceAgent()
    rows = [_fault(1, hours_ago=2)]
    db = _make_db(rows)
    result = agent.signals(db)
    sig = result[0]
    assert sig["fault_count_24h"] == 1
    assert sig["risk_level"] == "watch"
    assert sig["risk_score"] >= 30


def test_two_faults_in_24h_is_service_soon():
    agent = PredictiveMaintenanceAgent()
    # Faults 14h apart — MTBF=14h, above both critical (4h) and low (12h) thresholds
    rows = [_fault(1, hours_ago=15), _fault(1, hours_ago=1)]
    db = _make_db(rows)
    result = agent.signals(db)
    sig = result[0]
    assert sig["fault_count_24h"] == 2
    assert sig["risk_level"] == "service_soon"
    assert sig["risk_score"] >= 60


def test_three_faults_in_24h_is_urgent():
    agent = PredictiveMaintenanceAgent()
    rows = [_fault(1, hours_ago=5), _fault(1, hours_ago=2), _fault(1, hours_ago=1)]
    db = _make_db(rows)
    result = agent.signals(db)
    sig = result[0]
    assert sig["fault_count_24h"] == 3
    assert sig["risk_level"] == "urgent"
    assert sig["risk_score"] >= 80


def test_fault_older_than_24h_counted_in_7d_but_not_24h():
    agent = PredictiveMaintenanceAgent()
    # Fault 30 hours ago — outside 24h window but inside 7d window
    rows = [_fault(1, hours_ago=30)]
    db = _make_db(rows)
    result = agent.signals(db)
    sig = result[0]
    assert sig["fault_count_24h"] == 0
    assert sig["fault_count_7d"] == 1
    assert sig["risk_level"] == "ok"


# ---------------------------------------------------------------------------
# Agent — MTBF
# ---------------------------------------------------------------------------

def test_mtbf_none_with_single_fault():
    agent = PredictiveMaintenanceAgent()
    rows = [_fault(1, hours_ago=5)]
    db = _make_db(rows)
    result = agent.signals(db)
    assert result[0]["mtbf_hours"] is None


def test_mtbf_computed_with_two_faults():
    agent = PredictiveMaintenanceAgent()
    # Faults 10h apart
    rows = [_fault(1, hours_ago=10), _fault(1, hours_ago=0)]
    db = _make_db(rows)
    result = agent.signals(db)
    mtbf = result[0]["mtbf_hours"]
    assert mtbf is not None
    assert abs(mtbf - 10.0) < 0.5


def test_low_mtbf_raises_risk_score():
    """MTBF < 4h (critical) should add +30 to base score."""
    agent = PredictiveMaintenanceAgent()
    # 1 fault in 24h (base=35) + MTBF=2h (critical → +30) → score ≥ 60
    rows = [_fault(1, hours_ago=2), _fault(1, hours_ago=0)]
    db = _make_db(rows)
    result = agent.signals(db)
    sig = result[0]
    assert sig["mtbf_hours"] is not None
    assert sig["mtbf_hours"] < 4.0
    assert sig["risk_score"] >= 60


# ---------------------------------------------------------------------------
# Agent — MTTR
# ---------------------------------------------------------------------------

def test_mttr_none_with_no_resolved_faults():
    agent = PredictiveMaintenanceAgent()
    # Fault but no recovery yet
    rows = [_fault(1, hours_ago=1)]
    db = _make_db(rows)
    result = agent.signals(db)
    assert result[0]["mttr_minutes"] is None


def test_mttr_computed_for_resolved_fault():
    agent = PredictiveMaintenanceAgent()
    # Fault at t-60min, recovered at t-0 → MTTR = 60 min
    rows = [
        _fault(1, hours_ago=1.0),
        _recover(1, hours_ago=0.0),
    ]
    db = _make_db(rows)
    result = agent.signals(db)
    mttr = result[0]["mttr_minutes"]
    assert mttr is not None
    assert abs(mttr - 60.0) < 2.0


# ---------------------------------------------------------------------------
# Agent — multi-machine
# ---------------------------------------------------------------------------

def test_signals_isolates_per_machine():
    agent = PredictiveMaintenanceAgent()
    rows = [
        _fault(machine_id=1, hours_ago=15),  # 14h apart → MTBF=14h, above thresholds
        _fault(machine_id=1, hours_ago=1),
        # Machine 2 has no faults
        _log_row(machine_id=2, from_state="IDLE", to_state="SETUP", hours_ago=1),
    ]
    db = _make_db(rows)
    result = agent.signals(db)
    by_id = {s["machine_id"]: s for s in result}
    assert by_id[1]["fault_count_24h"] == 2
    assert by_id[2]["fault_count_24h"] == 0
    assert by_id[1]["risk_level"] == "service_soon"
    assert by_id[2]["risk_level"] == "ok"


def test_last_fault_at_populated():
    agent = PredictiveMaintenanceAgent()
    rows = [_fault(1, hours_ago=2)]
    db = _make_db(rows)
    result = agent.signals(db)
    assert result[0]["last_fault_at"] is not None
    # Should be parseable ISO datetime
    datetime.fromisoformat(result[0]["last_fault_at"])


def test_recommendation_text_present():
    agent = PredictiveMaintenanceAgent()
    rows = [_fault(1, hours_ago=2), _fault(1, hours_ago=1), _fault(1, hours_ago=0.5)]
    db = _make_db(rows)
    result = agent.signals(db)
    rec = result[0]["recommendation"]
    assert isinstance(rec, str)
    assert len(rec) > 10


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

def test_get_signals_requires_auth(client):
    resp = client.get("/api/maintenance/signals")
    assert resp.status_code == 401


def test_get_signals_ok_when_authenticated(client):
    client.post("/api/auth/register", json={
        "email": "maint@example.com", "password": "testpass123", "name": "Maint"
    })
    client.post("/api/auth/login", json={"email": "maint@example.com", "password": "testpass123"})

    resp = client.get("/api/maintenance/signals")
    assert resp.status_code == 200
    body = resp.json()
    assert "machines" in body
    assert "machine_count" in body
    assert "lookback_hours" in body


def test_get_signals_empty_history_returns_empty_machines(client):
    client.post("/api/auth/register", json={
        "email": "maint2@example.com", "password": "testpass123", "name": "Maint2"
    })
    client.post("/api/auth/login", json={"email": "maint2@example.com", "password": "testpass123"})

    resp = client.get("/api/maintenance/signals")
    body = resp.json()
    assert body["machines"] == []
    assert body["machine_count"] == 0


def test_get_signal_for_machine_requires_auth(client):
    resp = client.get("/api/maintenance/signals/1")
    assert resp.status_code == 401


def test_get_signal_for_machine_ok(client):
    client.post("/api/auth/register", json={
        "email": "maint3@example.com", "password": "testpass123", "name": "Maint3"
    })
    client.post("/api/auth/login", json={"email": "maint3@example.com", "password": "testpass123"})

    resp = client.get("/api/maintenance/signals/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["machine_id"] == 1
    assert "risk_level" in body
    assert "risk_score" in body
    assert "recommendation" in body


def test_get_signals_lookback_param_respected(client):
    client.post("/api/auth/register", json={
        "email": "maint4@example.com", "password": "testpass123", "name": "Maint4"
    })
    client.post("/api/auth/login", json={"email": "maint4@example.com", "password": "testpass123"})

    resp = client.get("/api/maintenance/signals?lookback_hours=24")
    assert resp.status_code == 200
    assert resp.json()["lookback_hours"] == 24
