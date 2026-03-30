"""
Tests for GET /api/schedule/export-pdf endpoint.

Covers:
1. Valid export returns PDF bytes (application/pdf content-type)
2. PDF content-disposition header uses schedule ID
3. 404 for non-existent schedule_id
4. 401 without authentication token
5. User isolation — cannot export another user's schedule run
"""

import io
import pytest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_token(client, email="pdfuser@example.com"):
    res = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "PDF Tester",
    })
    assert res.status_code == 201
    client.cookies.clear()
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _future_date(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


def _create_and_schedule(client, token) -> int:
    """Create two orders and schedule them; return schedule_run_id."""
    for material, qty in [("steel", 200), ("aluminum", 150)]:
        res = client.post("/api/orders", json={
            "material": material,
            "quantity": qty,
            "dimensions": "100x50x10mm",
            "due_date": _future_date(20),
            "priority": 5,
            "complexity": 1.0,
        }, headers=_auth(token))
        assert res.status_code == 201

    sched_res = client.post("/api/orders/schedule?algorithm=edd", headers=_auth(token))
    assert sched_res.status_code == 200
    return sched_res.json()["schedule_run_id"]


# ---------------------------------------------------------------------------
# 1. Valid export returns PDF
# ---------------------------------------------------------------------------

def test_pdf_export_returns_pdf(client):
    """GET /api/schedule/export-pdf with valid schedule_id returns application/pdf."""
    token = _register_and_token(client)
    run_id = _create_and_schedule(client, token)

    res = client.get(f"/api/schedule/export-pdf?schedule_id={run_id}", headers=_auth(token))
    assert res.status_code == 200
    assert "application/pdf" in res.headers.get("content-type", "")
    # PDF magic bytes: %PDF-
    assert res.content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# 2. Content-Disposition header uses schedule ID
# ---------------------------------------------------------------------------

def test_pdf_export_content_disposition(client):
    """Content-Disposition header contains the schedule run ID as filename."""
    token = _register_and_token(client, "pdfcd@example.com")
    run_id = _create_and_schedule(client, token)

    res = client.get(f"/api/schedule/export-pdf?schedule_id={run_id}", headers=_auth(token))
    assert res.status_code == 200
    disposition = res.headers.get("content-disposition", "")
    assert f"schedule_{run_id}.pdf" in disposition


# ---------------------------------------------------------------------------
# 3. 404 for non-existent schedule
# ---------------------------------------------------------------------------

def test_pdf_export_not_found(client):
    """schedule_id that doesn't exist returns 404."""
    token = _register_and_token(client, "pdfnotfound@example.com")
    res = client.get("/api/schedule/export-pdf?schedule_id=99999", headers=_auth(token))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 4. 401 without auth token
# ---------------------------------------------------------------------------

def test_pdf_export_requires_auth(client):
    """GET /api/schedule/export-pdf without bearer token returns 401."""
    res = client.get("/api/schedule/export-pdf?schedule_id=1")
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 5. User isolation
# ---------------------------------------------------------------------------

def test_pdf_export_user_isolation(client):
    """User A cannot download User B's schedule run."""
    token_a = _register_and_token(client, "pdfa@example.com")
    token_b = _register_and_token(client, "pdfb@example.com")

    # User A creates and schedules orders
    run_id = _create_and_schedule(client, token_a)

    # User B tries to export User A's schedule run
    res = client.get(f"/api/schedule/export-pdf?schedule_id={run_id}", headers=_auth(token_b))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 6. Path-param endpoint returns PDF
# ---------------------------------------------------------------------------

def test_pdf_export_path_param_returns_pdf(client):
    """GET /api/schedule/{run_id}/export-pdf returns a valid PDF."""
    token = _register_and_token(client, "pdfpath@example.com")
    run_id = _create_and_schedule(client, token)

    res = client.get(f"/api/schedule/{run_id}/export-pdf", headers=_auth(token))
    assert res.status_code == 200
    assert "application/pdf" in res.headers.get("content-type", "")
    assert res.content[:4] == b"%PDF"
    assert f"schedule_{run_id}.pdf" in res.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# 7. Path-param 404 for non-existent run
# ---------------------------------------------------------------------------

def test_pdf_export_path_param_not_found(client):
    """Path-param variant returns 404 for non-existent run_id."""
    token = _register_and_token(client, "pdfpath404@example.com")
    res = client.get("/api/schedule/99999/export-pdf", headers=_auth(token))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 8. Path-param requires auth
# ---------------------------------------------------------------------------

def test_pdf_export_path_param_requires_auth(client):
    """Path-param variant returns 401 without auth."""
    res = client.get("/api/schedule/1/export-pdf")
    assert res.status_code == 401
