"""Tests for the contracts router and ContractGenerator agent."""

import pytest


# ── SLA schedule ──


def test_sla_starter(client):
    r = client.get("/api/contracts/sla/starter")
    assert r.status_code == 200
    data = r.json()
    assert data["document_type"] == "sla_schedule"
    assert data["tier"] == "starter"
    assert "content_markdown" in data
    assert "99.0%" in data["content_markdown"]
    assert "generated_at" in data


def test_sla_enterprise(client):
    r = client.get("/api/contracts/sla/enterprise")
    assert r.status_code == 200
    data = r.json()
    assert "99.9%" in data["content_markdown"]
    assert "Dedicated CSM" in data["content_markdown"]


def test_sla_unknown_tier_falls_back(client):
    """Unknown tier falls back to starter SLA."""
    r = client.get("/api/contracts/sla/nonexistent")
    assert r.status_code == 200
    data = r.json()
    assert "99.0%" in data["content_markdown"]


# ── MSA ──


def test_msa_generation(client):
    r = client.post("/api/contracts/msa", json={
        "customer_name": "Precision Parts Inc.",
        "customer_address": "123 Mill Road, Cleveland, OH 44101",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["document_type"] == "msa"
    assert data["customer_name"] == "Precision Parts Inc."
    md = data["content_markdown"]
    assert "Precision Parts Inc." in md
    assert "123 Mill Road" in md
    assert "Massachusetts" in md  # default governing state
    assert "PRECISION PARTS INC." in md  # uppercased signature block


def test_msa_custom_governing_state(client):
    r = client.post("/api/contracts/msa", json={
        "customer_name": "Texas Machining",
        "customer_address": "456 Shop Ave, Houston, TX",
        "governing_state": "Texas",
    })
    assert r.status_code == 200
    assert "Texas" in r.json()["content_markdown"]


def test_msa_custom_date(client):
    r = client.post("/api/contracts/msa", json={
        "customer_name": "Test Co",
        "customer_address": "Test Addr",
        "effective_date": "2026-06-01",
    })
    assert r.status_code == 200
    assert "June 01, 2026" in r.json()["content_markdown"]


def test_msa_bad_date(client):
    r = client.post("/api/contracts/msa", json={
        "customer_name": "Test Co",
        "customer_address": "Test Addr",
        "effective_date": "not-a-date",
    })
    assert r.status_code == 400


def test_msa_validation_short_name(client):
    r = client.post("/api/contracts/msa", json={
        "customer_name": "X",
        "customer_address": "Test Addr",
    })
    assert r.status_code == 422


# ── Order form ──


def test_order_form_growth_annual(client):
    r = client.post("/api/contracts/order-form", json={
        "customer_name": "Midwest Metals",
        "tier": "growth",
        "machine_count": 12,
        "billing_cycle": "annual",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["document_type"] == "order_form"
    assert data["tier"] == "growth"
    md = data["content_markdown"]
    assert "Midwest Metals" in md
    assert "12 machines" in md
    assert "14,990" in md  # growth annual price


def test_order_form_with_addons(client):
    r = client.post("/api/contracts/order-form", json={
        "customer_name": "Test Shop",
        "tier": "growth",
        "machine_count": 10,
        "add_ons": ["contract_management", "sso_saml"],
    })
    assert r.status_code == 200
    md = r.json()["content_markdown"]
    assert "Contract Management" in md
    assert "Sso Saml" in md


def test_order_form_invalid_tier(client):
    r = client.post("/api/contracts/order-form", json={
        "customer_name": "Test Shop",
        "tier": "nonexistent",
        "machine_count": 5,
    })
    assert r.status_code == 400
    assert "Unknown tier" in r.json()["detail"]


# ── Pilot agreement ──


def test_pilot_agreement_default(client):
    r = client.post("/api/contracts/pilot", json={
        "customer_name": "New England CNC",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["document_type"] == "pilot_agreement"
    assert data["tier"] == "growth"
    md = data["content_markdown"]
    assert "New England CNC" in md
    assert "30 days" in md
    assert "No charge" in md


def test_pilot_agreement_custom_days(client):
    r = client.post("/api/contracts/pilot", json={
        "customer_name": "Quick Test Co",
        "pilot_days": 14,
        "tier": "starter",
    })
    assert r.status_code == 200
    md = r.json()["content_markdown"]
    assert "14 days" in md
    assert "Starter" in md


def test_pilot_agreement_custom_date(client):
    r = client.post("/api/contracts/pilot", json={
        "customer_name": "Date Test Co",
        "start_date": "2026-07-01",
    })
    assert r.status_code == 200
    assert "July 01, 2026" in r.json()["content_markdown"]
