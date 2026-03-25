"""
Tests for the EnergyOptimizer agent.
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.energy_optimizer import (
    EnergyOptimizer,
    MOCK_HOURLY_RATES,
    MACHINE_POWER_KW,
    _rates_cache,
)


@pytest.fixture
def optimizer():
    return EnergyOptimizer()


@pytest.fixture
def off_peak_time():
    """A datetime at 02:00 — known off-peak hour in simulated data."""
    return datetime(2026, 1, 15, 2, 0, 0)


@pytest.fixture
def peak_time():
    """A datetime at 17:00 — known peak hour in simulated data."""
    return datetime(2026, 1, 15, 17, 0, 0)


# ---------------------------------------------------------------------------
# estimate_energy_cost
# ---------------------------------------------------------------------------

def test_estimate_returns_energy_profile(optimizer, off_peak_time):
    profile = optimizer.estimate_energy_cost(off_peak_time, 2.0, "steel")
    assert profile.material == "steel"
    assert profile.estimated_kwh > 0
    assert profile.estimated_cost_usd > 0
    assert profile.start_time == off_peak_time
    assert profile.end_time == off_peak_time + timedelta(hours=2.0)


def test_estimate_kwh_matches_power_draw(optimizer, off_peak_time):
    """estimated_kwh = power_kw × duration."""
    duration = 3.0
    profile = optimizer.estimate_energy_cost(off_peak_time, duration, "titanium")
    expected_kwh = MACHINE_POWER_KW["titanium"] * duration
    assert abs(profile.estimated_kwh - expected_kwh) < 0.01


def test_peak_costs_more_than_off_peak(optimizer, off_peak_time, peak_time):
    """Same job at peak should cost more than at off-peak."""
    duration = 2.0
    peak_profile = optimizer.estimate_energy_cost(peak_time, duration, "steel")
    off_peak_profile = optimizer.estimate_energy_cost(off_peak_time, duration, "steel")
    assert peak_profile.estimated_cost_usd > off_peak_profile.estimated_cost_usd


def test_peak_rate_and_off_peak_rate_correct(optimizer, off_peak_time):
    """peak_rate >= off_peak_rate > 0, regardless of data source."""
    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    assert profile.peak_rate >= profile.off_peak_rate
    assert profile.off_peak_rate > 0


def test_peak_recommendation_warns(optimizer, peak_time, monkeypatch):
    """Running during peak hours (above mean rate) should produce a shift recommendation."""
    # Force simulated fallback so the test is deterministic
    monkeypatch.setattr(optimizer, "hourly_rates", MOCK_HOURLY_RATES)
    monkeypatch.setattr(optimizer, "data_source", "simulated_fallback")
    profile = optimizer.estimate_energy_cost(peak_time, 1.0, "steel")
    assert "off-peak" in profile.recommendation.lower()


def test_off_peak_recommendation_favorable(optimizer, off_peak_time, monkeypatch):
    """Running during off-peak hours should get a favorable recommendation."""
    monkeypatch.setattr(optimizer, "hourly_rates", MOCK_HOURLY_RATES)
    monkeypatch.setattr(optimizer, "data_source", "simulated_fallback")
    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    assert "favorable" in profile.recommendation.lower()


def test_unknown_material_uses_default_power(optimizer, off_peak_time):
    """Unknown material should fall back to default power draw."""
    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "unobtanium")
    expected_kwh = MACHINE_POWER_KW["default"] * 1.0
    assert abs(profile.estimated_kwh - expected_kwh) < 0.01


def test_material_case_insensitive(optimizer, off_peak_time):
    """Material lookup should be case-insensitive."""
    lower = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    upper = optimizer.estimate_energy_cost(off_peak_time, 1.0, "STEEL")
    assert abs(lower.estimated_kwh - upper.estimated_kwh) < 0.001


# ---------------------------------------------------------------------------
# get_optimal_start_windows
# ---------------------------------------------------------------------------

def test_optimal_windows_returns_five(optimizer):
    windows = optimizer.get_optimal_start_windows(2.0, "steel")
    assert len(windows) == 5


def test_optimal_windows_sorted_ascending(optimizer):
    windows = optimizer.get_optimal_start_windows(1.0, "aluminum")
    costs = [w["estimated_cost_usd"] for w in windows]
    assert costs == sorted(costs)


def test_optimal_windows_have_required_keys(optimizer):
    windows = optimizer.get_optimal_start_windows(1.0, "copper")
    for w in windows:
        assert "start_time" in w
        assert "estimated_cost_usd" in w
        assert "estimated_kwh" in w


def test_optimal_windows_respects_lookahead(optimizer):
    """With a lookahead of 3, still returns at most 5 windows (or fewer)."""
    windows = optimizer.get_optimal_start_windows(1.0, "steel", lookahead_hours=3)
    assert len(windows) == 3


def test_optimal_windows_costs_positive(optimizer):
    windows = optimizer.get_optimal_start_windows(2.0, "titanium")
    for w in windows:
        assert w["estimated_cost_usd"] > 0
        assert w["estimated_kwh"] > 0


# ---------------------------------------------------------------------------
# Validation loop tests
# ---------------------------------------------------------------------------

class TestEnergyValidation:

    def test_no_validation_failures_on_valid_profile(self, optimizer, off_peak_time):
        profile = optimizer.estimate_energy_cost(off_peak_time, 2.0, "steel")
        assert profile.validation_failures == []

    def test_validation_catches_negative_kwh(self, optimizer, off_peak_time, monkeypatch):
        _real = optimizer._do_estimate

        def bad_do(start, dur, mat):
            p = _real(start, dur, mat)
            p.estimated_kwh = -1.0   # invalid
            return p

        monkeypatch.setattr(optimizer, "_do_estimate", bad_do)
        profile = optimizer.estimate_energy_cost(off_peak_time, 2.0, "steel")
        assert len(profile.validation_failures) > 0
        assert any("estimated_kwh" in f for f in profile.validation_failures)

    def test_validation_catches_negative_cost(self, optimizer, off_peak_time, monkeypatch):
        _real = optimizer._do_estimate

        def bad_do(start, dur, mat):
            p = _real(start, dur, mat)
            p.estimated_cost_usd = -5.0   # invalid
            return p

        monkeypatch.setattr(optimizer, "_do_estimate", bad_do)
        profile = optimizer.estimate_energy_cost(off_peak_time, 2.0, "steel")
        assert len(profile.validation_failures) > 0
        assert any("estimated_cost_usd" in f for f in profile.validation_failures)

    def test_retry_stops_on_first_valid(self, optimizer, off_peak_time, monkeypatch):
        call_count = {"n": 0}
        _real = optimizer._do_estimate

        def side_effect(start, dur, mat):
            call_count["n"] += 1
            p = _real(start, dur, mat)
            if call_count["n"] == 1:
                p.estimated_kwh = -1.0   # bad first attempt
            return p

        monkeypatch.setattr(optimizer, "_do_estimate", side_effect)
        profile = optimizer.estimate_energy_cost(off_peak_time, 2.0, "steel")
        assert call_count["n"] == 2
        assert profile.validation_failures == []


# ---------------------------------------------------------------------------
# Real data / data_source tests (new)
# ---------------------------------------------------------------------------

def test_profile_has_data_source_field(optimizer, off_peak_time):
    """EnergyProfile must expose data_source (either real or fallback)."""
    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    assert profile.data_source in ("EIA_realtime", "simulated_fallback")


def test_simulated_fallback_is_default_without_network(optimizer, off_peak_time, monkeypatch):
    """When EIA fetch fails, data_source should be simulated_fallback."""
    import agents.energy_optimizer as eo_module

    def mock_fetch():
        return None  # simulate network failure

    monkeypatch.setattr(eo_module, "_fetch_real_time_price", mock_fetch)
    # Expire cache to force re-fetch
    eo_module._rates_cache["fetched_at"] = None
    optimizer._refresh_rates()

    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    assert profile.data_source == "simulated_fallback"


def test_pjm_realtime_when_fetch_succeeds(optimizer, off_peak_time, monkeypatch):
    """When EIA fetch returns valid rates, data_source should be EIA_realtime."""
    import agents.energy_optimizer as eo_module

    fake_rates = [0.04 + i * 0.002 for i in range(24)]  # 24 valid $/kWh values

    def mock_fetch():
        return fake_rates

    monkeypatch.setattr(eo_module, "_fetch_real_time_price", mock_fetch)
    eo_module._rates_cache["fetched_at"] = None  # expire cache
    optimizer._refresh_rates()

    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    assert profile.data_source == "EIA_realtime"


def test_cache_reuses_rates_within_ttl(monkeypatch):
    """Rates should not be re-fetched within the TTL window."""
    import agents.energy_optimizer as eo_module

    call_count = {"n": 0}

    def counting_fetch():
        call_count["n"] += 1
        return [0.05] * 24

    monkeypatch.setattr(eo_module, "_fetch_real_time_price", counting_fetch)
    # Save and restore full cache state so downstream tests aren't affected
    monkeypatch.setitem(eo_module._rates_cache, "rates", eo_module._rates_cache["rates"])
    monkeypatch.setitem(eo_module._rates_cache, "fetched_at", None)
    monkeypatch.setitem(eo_module._rates_cache, "data_source", eo_module._rates_cache["data_source"])

    eo_module._get_hourly_rates()
    eo_module._get_hourly_rates()
    eo_module._get_hourly_rates()

    assert call_count["n"] == 1  # only one actual fetch within TTL


def test_recommendation_threshold_is_relative(optimizer, monkeypatch):
    """Recommendation logic must use mean rate as threshold, not a hardcoded value."""
    import agents.energy_optimizer as eo_module

    # All hours set to same value — no hour is above mean, so always favorable
    flat_rates = [0.05] * 24
    # Patch the cache so _refresh_rates() returns flat rates instead of MOCK_HOURLY_RATES
    monkeypatch.setitem(eo_module._rates_cache, "rates", flat_rates)
    monkeypatch.setitem(eo_module._rates_cache, "data_source", "simulated_fallback")
    monkeypatch.setattr(optimizer, "hourly_rates", flat_rates)
    monkeypatch.setattr(optimizer, "data_source", "simulated_fallback")

    for h in range(24):
        t = datetime(2026, 1, 15, h, 0, 0)
        profile = optimizer.estimate_energy_cost(t, 1.0, "steel")
        assert "favorable" in profile.recommendation.lower(), (
            f"Hour {h} with flat rates should be favorable, got: {profile.recommendation}"
        )
