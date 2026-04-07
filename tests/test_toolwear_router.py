"""
Tests for /api/toolwear router endpoints.

Covers:
  - POST /api/toolwear/tools — register a tool
  - GET /api/toolwear/tools — fleet status
  - GET /api/toolwear/tools/{id} — single tool status
  - POST /api/toolwear/readings — ingest sensor reading
  - GET /api/toolwear/readings/{id} — reading history
  - POST /api/toolwear/reset/{id} — reset after tool change
  - POST /api/toolwear/simulate/{id} — synthetic wear for demo
"""

import pytest


_TOOL = {
    "tool_id": "T-001",
    "machine_id": 1,
    "tool_type": "end_mill",
    "material": "carbide",
    "expected_life_minutes": 120,
}


# ---------------------------------------------------------------------------
# Register
# ---------------------------------------------------------------------------

def test_register_tool_ok(client):
    res = client.post("/api/toolwear/tools", json=_TOOL)
    assert res.status_code == 201
    data = res.json()
    assert data["tool_id"] == "T-001"
    assert data["alert_level"] == "GREEN"
    assert data["wear_score"] == 0.0


def test_register_tool_idempotent(client):
    """Registering same tool twice should not crash."""
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.post("/api/toolwear/tools", json=_TOOL)
    assert res.status_code == 201


# ---------------------------------------------------------------------------
# Fleet status
# ---------------------------------------------------------------------------

def test_list_tools_empty(client):
    res = client.get("/api/toolwear/tools")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_list_tools_includes_registered(client):
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.get("/api/toolwear/tools")
    assert res.status_code == 200
    tool_ids = [t["tool_id"] for t in res.json()]
    assert "T-001" in tool_ids


# ---------------------------------------------------------------------------
# Single tool
# ---------------------------------------------------------------------------

def test_get_tool_ok(client):
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.get("/api/toolwear/tools/T-001")
    assert res.status_code == 200
    assert res.json()["tool_id"] == "T-001"


def test_get_tool_not_found(client):
    res = client.get("/api/toolwear/tools/NONEXISTENT")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Readings
# ---------------------------------------------------------------------------

def test_ingest_reading_ok(client):
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.post("/api/toolwear/readings", json={
        "tool_id": "T-001",
        "reading": {
            "vibration_rms": 0.5,
            "vibration_peak_freq": 1200.0,
            "acoustic_rms": 0.3,
            "acoustic_peak_freq": 800.0,
            "spindle_load_pct": 40.0,
            "feed_rate_actual": 200.0,
        },
    })
    assert res.status_code == 200
    data = res.json()
    assert data["tool_id"] == "T-001"
    assert data["wear_score"] >= 0


def test_ingest_reading_unknown_tool(client):
    res = client.post("/api/toolwear/readings", json={
        "tool_id": "GHOST",
        "reading": {
            "vibration_rms": 0.5,
            "vibration_peak_freq": 1200.0,
            "acoustic_rms": 0.3,
            "acoustic_peak_freq": 800.0,
            "spindle_load_pct": 40.0,
            "feed_rate_actual": 200.0,
        },
    })
    assert res.status_code == 404


def test_get_readings_empty(client):
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.get("/api/toolwear/readings/T-001")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def test_reset_tool_ok(client):
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.post("/api/toolwear/reset/T-001")
    assert res.status_code == 200
    assert res.json()["wear_score"] == 0.0
    assert res.json()["alert_level"] == "GREEN"


def test_reset_tool_not_found(client):
    res = client.post("/api/toolwear/reset/NOPE")
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# Simulate
# ---------------------------------------------------------------------------

def test_simulate_wear_ok(client):
    client.post("/api/toolwear/tools", json=_TOOL)
    res = client.post("/api/toolwear/simulate/T-001?steps=20")
    assert res.status_code == 200
    data = res.json()
    assert data["tool_id"] == "T-001"
    assert len(data["wear_scores"]) == 20
    assert data["final_wear_score"] > 0
