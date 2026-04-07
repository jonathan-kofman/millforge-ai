"""
Tests for /api/energy router endpoints.

Covers:
  - POST /api/energy/estimate — energy cost estimation
  - GET /api/energy/negative-pricing-windows — negative LMP detection
  - POST /api/energy/arbitrage-analysis — load shifting savings
  - GET /api/energy/carbon-intensity — grid carbon data
  - GET /api/energy/rates — 24-hour rate curve
  - POST /api/energy/scenario — 10-year NPV scenario
"""

import pytest
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Estimate
# ---------------------------------------------------------------------------

def test_energy_estimate_ok(client):
    res = client.post("/api/energy/estimate", json={
        "material": "steel",
        "duration_hours": 4.0,
        "start_time": datetime.now(timezone.utc).isoformat(),
    })
    assert res.status_code == 200
    data = res.json()
    assert data["estimated_kwh"] > 0
    assert data["estimated_cost_usd"] > 0
    assert "recommendation" in data
    assert "data_source" in data


def test_energy_estimate_missing_material(client):
    res = client.post("/api/energy/estimate", json={
        "duration_hours": 2.0,
        "start_time": datetime.now(timezone.utc).isoformat(),
    })
    assert res.status_code == 422


def test_energy_estimate_invalid_duration(client):
    res = client.post("/api/energy/estimate", json={
        "material": "aluminum",
        "duration_hours": -1,
        "start_time": datetime.now(timezone.utc).isoformat(),
    })
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Negative pricing windows
# ---------------------------------------------------------------------------

def test_negative_pricing_windows_ok(client):
    res = client.get("/api/energy/negative-pricing-windows")
    assert res.status_code == 200
    data = res.json()
    assert "windows" in data
    assert "total_windows" in data
    assert "recommendation" in data
    assert "data_source" in data
    assert isinstance(data["windows"], list)


# ---------------------------------------------------------------------------
# Arbitrage analysis
# ---------------------------------------------------------------------------

def test_arbitrage_analysis_ok(client):
    res = client.post("/api/energy/arbitrage-analysis", json={
        "daily_energy_kwh": 5000,
        "flexible_load_percent": 0.4,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["daily_savings_usd"] >= 0
    assert data["annual_savings_usd"] >= 0
    assert data["peak_rate_usd_per_kwh"] > 0
    assert data["off_peak_rate_usd_per_kwh"] >= 0
    assert "optimal_shift_hours" in data


def test_arbitrage_analysis_missing_fields(client):
    res = client.post("/api/energy/arbitrage-analysis", json={})
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# Carbon intensity
# ---------------------------------------------------------------------------

def test_carbon_intensity_ok(client):
    res = client.get("/api/energy/carbon-intensity")
    assert res.status_code == 200
    data = res.json()
    assert "carbon_intensity_gco2_per_kwh" in data
    assert data["carbon_intensity_gco2_per_kwh"] > 0
    assert "data_source" in data


# ---------------------------------------------------------------------------
# Hourly rates
# ---------------------------------------------------------------------------

def test_hourly_rates_ok(client):
    res = client.get("/api/energy/rates")
    assert res.status_code == 200
    data = res.json()
    assert "rates_usd_per_kwh" in data
    assert "hours" in data
    assert len(data["rates_usd_per_kwh"]) == 24
    assert len(data["hours"]) == 24


# ---------------------------------------------------------------------------
# Scenario NPV
# ---------------------------------------------------------------------------

def test_scenario_solar_ok(client):
    res = client.post("/api/energy/scenario", json={
        "scenario": "solar",
        "annual_energy_kwh": 1_000_000,
        "capex_usd": 500_000,
    })
    assert res.status_code == 200
    data = res.json()
    assert data["scenario"] == "solar"
    assert "npv_10yr_usd" in data
    assert "payback_years" in data
    assert data["lcoe_usd_per_kwh"] > 0


def test_scenario_grid_only_no_payback(client):
    res = client.post("/api/energy/scenario", json={
        "scenario": "grid_only",
        "annual_energy_kwh": 1_000_000,
        "capex_usd": 1,  # grid_only still requires > 0 for validation
    })
    assert res.status_code == 200
    data = res.json()
    assert data["scenario"] == "grid_only"
    assert data["payback_years"] is None


def test_scenario_invalid_type(client):
    res = client.post("/api/energy/scenario", json={
        "scenario": "perpetual_motion",
        "annual_energy_kwh": 100,
        "capex_usd": 0,
    })
    assert res.status_code == 422
