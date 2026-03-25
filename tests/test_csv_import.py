"""
Tests for CSV bulk order import endpoints.

Covers:
1. Basic preview — valid CSV, all columns recognised
2. Fuzzy column matching — qty / deadline / part_number aliases
3. Missing required column — 422 with helpful error message
4. Invalid rows — bad material value isolated to error_rows
5. Auth required — 401 without token
6. Confirm success — orders committed to DB, visible in /api/orders
7. Confirm invalid token — 404
8. Template download — returns CSV with correct headers
"""

import io
import pytest
from datetime import datetime, timedelta, timezone


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_token(client, email="csvuser@example.com"):
    res = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "CSV Tester",
    })
    assert res.status_code == 201
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _csv_upload(content: str, filename: str = "orders.csv"):
    """Return files dict suitable for TestClient multipart upload."""
    return {"file": (filename, io.BytesIO(content.encode()), "text/csv")}


def _future_date(days: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 1. Basic preview
# ---------------------------------------------------------------------------

def test_csv_import_preview_basic(client):
    """Valid CSV with all columns returns parsed preview."""
    token = _register_and_token(client)
    csv_content = (
        f"order_id,material,quantity,dimensions,due_date,priority,complexity\n"
        f"P-001,steel,500,200x100x10mm,{_future_date(30)},3,1.0\n"
        f"P-002,aluminum,200,150x75x8mm,{_future_date(60)},5,1.2\n"
    )
    res = client.post(
        "/api/orders/import-csv",
        files=_csv_upload(csv_content),
        headers=_auth(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid_count"] == 2
    assert data["error_count"] == 0
    assert data["total_rows"] == 2
    assert "preview_token" in data
    assert len(data["valid_rows"]) == 2
    row = data["valid_rows"][0]
    assert row["material"] == "steel"
    assert row["quantity"] == 500
    assert row["order_id"] == "P-001"


# ---------------------------------------------------------------------------
# 2. Fuzzy column matching
# ---------------------------------------------------------------------------

def test_csv_import_preview_fuzzy_columns(client):
    """Aliases like qty / deadline / part_number / metal are mapped correctly."""
    token = _register_and_token(client, "fuzzy@example.com")
    csv_content = (
        f"part_number,metal,qty,deadline\n"
        f"JOB-99,steel,100,{_future_date(14)}\n"
    )
    res = client.post(
        "/api/orders/import-csv",
        files=_csv_upload(csv_content),
        headers=_auth(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid_count"] == 1
    assert data["error_count"] == 0
    # column_mapping should expose the alias → canonical mapping
    mapping = data["column_mapping"]
    assert mapping.get("qty") == "quantity"
    assert mapping.get("deadline") == "due_date"
    assert mapping.get("metal") == "material"
    # parsed row should carry the original order_id value
    assert data["valid_rows"][0]["order_id"] == "JOB-99"


# ---------------------------------------------------------------------------
# 3. Missing required column
# ---------------------------------------------------------------------------

def test_csv_import_preview_missing_required_column(client):
    """CSV without due_date (or alias) returns 422 with a helpful message."""
    token = _register_and_token(client, "missing@example.com")
    csv_content = "material,quantity\nsteel,500\n"
    res = client.post(
        "/api/orders/import-csv",
        files=_csv_upload(csv_content),
        headers=_auth(token),
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert "due_date" in detail


# ---------------------------------------------------------------------------
# 4. Invalid rows
# ---------------------------------------------------------------------------

def test_csv_import_preview_invalid_rows(client):
    """Rows with bad material are isolated to error_rows; valid rows pass through."""
    token = _register_and_token(client, "invalid@example.com")
    csv_content = (
        f"material,quantity,due_date\n"
        f"steel,500,{_future_date(10)}\n"
        f"unobtanium,200,{_future_date(20)}\n"
        f"aluminum,300,{_future_date(30)}\n"
    )
    res = client.post(
        "/api/orders/import-csv",
        files=_csv_upload(csv_content),
        headers=_auth(token),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["valid_count"] == 2
    assert data["error_count"] == 1
    assert data["total_rows"] == 3
    err = data["error_rows"][0]
    assert "unobtanium" in err["error"]
    assert err["row_number"] == 3


# ---------------------------------------------------------------------------
# 5. Auth required
# ---------------------------------------------------------------------------

def test_csv_import_requires_auth(client):
    """POST /api/orders/import-csv returns 401 without a bearer token."""
    csv_content = f"material,quantity,due_date\nsteel,500,{_future_date()}\n"
    res = client.post("/api/orders/import-csv", files=_csv_upload(csv_content))
    assert res.status_code == 401


# ---------------------------------------------------------------------------
# 6. Confirm success
# ---------------------------------------------------------------------------

def test_csv_import_confirm_success(client):
    """Preview then confirm creates orders in the DB."""
    token = _register_and_token(client, "confirm@example.com")
    csv_content = (
        f"material,quantity,due_date\n"
        f"steel,500,{_future_date(14)}\n"
        f"titanium,50,{_future_date(30)}\n"
    )
    # Step 1: preview
    preview_res = client.post(
        "/api/orders/import-csv",
        files=_csv_upload(csv_content),
        headers=_auth(token),
    )
    assert preview_res.status_code == 200
    preview_token = preview_res.json()["preview_token"]

    # Step 2: confirm
    confirm_res = client.post(
        "/api/orders/import-csv/confirm",
        json={"preview_token": preview_token},
        headers=_auth(token),
    )
    assert confirm_res.status_code == 200
    data = confirm_res.json()
    assert data["imported_count"] == 2
    assert len(data["order_ids"]) == 2
    assert data["skipped_count"] == 0
    # All generated IDs should start with ORD-
    for oid in data["order_ids"]:
        assert oid.startswith("ORD-")

    # Orders must now appear in /api/orders
    orders_res = client.get("/api/orders", headers=_auth(token))
    assert orders_res.status_code == 200
    assert orders_res.json()["total"] == 2


# ---------------------------------------------------------------------------
# 7. Confirm invalid token
# ---------------------------------------------------------------------------

def test_csv_import_confirm_invalid_token(client):
    """Confirm with an unknown token returns 404."""
    token = _register_and_token(client, "badtoken@example.com")
    res = client.post(
        "/api/orders/import-csv/confirm",
        json={"preview_token": "thisisnotavalidtoken"},
        headers=_auth(token),
    )
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 8. Template download
# ---------------------------------------------------------------------------

def test_csv_import_template(client):
    """GET /api/orders/import-csv/template returns a CSV with required headers."""
    res = client.get("/api/orders/import-csv/template")
    assert res.status_code == 200
    assert "text/csv" in res.headers.get("content-type", "")
    content = res.text
    assert "material" in content
    assert "quantity" in content
    assert "due_date" in content
    # Should contain at least one example data row
    lines = [line for line in content.splitlines() if line.strip()]
    assert len(lines) >= 2
