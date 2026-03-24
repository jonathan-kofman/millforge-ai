"""
HTTP-level tests for the /api/contact endpoint.
"""

import pytest
from unittest.mock import patch, MagicMock


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


# ---------------------------------------------------------------------------
# Database persistence
# ---------------------------------------------------------------------------

def test_contact_saves_to_database(client):
    """Submission is persisted to the DB even if email is not configured."""
    import database as db_module
    from db_models import ContactSubmission

    post_contact(client, {**VALID_PAYLOAD, "company": "Test Mill"})

    session = db_module.SessionLocal()
    try:
        record = session.query(ContactSubmission).filter_by(email=VALID_PAYLOAD["email"]).first()
        assert record is not None
        assert record.name == VALID_PAYLOAD["name"]
        assert record.company == "Test Mill"
    finally:
        session.close()


# ---------------------------------------------------------------------------
# SMTP email notification
# ---------------------------------------------------------------------------

def test_contact_sends_email_when_smtp_configured(client):
    """When SMTP env vars are set, sendmail is called with the correct recipient."""
    env_vars = {"SMTP_EMAIL": "sender@gmail.com", "SMTP_PASSWORD": "abcdabcdabcdabcd"}
    mock_smtp = MagicMock()

    with patch.dict("os.environ", env_vars):
        with patch("smtplib.SMTP_SSL", return_value=mock_smtp.__enter__.return_value):
            mock_smtp.__enter__.return_value.sendmail = MagicMock()
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            with patch("smtplib.SMTP_SSL", return_value=mock_ctx):
                resp = post_contact(client)

    assert resp.status_code == 200
    assert resp.json()["success"] is True
    # sendmail was called once inside the context manager
    mock_ctx.sendmail.assert_called_once()
    args = mock_ctx.sendmail.call_args[0]
    assert "kofman.j@northeastern.edu" in args[1]


def test_contact_returns_success_when_smtp_not_configured(client):
    """Form always returns success even when SMTP_EMAIL/PASSWORD are absent."""
    with patch.dict("os.environ", {"SMTP_EMAIL": "", "SMTP_PASSWORD": ""}):
        resp = post_contact(client)

    assert resp.status_code == 200
    assert resp.json()["success"] is True
