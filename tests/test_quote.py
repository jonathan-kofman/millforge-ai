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
    """quantity < 500 → no discount; 5% discount at 500 → ratio should be ~0.95."""
    base = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 100}).json()
    discounted = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 500}).json()
    assert base["unit_price_usd"] > 0
    assert abs(discounted["unit_price_usd"] / base["unit_price_usd"] - 0.95) < 0.001


def test_five_percent_discount_at_500(client):
    """500 units → 5% off vs. 100 units (no discount)."""
    base = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 100}).json()
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 500}).json()
    assert abs(data["unit_price_usd"] / base["unit_price_usd"] - 0.95) < 0.001


def test_ten_percent_discount_at_1000(client):
    """1000 units → 10% off vs. 100 units (no discount)."""
    base = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 100}).json()
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 1000}).json()
    assert abs(data["unit_price_usd"] / base["unit_price_usd"] - 0.90) < 0.001


def test_twenty_percent_discount_at_10000(client):
    """10000 units → 20% off vs. 100 units (no discount)."""
    base = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 100}).json()
    data = post_quote(client, {**VALID_PAYLOAD, "material": "steel", "quantity": 10000}).json()
    assert abs(data["unit_price_usd"] / base["unit_price_usd"] - 0.80) < 0.001


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


# ---------------------------------------------------------------------------
# Shift scaling validation (bug fix: lead-time scaling silent assumptions)
# ---------------------------------------------------------------------------


def test_quote_shift_scaling_both_provided(client):
    """When both shifts_per_day and hours_per_shift are provided, lead time scales correctly."""
    payload = {
        **VALID_PAYLOAD,
        "shifts_per_day": 1,
        "hours_per_shift": 8,
    }
    resp = post_quote(client, payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["estimated_lead_time_days"] > 0


def test_quote_shift_scaling_3_shifts_faster_than_1_shift(client):
    """3 shifts should give ~1/3 the lead time of 1 shift for the same job (all else equal)."""
    payload_1shift = {
        **VALID_PAYLOAD,
        "shifts_per_day": 1,
        "hours_per_shift": 8,
    }
    payload_3shift = {
        **VALID_PAYLOAD,
        "shifts_per_day": 3,
        "hours_per_shift": 8,
    }
    resp_1 = post_quote(client, payload_1shift)
    resp_3 = post_quote(client, payload_3shift)
    assert resp_1.status_code == 200
    assert resp_3.status_code == 200

    data_1 = resp_1.json()
    data_3 = resp_3.json()

    # 3 shifts (24h operation) should be ~1/3 the time of 1 shift (8h operation)
    ratio = data_1["estimated_lead_time_days"] / data_3["estimated_lead_time_days"]
    # Allow ~10% tolerance for rounding and other factors
    assert 2.7 < ratio < 3.3, f"Expected ratio ~3.0, got {ratio}"


def test_quote_shift_scaling_only_shifts_per_day_returns_400(client):
    """If only shifts_per_day is provided (without hours_per_shift), return 400."""
    payload = {
        **VALID_PAYLOAD,
        "shifts_per_day": 2,
        # hours_per_shift intentionally omitted
    }
    resp = post_quote(client, payload)
    assert resp.status_code == 400
    assert "shifts_per_day and hours_per_shift" in resp.json()["detail"]


def test_quote_shift_scaling_only_hours_per_shift_returns_400(client):
    """If only hours_per_shift is provided (without shifts_per_day), return 400."""
    payload = {
        **VALID_PAYLOAD,
        "hours_per_shift": 8,
        # shifts_per_day intentionally omitted
    }
    resp = post_quote(client, payload)
    assert resp.status_code == 400
    assert "shifts_per_day and hours_per_shift" in resp.json()["detail"]


def test_quote_shift_scaling_neither_provided_assumes_continuous(client):
    """If neither shifts_per_day nor hours_per_shift is provided, assume 24h continuous operation."""
    payload = {k: v for k, v in VALID_PAYLOAD.items()
               if k not in ("shifts_per_day", "hours_per_shift")}
    resp = post_quote(client, payload)
    assert resp.status_code == 200
    # Should work without crashing and give a reasonable lead time


def test_quote_shift_scaling_zero_shifts_per_day_returns_422(client):
    """shifts_per_day = 0 should return 422 (Pydantic validation enforces ge=1)."""
    payload = {
        **VALID_PAYLOAD,
        "shifts_per_day": 0,
        "hours_per_shift": 8,
    }
    resp = post_quote(client, payload)
    # Pydantic rejects before our handler runs
    assert resp.status_code == 422


def test_quote_shift_scaling_zero_hours_per_shift_returns_422(client):
    """hours_per_shift = 0 should return 422 (Pydantic validation enforces ge=4)."""
    payload = {
        **VALID_PAYLOAD,
        "shifts_per_day": 2,
        "hours_per_shift": 0,
    }
    resp = post_quote(client, payload)
    # Pydantic rejects before our handler runs
    assert resp.status_code == 422


def test_quote_shift_scaling_hours_exceed_24_logs_warning(client):
    """productive_hours_per_day > 24 (e.g., 3 shifts × 12 hours) should log warning but not block."""
    payload = {
        **VALID_PAYLOAD,
        "shifts_per_day": 3,
        "hours_per_shift": 12,  # 36 hours/day — overlapping shifts
    }
    resp = post_quote(client, payload)
    # Should succeed (no 400 error), but log a warning internally
    assert resp.status_code == 200
    data = resp.json()
    # With 36h productive time out of 24h calendar time, lead time should be compressed
    assert data["estimated_lead_time_days"] > 0


def test_quote_two_shifts_eight_hours_each_baseline(client):
    """Baseline 2-shift 8-hour operation: standard 16h/day productive."""
    payload = {
        **VALID_PAYLOAD,
        "shifts_per_day": 2,
        "hours_per_shift": 8,
    }
    resp = post_quote(client, payload)
    assert resp.status_code == 200
    data = resp.json()
    # Should give reasonable lead time with 16h/day productive
    assert data["estimated_lead_time_days"] > 0
    assert data["estimated_lead_time_hours"] > 0
