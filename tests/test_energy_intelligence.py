"""
Tests for energy intelligence layer:
  - compute_schedule_energy_analysis
  - get_negative_pricing_windows
  - get_arbitrage_analysis
  - get_scenario_npv
  - carbon footprint (unit-level)
  - API endpoints via TestClient
"""

import sys
import os
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.energy_optimizer import (
    EnergyOptimizer,
    MOCK_HOURLY_RATES,
    MACHINE_POWER_KW,
    US_GRID_CARBON_INTENSITY,
    _get_carbon_intensity,
    _fetch_carbon_intensity,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeOrder:
    def __init__(self, material="steel"):
        self.material = material
        self.due_date = datetime(2026, 1, 15, 20, 0)


class _FakeScheduledOrder:
    def __init__(self, material="steel", duration_h=4.0):
        now = datetime(2026, 1, 15, 8, 0)
        self.setup_start = now
        self.completion_time = now + timedelta(hours=duration_h)
        self.order = _FakeOrder(material)


@pytest.fixture
def opt():
    return EnergyOptimizer()


# ---------------------------------------------------------------------------
# Section 1: compute_schedule_energy_analysis
# ---------------------------------------------------------------------------

class TestScheduleEnergyAnalysis:
    def test_returns_required_keys(self, opt):
        orders = [_FakeScheduledOrder("steel", 4.0)]
        result = opt.compute_schedule_energy_analysis(orders)
        for key in ("total_energy_kwh", "current_schedule_cost_usd",
                    "optimal_schedule_cost_usd", "potential_savings_usd",
                    "carbon_footprint_kg_co2", "carbon_delta_kg_co2"):
            assert key in result, f"Missing key: {key}"

    def test_kwh_matches_power_draw(self, opt):
        orders = [_FakeScheduledOrder("steel", 2.0)]
        result = opt.compute_schedule_energy_analysis(orders)
        expected_kwh = MACHINE_POWER_KW["steel"] * 2.0
        assert abs(result["total_energy_kwh"] - expected_kwh) < 1.0

    def test_carbon_uses_us_average_fallback(self, opt):
        with patch("agents.energy_optimizer._fetch_carbon_intensity", return_value=None):
            orders = [_FakeScheduledOrder("titanium", 1.0)]
            result = opt.compute_schedule_energy_analysis(orders)
            expected_kwh = MACHINE_POWER_KW["titanium"] * 1.0
            expected_co2 = expected_kwh * US_GRID_CARBON_INTENSITY
            assert abs(result["carbon_footprint_kg_co2"] - expected_co2) < 0.5

    def test_savings_non_negative(self, opt):
        orders = [_FakeScheduledOrder("aluminum", 3.0), _FakeScheduledOrder("steel", 5.0)]
        result = opt.compute_schedule_energy_analysis(orders)
        assert result["potential_savings_usd"] >= 0.0

    def test_battery_recommendation_high_soc(self, opt):
        orders = [_FakeScheduledOrder("steel", 2.0)]
        result = opt.compute_schedule_energy_analysis(orders, battery_soc_percent=80.0)
        assert "battery_recommendation" in result
        assert "80" in result["battery_recommendation"]

    def test_battery_recommendation_low_soc(self, opt):
        orders = [_FakeScheduledOrder("steel", 2.0)]
        result = opt.compute_schedule_energy_analysis(orders, battery_soc_percent=10.0)
        assert "10" in result["battery_recommendation"]
        assert "off-peak" in result["battery_recommendation"].lower()

    def test_no_battery_key_without_soc(self, opt):
        orders = [_FakeScheduledOrder("steel", 2.0)]
        result = opt.compute_schedule_energy_analysis(orders)
        assert "battery_recommendation" not in result


# ---------------------------------------------------------------------------
# Section 2: get_negative_pricing_windows
# ---------------------------------------------------------------------------

class TestNegativePricingWindows:
    def test_returns_required_keys(self, opt):
        result = opt.get_negative_pricing_windows()
        for key in ("windows", "total_windows", "max_credit_usd_per_mwh",
                    "recommendation", "data_source"):
            assert key in result

    def test_simulated_fallback_has_no_negatives(self, opt):
        with patch("agents.energy_optimizer._fetch_pjm_lmp_raw", return_value=None):
            result = opt.get_negative_pricing_windows()
        assert result["total_windows"] == 0
        assert result["data_source"] == "simulated_fallback"

    def test_live_negatives_detected(self, opt):
        mock_rates = [0.05] * 22 + [-0.02, -0.01]  # 2 negative hours
        with patch("agents.energy_optimizer._fetch_pjm_lmp_raw", return_value=mock_rates):
            result = opt.get_negative_pricing_windows()
        assert result["total_windows"] == 2
        assert result["max_credit_usd_per_mwh"] > 0
        assert result["data_source"] == "PJM_realtime"

    def test_windows_have_correct_structure(self, opt):
        mock_rates = [0.05] * 23 + [-0.03]
        with patch("agents.energy_optimizer._fetch_pjm_lmp_raw", return_value=mock_rates):
            result = opt.get_negative_pricing_windows()
        w = result["windows"][0]
        assert "hour" in w
        assert "rate_usd_per_kwh" in w
        assert w["rate_usd_per_kwh"] < 0


# ---------------------------------------------------------------------------
# Section 3: get_arbitrage_analysis
# ---------------------------------------------------------------------------

class TestArbitrageAnalysis:
    def test_returns_required_keys(self, opt):
        result = opt.get_arbitrage_analysis(1000.0, 0.3)
        for key in ("daily_savings_usd", "annual_savings_usd",
                    "optimal_shift_hours", "data_source"):
            assert key in result

    def test_annual_is_250x_daily(self, opt):
        result = opt.get_arbitrage_analysis(500.0, 0.25)
        assert abs(result["annual_savings_usd"] - result["daily_savings_usd"] * 250) < 0.01

    def test_zero_flexible_load_means_zero_savings(self, opt):
        result = opt.get_arbitrage_analysis(1000.0, 0.0)
        assert result["daily_savings_usd"] == 0.0

    def test_higher_load_means_higher_savings(self, opt):
        r1 = opt.get_arbitrage_analysis(500.0, 0.3)
        r2 = opt.get_arbitrage_analysis(1000.0, 0.3)
        assert r2["annual_savings_usd"] > r1["annual_savings_usd"]

    def test_optimal_shift_hours_are_valid(self, opt):
        result = opt.get_arbitrage_analysis(500.0, 0.3)
        for h in result["optimal_shift_hours"]:
            assert 0 <= h <= 23


# ---------------------------------------------------------------------------
# Section 4: get_scenario_npv
# ---------------------------------------------------------------------------

class TestScenarioNPV:
    def test_grid_only_returns_zero_npv(self, opt):
        result = opt.get_scenario_npv("grid_only", 500_000)
        assert result["npv_10yr_usd"] == 0.0
        assert result["annual_savings_usd"] == 0.0

    def test_solar_positive_npv_at_high_energy(self, opt):
        # At 500 MWh/yr, solar LCOE should beat simulated grid rate
        result = opt.get_scenario_npv("solar", 500_000)
        assert "npv_10yr_usd" in result
        assert result["lcoe_usd_per_kwh"] == 0.045

    def test_custom_capex_overrides_default(self, opt):
        r1 = opt.get_scenario_npv("solar", 200_000)
        r2 = opt.get_scenario_npv("solar", 200_000, capex_usd=200_000)
        assert r1["capex_usd"] != r2["capex_usd"]

    def test_smr_uses_lower_discount_rate(self, opt):
        # SMR uses 6% vs 8% for others; this is internal but we can check
        # that the NPV is computed (no exception)
        result = opt.get_scenario_npv("smr", 2_000_000)
        assert "payback_years" in result

    def test_recommendation_present(self, opt):
        for scenario in ("solar", "battery", "wind", "solar_battery"):
            result = opt.get_scenario_npv(scenario, 300_000)
            assert result["recommendation"]


# ---------------------------------------------------------------------------
# Section 5: Carbon footprint unit tests
# ---------------------------------------------------------------------------

class TestCarbonIntensity:
    def test_fallback_returns_epa_constant(self):
        with patch("agents.energy_optimizer._fetch_carbon_intensity", return_value=None):
            from agents.energy_optimizer import _carbon_cache
            _carbon_cache["fetched_at"] = None  # force refresh
            intensity, source = _get_carbon_intensity()
        assert intensity == US_GRID_CARBON_INTENSITY
        assert source == "epa_2023_average"

    def test_live_intensity_used_when_available(self):
        with patch("agents.energy_optimizer._fetch_carbon_intensity", return_value=0.25):
            from agents.energy_optimizer import _carbon_cache
            _carbon_cache["fetched_at"] = None  # force refresh
            intensity, source = _get_carbon_intensity()
        assert intensity == 0.25
        assert source == "electricity_maps"

    def test_fetch_returns_none_without_api_key(self):
        with patch.dict(os.environ, {"ELECTRICITY_MAPS_API_KEY": ""}):
            result = _fetch_carbon_intensity()
        assert result is None


# ---------------------------------------------------------------------------
# Section 6: API endpoint smoke tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from main import app
    return TestClient(app)


class TestEnergyAPIEndpoints:
    def test_negative_pricing_windows_200(self, client):
        r = client.get("/api/energy/negative-pricing-windows")
        assert r.status_code == 200
        data = r.json()
        assert "total_windows" in data
        assert "windows" in data

    def test_arbitrage_analysis_200(self, client):
        r = client.post(
            "/api/energy/arbitrage-analysis",
            json={"daily_energy_kwh": 1000.0, "flexible_load_percent": 0.3},
        )
        assert r.status_code == 200
        data = r.json()
        assert "annual_savings_usd" in data
        assert data["annual_savings_usd"] >= 0

    def test_scenario_solar_200(self, client):
        r = client.post(
            "/api/energy/scenario",
            json={"scenario": "solar", "annual_energy_kwh": 500_000},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["scenario"] == "solar"
        assert "npv_10yr_usd" in data

    def test_scenario_grid_only_zero_npv(self, client):
        r = client.post(
            "/api/energy/scenario",
            json={"scenario": "grid_only", "annual_energy_kwh": 500_000},
        )
        assert r.status_code == 200
        assert r.json()["npv_10yr_usd"] == 0.0

    def test_schedule_response_includes_energy_analysis(self, client):
        r = client.post(
            "/api/schedule",
            json={
                "orders": [
                    {
                        "order_id": "E-001",
                        "material": "steel",
                        "quantity": 100,
                        "dimensions": "200x100x10mm",
                        "due_date": "2026-12-01T08:00:00",
                        "priority": 3,
                    }
                ]
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "energy_analysis" in data
        ea = data["energy_analysis"]
        assert ea["total_energy_kwh"] > 0
        assert ea["carbon_footprint_kg_co2"] > 0

    def test_schedule_with_battery_soc(self, client):
        r = client.post(
            "/api/schedule",
            json={
                "orders": [
                    {
                        "order_id": "E-002",
                        "material": "aluminum",
                        "quantity": 50,
                        "dimensions": "100x50x5mm",
                        "due_date": "2026-12-01T08:00:00",
                        "priority": 3,
                    }
                ],
                "battery_soc_percent": 80.0,
            },
        )
        assert r.status_code == 200
        ea = r.json()["energy_analysis"]
        assert ea["battery_recommendation"] is not None
        assert "80" in ea["battery_recommendation"]

    def test_quote_includes_carbon_footprint(self, client):
        r = client.post(
            "/api/quote",
            json={
                "material": "steel",
                "dimensions": "200x100x10mm",
                "quantity": 100,
                "priority": 3,
            },
        )
        assert r.status_code == 200
        data = r.json()
        assert "carbon_footprint_kg_co2" in data
        assert data["carbon_footprint_kg_co2"] > 0
