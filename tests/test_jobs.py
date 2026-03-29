"""
Tests for /api/jobs — CAM import, lifecycle management, machine-aware scheduling, QC stage.

Covers:
1. POST /api/jobs/import-from-cam — happy path
2. Schema version rejection (unsupported version)
3. GET /api/jobs — list
4. GET /api/jobs/{id} — detail
5. PATCH /api/jobs/{id} — stage transition
6. DELETE /api/jobs/{id}
7. GET /api/machines/check-conflict — available match
8. GET /api/machines/check-conflict — no match
9. POST /api/machines — create machine
10. CAMImport Pydantic model validates against contracts/cam_setup_schema_v1.json
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_CAM_PAYLOAD = {
    "schema_version": "1.0",
    "part_id": "ARIA-P-TEST-001",
    "machine_name": "Haas VF-2",
    "tools": [{"tool_number": 1, "description": "3/8 End Mill", "diameter_mm": 9.5}],
    "stock_dims": {"length_mm": 120.0, "width_mm": 60.0, "height_mm": 25.0},
    "cycle_time_min_estimate": 42.5,
    "second_op_required": False,
    "work_offset_recommendation": "G54",
    "fixturing_suggestion": "Kurt vise, jaw width 60mm",
    "generated_at": "2024-01-01T08:00:00",
    "material": "aluminum",
}


def _auth_headers(client) -> dict:
    """Register + login, return empty dict (auth via cookie in TestClient)."""
    client.post("/api/auth/register", json={
        "email": "job_test@example.com",
        "password": "testpass123",
        "name": "Test User",
    })
    client.post("/api/auth/login", json={
        "email": "job_test@example.com",
        "password": "testpass123",
    })
    return {}


# ---------------------------------------------------------------------------
# CAM import
# ---------------------------------------------------------------------------

def test_cam_import_happy_path(client):
    _auth_headers(client)
    resp = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD)
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["title"] == "ARIA-P-TEST-001 — Haas VF-2"
    assert data["stage"] == "queued"
    assert data["source"] == "aria_cam"
    assert data["material"] == "aluminum"
    assert data["estimated_duration_minutes"] == 42.5
    assert data["cam_metadata"]["part_id"] == "ARIA-P-TEST-001"


def test_cam_import_rejects_unsupported_version(client):
    _auth_headers(client)
    bad = dict(_CAM_PAYLOAD, schema_version="99.0")
    resp = client.post("/api/jobs/import-from-cam", json=bad)
    assert resp.status_code == 400
    assert "Unsupported ARIA schema version" in resp.json()["detail"]


def test_cam_import_creates_required_machine_type(client):
    _auth_headers(client)
    resp = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD)
    assert resp.status_code == 201
    assert resp.json()["required_machine_type"] == "Haas VF-2"


# ---------------------------------------------------------------------------
# List / Get
# ---------------------------------------------------------------------------

def test_list_jobs_returns_created_job(client):
    _auth_headers(client)
    client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD)
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    assert any(j["source"] == "aria_cam" for j in data["jobs"])


def test_get_job_by_id(client):
    _auth_headers(client)
    created = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD).json()
    resp = client.get(f"/api/jobs/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_job_404_on_missing(client):
    _auth_headers(client)
    resp = client.get("/api/jobs/99999999")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------

def test_patch_job_stage(client):
    _auth_headers(client)
    job = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD).json()
    resp = client.patch(f"/api/jobs/{job['id']}", json={"stage": "in_progress"})
    assert resp.status_code == 200
    assert resp.json()["stage"] == "in_progress"


def test_patch_job_invalid_stage(client):
    _auth_headers(client)
    job = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD).json()
    resp = client.patch(f"/api/jobs/{job['id']}", json={"stage": "flying"})
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def test_delete_job(client):
    _auth_headers(client)
    job = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD).json()
    del_resp = client.delete(f"/api/jobs/{job['id']}")
    assert del_resp.status_code == 204
    assert client.get(f"/api/jobs/{job['id']}").status_code == 404


# ---------------------------------------------------------------------------
# Machine CRUD + conflict check
# ---------------------------------------------------------------------------

def test_create_machine(client):
    _auth_headers(client)
    resp = client.post("/api/machines", json={
        "name": "Haas VF-2", "machine_type": "VMC", "is_available": True
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["machine_type"] == "VMC"
    assert data["is_available"] is True


def test_check_conflict_no_match(client):
    _auth_headers(client)
    resp = client.get("/api/machines/check-conflict?required_machine_type=EDM_WIRE_XYZ_NONEXISTENT")
    assert resp.status_code == 200
    assert resp.json()["conflict"] is True


def test_check_conflict_with_available_machine(client):
    _auth_headers(client)
    client.post("/api/machines", json={
        "name": "EDM-01", "machine_type": "EDM_WIRE_UNIQUE_TYPE", "is_available": True
    })
    resp = client.get("/api/machines/check-conflict?required_machine_type=EDM_WIRE_UNIQUE_TYPE")
    assert resp.status_code == 200
    data = resp.json()
    assert data["conflict"] is False
    assert len(data["available_machines"]) >= 1


# ---------------------------------------------------------------------------
# Contract schema validation
# ---------------------------------------------------------------------------

def test_cam_import_validates_against_json_schema():
    """CAMImport Pydantic model output must validate against contracts/cam_setup_schema_v1.json."""
    try:
        import jsonschema  # type: ignore
    except ImportError:
        pytest.skip("jsonschema not installed — run: pip install jsonschema")

    schema_path = os.path.join(
        os.path.dirname(__file__), "..", "contracts", "cam_setup_schema_v1.json"
    )
    with open(schema_path) as f:
        schema = json.load(f)

    from models.schemas import CAMImport
    instance = CAMImport(**_CAM_PAYLOAD)
    jsonschema.validate(instance.model_dump(), schema)
