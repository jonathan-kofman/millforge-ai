"""
HTTP-level tests for the /api/quote endpoint.
"""

import pytest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "material": "steel",
    "dimensions": "200x100x10mm",
    "quantity": 100,
    "priority": 5,
}


def post_quote(client, payload=None):
    return client.post("/api/quote", json=payload or VALID_PAYLOAD)


# ---------------------------------------------------------------------------
# Happy-path response shape
# ---------------------------------------------------------------------------

def test_quote_returns_200(client):
    resp = post_quote(client)
    assert resp.status_code == 200


def test_quote_response_fields(client):
    data = post_quote(client).json()
    assert "quote_id" in data
    assert "material" in data
    assert "dimensions" in data
    assert "quantity" in data
    assert "estimated_lead_time_hours" in data
    assert "estimated_lead_time_days" in data
    assert "unit_price_usd" in data
    assert "total_price_usd" in data
    assert "valid_until" in data
    assert "notes" in data


def test_quote_id_has_quote_prefix(client):
    data = post_quote(client).json()
    assert data["quote_id"].startswith("QUOTE-")


def test_quote_echoes_material(client):
    data = post_quote(client).json()
    assert data["material"] == "steel"


def test_quote_lead_time_positive(client):
    data = post_quote(client).json()
    assert data["estimated_lead_time_hours"] > 0
    assert data["estimated_lead_time_days"] > 0


def test_quote_lead_time_days_consistent(client):
    """lead_time_days ≈ lead_time_hours / 24."""
    data = post_quote(client).json()
    assert abs(data["estimated_lead_time_days"] - data["estimated_lead_time_hours"] / 24) < 0.01


def test_quote_total_price_positive(client):
    data = post_quote(client).json()
    assert data["total_price_usd"] > 0
    assert data["unit_price_usd"] > 0


def test_quote_total_equals_unit_times_quantity(client):
    """total_price_usd == unit_price_usd × quantity (within rounding)."""
    data = post_quote(client).json()
    expected = round(data["unit_price_usd"] * data["quantity"], 2)
    assert abs(data["total_price_usd"] - expected) < 0.02


def test_quote_valid_until_in_future(client):
    data = post_quote(client).json()
    valid_until = datetime.fromisoformat(data["valid_until"])
    assert valid_until > datetime.now(timezone.utc).replace(tzinfo=None)


def test_quote_notes_mention_lead_time(client):
    data = post_quote(client).json()
    assert "lead time" in data["notes"].lower()


# ---------------------------------------------------------------------------
# Material pricing
# ---------------------------------------------------------------------------

def test_titanium_more_expensive_than_steel(client):
    steel = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 100}).json()
    titanium = post_quote(client, {**VALID_PAYLOAD, "material": "titanium", "quantity": 100}).json()
    assert titanium["unit_price_usd"] > steel["unit_price_usd"]


def test_all_materials_accepted(client):
    for material in ("steel", "aluminum", "titanium", "copper"):
        resp = post_quote(client, {**VALID_PAYLOAD, "material": material})
        assert resp.status_code == 200, f"Failed for material={material}"


# ---------------------------------------------------------------------------
# Volume discounts
# ---------------------------------------------------------------------------

def test_no_discount_below_500(client):
    """quantity < 500 → no discount; unit_price_usd should equal UNIT_PRICE['steel']."""
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 100}).json()
    assert abs(data["unit_price_usd"] - 2.50) < 0.001


def test_five_percent_discount_at_500(client):
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 500}).json()
    assert abs(data["unit_price_usd"] - 2.50 * 0.95) < 0.001


def test_ten_percent_discount_at_1000(client):
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 1000}).json()
    assert abs(data["unit_price_usd"] - 2.50 * 0.90) < 0.001


def test_twenty_percent_discount_at_10000(client):
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 10000}).json()
    assert abs(data["unit_price_usd"] - 2.50 * 0.80) < 0.001


def test_discount_note_present_for_large_order(client):
    data = post_quote(client, {**VALID_PAYLOAD, "quantity": 1000}).json()
    assert "discount" in data["notes"].lower()


# ---------------------------------------------------------------------------
# Optional fields
# ---------------------------------------------------------------------------

def test_quote_with_explicit_due_date(client):
    due = (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=60)).isoformat()
    resp = post_quote(client, {**VALID_PAYLOAD, "due_date": due})
    assert resp.status_code == 200


def test_quote_without_due_date(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "due_date"}
    resp = post_quote(client, payload)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------

def test_invalid_material_returns_422(client):
    resp = post_quote(client, {**VALID_PAYLOAD, "material": "unobtanium"})
    assert resp.status_code == 422


def test_zero_quantity_returns_422(client):
    resp = post_quote(client, {**VALID_PAYLOAD, "quantity": 0})
    assert resp.status_code == 422


def test_quantity_exceeds_max_returns_422(client):
    resp = post_quote(client, {**VALID_PAYLOAD, "quantity": 100_001})
    assert resp.status_code == 422


def test_missing_material_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "material"}
    resp = post_quote(client, payload)
    assert resp.status_code == 422


def test_missing_dimensions_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "dimensions"}
    resp = post_quote(client, payload)
    assert resp.status_code == 422
