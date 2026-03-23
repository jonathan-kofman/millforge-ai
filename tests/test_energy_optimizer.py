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
)


@pytest.fixture
def optimizer():
    return EnergyOptimizer()


@pytest.fixture
def off_peak_time():
    """A datetime at 02:00 — known off-peak hour."""
    return datetime(2026, 1, 15, 2, 0, 0)


@pytest.fixture
def peak_time():
    """A datetime at 17:00 — known peak hour."""
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
    profile = optimizer.estimate_energy_cost(off_peak_time, 1.0, "steel")
    assert profile.peak_rate == max(MOCK_HOURLY_RATES)
    assert profile.off_peak_rate == min(MOCK_HOURLY_RATES)


def test_peak_recommendation_warns(optimizer, peak_time):
    """Running during peak hours should produce a shift recommendation."""
    profile = optimizer.estimate_energy_cost(peak_time, 1.0, "steel")
    assert "off-peak" in profile.recommendation.lower()


def test_off_peak_recommendation_favorable(optimizer, off_peak_time):
    """Running during off-peak hours should get a favorable recommendation."""
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
