"""
Tests for /api/twin and /api/learning endpoints.

Covers:
  - GET /api/twin/accuracy returns accuracy structure (no auth)
  - GET /api/learning/setup-time-accuracy returns model status
  - GET /api/learning/calibration-report returns report structure

Uses the shared `client` fixture from conftest.py.
"""

import pytest


# ---------------------------------------------------------------------------
# /api/twin/accuracy
# ---------------------------------------------------------------------------

def test_twin_accuracy_ok(client):
    res = client.get("/api/twin/accuracy")
    assert res.status_code == 200
    data = res.json()
    # Should have at least one of these fields
    assert any(k in data for k in ("setup_mae_minutes", "message", "records_count", "model_status"))


def test_twin_accuracy_no_auth_required(client):
    """Twin accuracy is a monitoring endpoint — should not require auth."""
    res = client.get("/api/twin/accuracy")
    assert res.status_code != 401


# ---------------------------------------------------------------------------
# /api/learning/setup-time-accuracy
# ---------------------------------------------------------------------------

def test_learning_setup_time_accuracy_ok(client):
    res = client.get("/api/learning/setup-time-accuracy")
    assert res.status_code == 200
    data = res.json()
    # Untrained model should report fallback status
    assert any(k in data for k in ("trained", "status", "model_status", "fallback", "records_count"))


def test_learning_setup_time_accuracy_no_auth(client):
    res = client.get("/api/learning/setup-time-accuracy")
    assert res.status_code != 401


# ---------------------------------------------------------------------------
# /api/learning/calibration-report
# ---------------------------------------------------------------------------

def test_learning_calibration_report_ok(client):
    res = client.get("/api/learning/calibration-report")
    assert res.status_code == 200
    data = res.json()
    # Empty DB returns some kind of report structure (list or dict)
    assert data is not None


def test_learning_calibration_report_no_auth(client):
    res = client.get("/api/learning/calibration-report")
    assert res.status_code != 401
