"""
HTTP-level tests for the /api/contact endpoint.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_PAYLOAD = {
    "name": "Alice Smith",
    "email": "alice@example.com",
    "message": "Interested in your scheduling platform for our mill.",
    "pilot_interest": False,
}


def post_contact(client, payload=None):
    return client.post("/api/contact", json=payload or VALID_PAYLOAD)


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------

def test_contact_returns_200(client):
    resp = post_contact(client)
    assert resp.status_code == 200


def test_contact_response_fields(client):
    data = post_contact(client).json()
    assert "success" in data
    assert "message" in data


def test_contact_success_is_true(client):
    data = post_contact(client).json()
    assert data["success"] is True


def test_contact_message_mentions_name(client):
    data = post_contact(client).json()
    assert "Alice" in data["message"]


# ---------------------------------------------------------------------------
# pilot_interest flag
# ---------------------------------------------------------------------------

def test_pilot_interest_true_message(client):
    data = post_contact(client, {**VALID_PAYLOAD, "pilot_interest": True}).json()
    assert "pilot" in data["message"].lower()


def test_pilot_interest_false_no_pilot_mention(client):
    data = post_contact(client, {**VALID_PAYLOAD, "pilot_interest": False}).json()
    assert "pilot" not in data["message"].lower()


# ---------------------------------------------------------------------------
# Optional company field
# ---------------------------------------------------------------------------

def test_contact_with_company(client):
    resp = post_contact(client, {**VALID_PAYLOAD, "company": "Acme Steel"})
    assert resp.status_code == 200


def test_contact_without_company(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "company"}
    resp = post_contact(client, payload)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Validation errors (422)
# ---------------------------------------------------------------------------

def test_missing_name_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "name"}
    resp = post_contact(client, payload)
    assert resp.status_code == 422


def test_name_too_short_returns_422(client):
    resp = post_contact(client, {**VALID_PAYLOAD, "name": "A"})
    assert resp.status_code == 422


def test_missing_email_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "email"}
    resp = post_contact(client, payload)
    assert resp.status_code == 422


def test_missing_message_returns_422(client):
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "message"}
    resp = post_contact(client, payload)
    assert resp.status_code == 422


def test_message_too_short_returns_422(client):
    resp = post_contact(client, {**VALID_PAYLOAD, "message": "Too short"})
    assert resp.status_code == 422
