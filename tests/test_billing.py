"""Billing config endpoint (Stripe optional)."""

from fastapi.testclient import TestClient


def test_billing_config_schema():
    from main import app

    client = TestClient(app)
    r = client.get("/api/billing/config")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data.get("stripe_enabled"), bool)
    assert "publishable_key" in data
