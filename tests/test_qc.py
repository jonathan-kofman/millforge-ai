"""
Tests for QC inspection stage — POST /api/jobs/{id}/qc-submit,
GET /api/jobs/{id}/qc-results, and GET /api/analytics/qc.

The ONNX model is not present in CI, so all tests exercise the
model_not_deployed fallback path (passed=True, defects_found=[]).
"""

import io
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# ---------------------------------------------------------------------------
# Shared CAM payload and auth helper (mirrors test_jobs.py)
# ---------------------------------------------------------------------------

_CAM_PAYLOAD = {
    "schema_version": "1.0",
    "part_id": "ARIA-QC-001",
    "machine_name": "Haas VF-2",
    "tools": [{"tool_number": 1, "description": "3/8 End Mill", "diameter_mm": 9.5}],
    "stock_dims": {"length_mm": 100.0, "width_mm": 50.0, "height_mm": 20.0},
    "cycle_time_min_estimate": 30.0,
    "second_op_required": False,
    "work_offset_recommendation": "G54",
    "fixturing_suggestion": "Kurt vise",
    "generated_at": "2024-01-01T08:00:00",
    "material": "aluminum",
}

# Minimal 1×1 white JPEG (48 bytes, valid image)
_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1edB"
    b"\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00"
    b"\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01\x01\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07\x08\t\n\x0b"
    b"\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xfb\xff\xd9"
)


def _auth(client) -> dict:
    client.post("/api/auth/register", json={
        "email": "qc_test@example.com",
        "password": "testpass123",
        "name": "QC Tester",
    })
    client.post("/api/auth/login", json={
        "email": "qc_test@example.com",
        "password": "testpass123",
    })
    return {}


def _create_job(client) -> dict:
    resp = client.post("/api/jobs/import-from-cam", json=_CAM_PAYLOAD)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _advance_to_qc_pending(client, job_id: int):
    """Move job through queued → in_progress → qc_pending."""
    client.patch(f"/api/jobs/{job_id}", json={"stage": "in_progress"})
    client.patch(f"/api/jobs/{job_id}", json={"stage": "qc_pending"})


def _upload_image(client, job_id: int, image_bytes: bytes = _TINY_JPEG) -> dict:
    resp = client.post(
        f"/api/jobs/{job_id}/qc-submit",
        files={"image": ("surface.jpg", io.BytesIO(image_bytes), "image/jpeg")},
    )
    return resp


# ---------------------------------------------------------------------------
# QC submit — happy path (model_not_deployed fallback)
# ---------------------------------------------------------------------------

def test_qc_submit_happy_path(client):
    _auth(client)
    job = _create_job(client)
    _advance_to_qc_pending(client, job["id"])

    resp = _upload_image(client, job["id"])
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert "id" in data
    assert data["job_id"] == job["id"]
    assert isinstance(data["passed"], bool)
    assert isinstance(data["defects_found"], list)
    assert isinstance(data["confidence_scores"], list)


def test_qc_submit_from_in_progress(client):
    """QC submit is also valid when job is in_progress (not only qc_pending)."""
    _auth(client)
    job = _create_job(client)
    client.patch(f"/api/jobs/{job['id']}", json={"stage": "in_progress"})

    resp = _upload_image(client, job["id"])
    assert resp.status_code == 201, resp.text


def test_qc_submit_advances_stage_to_complete(client):
    """Model-not-deployed path always returns passed=True → stage becomes complete."""
    _auth(client)
    job = _create_job(client)
    _advance_to_qc_pending(client, job["id"])

    _upload_image(client, job["id"])

    updated = client.get(f"/api/jobs/{job['id']}").json()
    # model_not_deployed returns passed=True → stage must be complete
    assert updated["stage"] == "complete"


def test_qc_submit_rejects_wrong_stage(client):
    """Submitting QC on a queued job should return 400."""
    _auth(client)
    job = _create_job(client)
    # job is still 'queued'

    resp = _upload_image(client, job["id"])
    assert resp.status_code == 400
    assert "stage" in resp.json()["detail"].lower()


def test_qc_submit_rejects_empty_image(client):
    _auth(client)
    job = _create_job(client)
    _advance_to_qc_pending(client, job["id"])

    resp = client.post(
        f"/api/jobs/{job['id']}/qc-submit",
        files={"image": ("empty.jpg", io.BytesIO(b""), "image/jpeg")},
    )
    assert resp.status_code == 400


def test_qc_submit_404_on_missing_job(client):
    _auth(client)
    resp = _upload_image(client, 99999999)
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/jobs/{id}/qc-results
# ---------------------------------------------------------------------------

def test_get_qc_results_empty(client):
    _auth(client)
    job = _create_job(client)

    resp = client.get(f"/api/jobs/{job['id']}/qc-results")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_qc_results_after_submit(client):
    _auth(client)
    job = _create_job(client)
    _advance_to_qc_pending(client, job["id"])
    _upload_image(client, job["id"])

    resp = client.get(f"/api/jobs/{job['id']}/qc-results")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) == 1
    assert results[0]["job_id"] == job["id"]


def test_get_qc_results_404_on_missing_job(client):
    _auth(client)
    resp = client.get("/api/jobs/99999999/qc-results")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/analytics/qc
# ---------------------------------------------------------------------------

def test_qc_analytics_empty(client):
    _auth(client)
    resp = client.get("/api/analytics/qc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_inspections"] == 0
    assert data["overall_pass_rate_percent"] == 0.0
    assert data["by_machine_type"] == []
    assert data["by_material"] == []


def test_qc_analytics_after_inspection(client):
    _auth(client)
    job = _create_job(client)
    _advance_to_qc_pending(client, job["id"])
    _upload_image(client, job["id"])

    resp = client.get("/api/analytics/qc")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_inspections"] == 1
    assert data["overall_pass_rate_percent"] == 100.0
    assert len(data["by_machine_type"]) >= 1
    assert len(data["by_material"]) >= 1


def test_qc_analytics_groups_by_machine_type(client):
    _auth(client)

    # Job 1: Haas VF-2 / aluminum
    job1 = _create_job(client)
    _advance_to_qc_pending(client, job1["id"])
    _upload_image(client, job1["id"])

    # Job 2: different machine name → patch after creation
    job2 = _create_job(client)
    client.patch(f"/api/jobs/{job2['id']}", json={"stage": "in_progress", "required_machine_type": "Mazak HCN-5000"})
    client.patch(f"/api/jobs/{job2['id']}", json={"stage": "qc_pending"})
    _upload_image(client, job2["id"])

    resp = client.get("/api/analytics/qc")
    data = resp.json()
    assert data["total_inspections"] == 2
    machine_types = [item["value"] for item in data["by_machine_type"]]
    # Both machine types should appear
    assert len(machine_types) == 2
