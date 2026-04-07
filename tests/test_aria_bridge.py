"""
Tests for the ARIA-OS ↔ MillForge bridge.

Covers:
- POST /api/jobs/from-aria — valid submission, duplicate idempotency, validation rejections
- GET  /api/bridge/status/{aria_job_id}
- POST /api/bridge/feedback
- GET  /api/bridge/feedback/{aria_job_id}
- Shared-package validation (millforge_aria_common)

Run with: pytest tests/test_aria_bridge.py -v
"""

import sys
import os
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "millforge-aria-common"))


# ---------------------------------------------------------------------------
# Shared package tests (no HTTP — pure Python)
# ---------------------------------------------------------------------------

class TestSharedPackageModels:
    def test_to_millforge_material_mapping(self):
        from millforge_aria_common.models import ARIAMaterialSpec

        assert ARIAMaterialSpec("6061-T6 Aluminum", "aluminum").to_millforge_material() == "aluminum"
        assert ARIAMaterialSpec("304 SS", "stainless").to_millforge_material() == "steel"
        assert ARIAMaterialSpec("Ti-6Al-4V", "titanium").to_millforge_material() == "titanium"
        assert ARIAMaterialSpec("C360 Brass", "brass").to_millforge_material() == "copper"

    def test_aria_job_to_dict_round_trip(self):
        from millforge_aria_common.models import (
            ARIAToMillForgeJob, ARIAMaterialSpec, ARIASimulationResults,
            ToleranceClass, OperationType,
        )

        job = ARIAToMillForgeJob(
            aria_job_id="test-uuid-001",
            part_name="Bracket A",
            geometry_hash="a" * 64,
            geometry_file="s3://aria-jobs/bracket.stl",
            toolpath_file="s3://aria-jobs/bracket.nc",
            material="aluminum",
            material_spec=ARIAMaterialSpec("6061-T6", "aluminum"),
            required_operations=[OperationType.MILLING, OperationType.DRILLING],
            tolerance_class=ToleranceClass.MEDIUM,
            simulation_results=ARIASimulationResults(
                estimated_cycle_time_minutes=45.0,
                simulation_confidence=0.92,
            ),
            validation_passed=True,
            estimated_cycle_time_minutes=45.0,
        )

        d = job.to_dict()
        assert d["aria_job_id"] == "test-uuid-001"
        assert d["material"] == "aluminum"
        assert d["simulation_results"]["estimated_cycle_time_minutes"] == 45.0
        assert d["required_operations"] == ["milling", "drilling"]
        assert d["tolerance_class"] == "medium"

    def test_feedback_to_dict(self):
        from millforge_aria_common.models import ARIAJobFeedback

        fb = ARIAJobFeedback(
            aria_job_id="test-uuid-001",
            millforge_job_id=42,
            part_name="Bracket A",
            completed_at=datetime.now(timezone.utc),
            actual_cycle_time_minutes=48.5,
            cycle_time_delta_minutes=45.0 - 48.5,
            cycle_time_accuracy_pct=round(48.5 / 45.0 * 100, 1),
            qc_passed=True,
            defects_found=[],
        )
        d = fb.to_dict()
        assert d["qc_passed"] is True
        assert d["actual_cycle_time_minutes"] == 48.5


class TestSharedPackageValidation:
    def _make_valid_job(self):
        from millforge_aria_common.models import (
            ARIAToMillForgeJob, ARIAMaterialSpec, ARIASimulationResults,
            ToleranceClass, OperationType,
        )
        return ARIAToMillForgeJob(
            aria_job_id="uuid-valid",
            part_name="Shaft",
            geometry_hash="b" * 64,
            geometry_file="s3://bucket/shaft.stl",
            toolpath_file="s3://bucket/shaft.nc",
            material="steel",
            material_spec=ARIAMaterialSpec("4140 Steel", "steel"),
            required_operations=[OperationType.TURNING],
            tolerance_class=ToleranceClass.FINE,
            simulation_results=ARIASimulationResults(
                estimated_cycle_time_minutes=30.0,
                collision_detected=False,
                simulation_confidence=0.95,
            ),
            validation_passed=True,
            estimated_cycle_time_minutes=30.0,
        )

    def test_valid_job_passes(self):
        from millforge_aria_common.validation import validate_aria_job
        validate_aria_job(self._make_valid_job())  # must not raise

    def test_collision_detected_rejected(self):
        from millforge_aria_common.validation import validate_aria_job, ValidationError
        from millforge_aria_common.models import ARIASimulationResults

        job = self._make_valid_job()
        job.simulation_results = ARIASimulationResults(
            estimated_cycle_time_minutes=30.0,
            collision_detected=True,
        )
        with pytest.raises(ValidationError) as exc_info:
            validate_aria_job(job)
        assert any("collision_detected" in e for e in exc_info.value.errors)

    def test_bad_geometry_hash_rejected(self):
        from millforge_aria_common.validation import validate_aria_job, ValidationError

        job = self._make_valid_job()
        job.geometry_hash = "not-a-sha256"
        with pytest.raises(ValidationError) as exc_info:
            validate_aria_job(job)
        assert any("geometry_hash" in e for e in exc_info.value.errors)

    def test_invalid_material_rejected(self):
        from millforge_aria_common.validation import validate_aria_job, ValidationError

        job = self._make_valid_job()
        job.material = "unobtainium"
        with pytest.raises(ValidationError) as exc_info:
            validate_aria_job(job)
        assert any("material" in e for e in exc_info.value.errors)

    def test_validation_passed_false_rejected(self):
        from millforge_aria_common.validation import validate_aria_job, ValidationError

        job = self._make_valid_job()
        job.validation_passed = False
        with pytest.raises(ValidationError) as exc_info:
            validate_aria_job(job)
        assert any("validation_passed" in e for e in exc_info.value.errors)

    def test_all_errors_surfaced_at_once(self):
        from millforge_aria_common.validation import validate_aria_job, ValidationError
        from millforge_aria_common.models import ARIASimulationResults

        job = self._make_valid_job()
        job.geometry_hash = "bad"
        job.material = "unobtainium"
        job.simulation_results = ARIASimulationResults(
            estimated_cycle_time_minutes=30.0,
            collision_detected=True,
        )
        job.validation_passed = False

        with pytest.raises(ValidationError) as exc_info:
            validate_aria_job(job)
        # Should surface all 4 errors, not just the first
        assert len(exc_info.value.errors) >= 3

    def test_compute_geometry_hash(self):
        from millforge_aria_common.validation import compute_geometry_hash
        import hashlib

        data = b"fake stl bytes"
        expected = hashlib.sha256(data).hexdigest()
        assert compute_geometry_hash(data) == expected


# ---------------------------------------------------------------------------
# HTTP endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    from main import app
    from database import Base, engine
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


_VALID_PAYLOAD = {
    "schema_version": "1.0",
    "aria_job_id": "aria-test-001",
    "part_name": "Test Bracket",
    "geometry_hash": "c" * 64,
    "geometry_file": "s3://test/bracket.stl",
    "toolpath_file": "s3://test/bracket.nc",
    "material": "aluminum",
    "material_spec": {
        "material_name": "6061-T6 Aluminum",
        "material_family": "aluminum",
    },
    "required_operations": ["milling", "drilling"],
    "tolerance_class": "medium",
    "simulation_results": {
        "estimated_cycle_time_minutes": 45.0,
        "collision_detected": False,
        "simulation_confidence": 0.92,
    },
    "validation_passed": True,
    "estimated_cycle_time_minutes": 45.0,
    "quantity": 1,
    "priority": 5,
}


class TestARIABridgeEndpoints:
    def test_submit_valid_job(self, client):
        resp = client.post("/api/jobs/from-aria", json=_VALID_PAYLOAD)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["aria_job_id"] == "aria-test-001"
        assert data["millforge_job_id"] > 0
        assert data["status"] == "queued"

    def test_submit_duplicate_is_idempotent(self, client):
        resp1 = client.post("/api/jobs/from-aria", json=_VALID_PAYLOAD)
        resp2 = client.post("/api/jobs/from-aria", json=_VALID_PAYLOAD)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Same millforge_job_id returned both times
        assert resp1.json()["millforge_job_id"] == resp2.json()["millforge_job_id"]
        assert resp2.json()["duplicate"] is True

    def test_submit_collision_detected_rejected(self, client):
        bad = {**_VALID_PAYLOAD, "aria_job_id": "aria-collision-test"}
        bad["simulation_results"] = {**bad["simulation_results"], "collision_detected": True}
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422
        errors = resp.json()["detail"]["validation_errors"]
        assert any("collision_detected" in e for e in errors)

    def test_submit_validation_not_passed_rejected(self, client):
        bad = {**_VALID_PAYLOAD, "aria_job_id": "aria-val-false", "validation_passed": False}
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422

    def test_submit_invalid_material_rejected(self, client):
        bad = {**_VALID_PAYLOAD, "aria_job_id": "aria-bad-mat", "material": "unobtainium"}
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422

    def test_get_status_found(self, client):
        # Ensure the job from the first test exists
        resp = client.get("/api/bridge/status/aria-test-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["aria_job_id"] == "aria-test-001"
        assert data["stage"] == "queued"
        assert data["material"] == "aluminum"

    def test_get_status_not_found(self, client):
        resp = client.get("/api/bridge/status/does-not-exist")
        assert resp.status_code == 404

    def test_push_feedback(self, client):
        resp = client.post("/api/bridge/feedback", json={
            "aria_job_id": "aria-test-001",
            "actual_cycle_time_minutes": 48.5,
            "qc_passed": True,
            "defects_found": [],
            "defect_confidence_scores": [],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["feedback_stored"] is True
        assert data["estimated_cycle_time_minutes"] == 45.0
        # Delta should be 45 - 48.5 = -3.5
        assert abs(data["cycle_time_delta_minutes"] - (-3.5)) < 0.01
        assert data["cycle_time_accuracy_pct"] == pytest.approx(107.8, abs=0.2)

    def test_get_feedback_after_push(self, client):
        resp = client.get("/api/bridge/feedback/aria-test-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["feedback"]["qc_passed"] is True
        assert data["feedback"]["actual_cycle_time_minutes"] == 48.5

    def test_get_feedback_no_feedback_yet(self, client):
        # Submit a new job but don't push feedback
        fresh = {**_VALID_PAYLOAD, "aria_job_id": "aria-no-feedback-001"}
        client.post("/api/jobs/from-aria", json=fresh)
        resp = client.get("/api/bridge/feedback/aria-no-feedback-001")
        assert resp.status_code == 404
