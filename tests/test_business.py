"""Tests for the business router and BusinessAgent."""

import pytest


def _auth(client):
    """Register + login a test user, return headers."""
    client.post("/api/auth/register", json={
        "email": "biz_test@example.com",
        "password": "test1234",
        "name": "Biz Tester",
    })
    client.post("/api/auth/login", json={
        "email": "biz_test@example.com",
        "password": "test1234",
    })


# ── Pricing tiers ──


def test_pricing_tiers_returns_four_tiers(client):
    r = client.get("/api/business/pricing-tiers")
    assert r.status_code == 200
    tiers = r.json()["tiers"]
    assert len(tiers) == 4
    ids = [t["id"] for t in tiers]
    assert ids == ["starter", "growth", "enterprise", "custom"]


def test_pricing_tiers_have_required_fields(client):
    r = client.get("/api/business/pricing-tiers")
    for tier in r.json()["tiers"]:
        assert "name" in tier
        assert "features" in tier
        assert isinstance(tier["features"], list)
        assert len(tier["features"]) > 0
        assert "best_for" in tier


# ── Tier recommendation ──


def test_recommend_tier_starter(client):
    r = client.get("/api/business/recommend-tier", params={
        "machine_count": 3,
        "orders_per_month": 50,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "starter"
    assert "rationale" in r.json()


def test_recommend_tier_growth(client):
    r = client.get("/api/business/recommend-tier", params={
        "machine_count": 12,
        "orders_per_month": 400,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "growth"


def test_recommend_tier_enterprise(client):
    r = client.get("/api/business/recommend-tier", params={
        "machine_count": 50,
        "orders_per_month": 1000,
    })
    assert r.status_code == 200
    assert r.json()["id"] == "enterprise"


# ── ROI calculator ──


def test_roi_calculator_basic(client):
    r = client.post("/api/business/roi-calculator", json={
        "machine_count": 10,
        "orders_per_month": 200,
        "avg_order_value_usd": 1500,
        "current_otd_percent": 74.0,
        "shifts_per_day": 2,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["otd_improvement"]["improvement_pp"] > 0
    assert data["annual_benefits_usd"]["total"] > 0
    assert data["summary"]["roi_percent"] > 0
    assert data["summary"]["payback_months"] is not None
    assert data["summary"]["payback_months"] < 12  # should pay back quickly


def test_roi_calculator_already_high_otd(client):
    """Shop with 95% OTD sees smaller benefit."""
    r = client.post("/api/business/roi-calculator", json={
        "machine_count": 5,
        "orders_per_month": 100,
        "avg_order_value_usd": 2000,
        "current_otd_percent": 95.0,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["otd_improvement"]["improvement_pp"] < 5


def test_roi_calculator_validation(client):
    r = client.post("/api/business/roi-calculator", json={
        "machine_count": 0,
        "orders_per_month": 200,
        "avg_order_value_usd": 1500,
        "current_otd_percent": 74.0,
    })
    assert r.status_code == 422


# ── Revenue projection ──


def test_revenue_projection(client):
    r = client.post("/api/business/revenue-projection", json={
        "months": 12,
        "starting_customers": 3,
        "monthly_new_customers": 2.5,
        "avg_monthly_revenue_per_customer_usd": 1499,
        "churn_rate_monthly_percent": 2.0,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["projection_months"] == 12
    assert len(data["timeline"]) == 12
    assert data["summary"]["final_mrr_usd"] > 0
    assert data["summary"]["final_customers"] > 3  # should grow


def test_revenue_projection_zero_churn(client):
    r = client.post("/api/business/revenue-projection", json={
        "months": 6,
        "starting_customers": 10,
        "monthly_new_customers": 5,
        "avg_monthly_revenue_per_customer_usd": 499,
        "churn_rate_monthly_percent": 0,
    })
    assert r.status_code == 200
    data = r.json()
    # With 0 churn and 5 new/month: month 6 should have 10 + 30 = 40
    assert data["summary"]["final_customers"] == 40.0


# ── Business metrics (requires auth) ──


def test_business_metrics_requires_auth(client):
    r = client.get("/api/business/metrics")
    assert r.status_code in (401, 403)


def test_business_metrics_authenticated(client):
    _auth(client)
    r = client.get("/api/business/metrics")
    assert r.status_code == 200
    data = r.json()
    assert "users" in data
    assert "jobs" in data
    assert "quality" in data
    assert data["users"]["total"] >= 1  # at least the test user
