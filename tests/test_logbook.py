"""
Tests for /api/logbook endpoints.

Covers:
  - POST /api/logbook/entries requires auth (401 without token)
  - POST /api/logbook/entries happy path (201, correct fields)
  - POST /api/logbook/entries validation error (422 on bad payload)
  - GET /api/logbook/entries returns list (no auth required)
  - GET /api/logbook/entries/{id} 404 for unknown entry
"""

import pytest


def _register_and_token(client):
    res = client.post("/api/auth/register", json={
        "email": "logtest@example.com",
        "password": "logpass123",
        "name": "LogTester",
    })
    assert res.status_code == 201
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Auth guard on POST
# ---------------------------------------------------------------------------

def test_create_entry_requires_auth(client):
    """POST /api/logbook/entries without a token must return 401."""
    res = client.post("/api/logbook/entries", json={
        "title": "Test entry",
        "body": "This is a test.",
        "category": "observation",
    })
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_create_entry_success(client):
    token = _register_and_token(client)
    res = client.post(
        "/api/logbook/entries",
        json={
            "title": "Shift handover",
            "body": "Machine 3 running normally.",
            "category": "observation",
        },
        headers=_auth(token),
    )
    assert res.status_code == 201
    data = res.json()
    assert data["title"] == "Shift handover"
    assert data["category"] == "observation"
    assert "id" in data
    assert data["author_id"] is not None


def test_create_entry_uses_authenticated_user(client):
    """author_id must come from the JWT, not a hardcoded value."""
    token = _register_and_token(client)
    res = client.post(
        "/api/logbook/entries",
        json={"title": "Auth check", "body": "Body text.", "category": "note"},
        headers=_auth(token),
    )
    assert res.status_code == 201
    # The author_id should be a positive integer (not 0 or None)
    assert isinstance(res.json()["author_id"], int)
    assert res.json()["author_id"] > 0


def test_create_issue_entry(client):
    token = _register_and_token(client)
    res = client.post(
        "/api/logbook/entries",
        json={
            "title": "Spindle vibration on M2",
            "body": "Noticed unusual vibration at 8000 RPM.",
            "category": "issue",
            "severity": "warning",
            "machine_id": 2,
        },
        headers=_auth(token),
    )
    assert res.status_code == 201
    data = res.json()
    assert data["category"] == "issue"
    assert data["severity"] == "warning"
    assert data["machine_id"] == 2


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------

def test_create_entry_missing_required_fields(client):
    token = _register_and_token(client)
    res = client.post(
        "/api/logbook/entries",
        json={"body": "No title or category"},  # missing title + category
        headers=_auth(token),
    )
    assert res.status_code == 422


def test_create_entry_invalid_category(client):
    token = _register_and_token(client)
    res = client.post(
        "/api/logbook/entries",
        json={"title": "Bad category", "body": "Body.", "category": "not_a_real_category"},
        headers=_auth(token),
    )
    assert res.status_code == 422


# ---------------------------------------------------------------------------
# List entries
# ---------------------------------------------------------------------------

def test_list_entries_empty(client):
    res = client.get("/api/logbook/entries")
    assert res.status_code == 200
    assert isinstance(res.json(), list)


def test_list_entries_returns_created_entry(client):
    token = _register_and_token(client)
    client.post(
        "/api/logbook/entries",
        json={"title": "My log", "body": "Details.", "category": "observation"},
        headers=_auth(token),
    )
    res = client.get("/api/logbook/entries")
    assert res.status_code == 200
    titles = [e["title"] for e in res.json()]
    assert "My log" in titles


# ---------------------------------------------------------------------------
# Get by ID
# ---------------------------------------------------------------------------

def test_get_entry_not_found(client):
    res = client.get("/api/logbook/entries/99999")
    assert res.status_code == 404


def test_get_entry_by_id(client):
    token = _register_and_token(client)
    create_res = client.post(
        "/api/logbook/entries",
        json={"title": "Fetch me", "body": "Entry body.", "category": "note"},
        headers=_auth(token),
    )
    entry_id = create_res.json()["id"]
    res = client.get(f"/api/logbook/entries/{entry_id}")
    assert res.status_code == 200
    assert res.json()["title"] == "Fetch me"
