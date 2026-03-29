"""Tests for the market quotes router and MarketQuoter agent."""

import pytest


# ── Spot prices ──


def test_spot_prices_all(client):
    r = client.get("/api/market-quotes/spot-prices")
    assert r.status_code == 200
    data = r.json()
    assert "prices_usd_per_lb" in data
    assert "data_sources" in data
    prices = data["prices_usd_per_lb"]
    assert len(prices) > 0
    assert "steel" in prices
    assert "aluminum" in prices
    assert all(isinstance(v, (int, float)) and v > 0 for v in prices.values())


def test_spot_prices_filtered(client):
    r = client.get("/api/market-quotes/spot-prices", params={"materials": "steel,copper"})
    assert r.status_code == 200
    prices = r.json()["prices_usd_per_lb"]
    assert "steel" in prices
    assert "copper" in prices


def test_spot_prices_unknown_material(client):
    """Unknown materials return fallback price of 1.0."""
    r = client.get("/api/market-quotes/spot-prices", params={"materials": "unobtainium"})
    assert r.status_code == 200
    prices = r.json()["prices_usd_per_lb"]
    assert "unobtainium" in prices
    assert prices["unobtainium"] == 1.0


# ── Materials quote ──


def test_materials_quote(client):
    r = client.post("/api/market-quotes/materials", json={
        "material": "steel",
        "quantity_lbs": 500,
        "mill_form": "bar_stock",
        "top_n": 3,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["material"] == "steel"
    assert data["quantity_lbs"] == 500
    assert data["spot_price_usd_per_lb"] > 0
    # May or may not have suppliers depending on DB state
    assert "options" in data


def test_materials_quote_with_geo(client):
    r = client.post("/api/market-quotes/materials", json={
        "material": "aluminum",
        "quantity_lbs": 1000,
        "lat": 41.5,
        "lng": -81.7,
        "top_n": 5,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["material"] == "aluminum"


def test_materials_quote_validation(client):
    r = client.post("/api/market-quotes/materials", json={
        "material": "steel",
        "quantity_lbs": -100,
    })
    assert r.status_code == 422


# ── Energy quote ──


def test_energy_quote(client):
    r = client.post("/api/market-quotes/energy", json={
        "kwh_needed": 500,
        "flexible_hours": 4,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["kwh_needed"] == 500
    assert "cheapest_window" in data
    assert "peak_window" in data
    assert data["potential_savings_usd"] >= 0
    assert len(data["cheapest_window"]["hours_utc"]) == 4
    assert data["cheapest_window"]["total_cost_usd"] > 0


def test_energy_quote_large_flexible_window(client):
    r = client.post("/api/market-quotes/energy", json={
        "kwh_needed": 1000,
        "flexible_hours": 8,
    })
    assert r.status_code == 200
    data = r.json()
    assert len(data["cheapest_window"]["hours_utc"]) == 8
    # Cheapest window should always cost less than or equal to peak
    assert data["cheapest_window"]["total_cost_usd"] <= data["peak_window"]["total_cost_usd"]


# ── Full job cost ──


def test_full_job_cost(client):
    r = client.post("/api/market-quotes/full-job-cost", json={
        "material": "steel",
        "quantity_lbs": 200,
        "estimated_machine_hours": 4.0,
        "machine_power_kw": 85,
    })
    assert r.status_code == 200
    data = r.json()
    breakdown = data["cost_breakdown"]
    assert breakdown["total_usd"] > 0
    assert breakdown["materials_usd"] >= 0
    assert breakdown["energy_usd"] > 0
    assert breakdown["overhead_usd"] > 0
    # overhead = 20% of (materials + energy)
    expected_overhead = round((breakdown["materials_usd"] + breakdown["energy_usd"]) * 0.20, 2)
    assert abs(breakdown["overhead_usd"] - expected_overhead) < 0.02
    assert "energy_recommendation" in data


def test_full_job_cost_validation(client):
    r = client.post("/api/market-quotes/full-job-cost", json={
        "material": "steel",
        "quantity_lbs": 200,
        "estimated_machine_hours": -1,
    })
    assert r.status_code == 422
