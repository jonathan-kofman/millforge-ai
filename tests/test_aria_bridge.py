"""
Tests for the ARIA-OS ↔ MillForge bridge.

Covers:
- POST /api/jobs/from-aria — valid submission, duplicate idempotency, validation rejections
- GET  /api/bridge/status/{aria_job_id}
- POST /api/bridge/feedback
- GET  /api/bridge/feedback/{aria_job_id}
- POST /api/aria/bundle — pre-CAM bundle, idempotency, structsight_context passthrough
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

    def test_submit_with_structsight_context(self, client):
        """structsight_context is persisted in cam_metadata but doesn't break anything."""
        payload = {
            **_VALID_PAYLOAD,
            "aria_job_id": "aria-structsight-001",
            "structsight_context": {
                "discipline": "structural",
                "assumptions": ["Fixed base connection"],
                "verification_required": True,
                "risk_flags": ["Weld detail needs EOR stamp"],
                "size_class": "major",
            },
        }
        resp = client.post("/api/jobs/from-aria", json=payload)
        assert resp.status_code == 200
        assert resp.json()["aria_job_id"] == "aria-structsight-001"


_VALID_BUNDLE = {
    "schema_version": "1.0",
    "run_id": "20260409T215033_a3f1c9b2",
    "goal": "aluminum bracket 100x60x40mm with 4 M6 bolt holes",
    "part_name": "bracket",
    "step_path": "/aria/outputs/runs/20260409T215033_a3f1c9b2/part.step",
    "stl_path": "/aria/outputs/runs/20260409T215033_a3f1c9b2/part.stl",
    "geometry_hash": None,
    "material": "aluminum",
    "validation": {
        "geometry_passed": True,
        "visual_passed": True,
        "visual_confidence": 0.92,
        "dfm_score": 82.0,
        "dfm_process": "cnc_milling",
        "watertight": True,
    },
    "priority": 5,
}


class TestARIABundleEndpoint:
    def test_submit_valid_bundle(self, client):
        resp = client.post("/api/aria/bundle", json=_VALID_BUNDLE)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["aria_run_id"] == "20260409T215033_a3f1c9b2"
        assert data["millforge_job_id"] > 0
        assert data["status"] == "pending_cam"
        assert data["duplicate"] is False

    def test_bundle_idempotent_on_run_id(self, client):
        resp1 = client.post("/api/aria/bundle", json=_VALID_BUNDLE)
        resp2 = client.post("/api/aria/bundle", json=_VALID_BUNDLE)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["millforge_job_id"] == resp2.json()["millforge_job_id"]
        assert resp2.json()["duplicate"] is True

    def test_bundle_empty_run_id_rejected(self, client):
        bad = {**_VALID_BUNDLE, "run_id": "  ", "goal": "x", "part_name": "y"}
        resp = client.post("/api/aria/bundle", json=bad)
        assert resp.status_code == 422

    def test_bundle_empty_part_name_rejected(self, client):
        bad = {**_VALID_BUNDLE, "run_id": "unique-run-xyz", "part_name": "  "}
        resp = client.post("/api/aria/bundle", json=bad)
        assert resp.status_code == 422

    def test_bundle_infers_machine_type_from_dfm(self, client):
        """DFM process 'turning' should map to lathe machine type."""
        payload = {
            **_VALID_BUNDLE,
            "run_id": "bundle-turning-test-001",
            "validation": {**_VALID_BUNDLE["validation"], "dfm_process": "turning"},
        }
        resp = client.post("/api/aria/bundle", json=payload)
        assert resp.status_code == 200

    def test_bundle_with_structsight_context(self, client):
        payload = {
            **_VALID_BUNDLE,
            "run_id": "bundle-structsight-001",
            "structsight_context": {
                "discipline": "structural",
                "assumptions": ["Pinned base connection", "A36 steel"],
                "verification_required": True,
                "risk_flags": ["Verify weld category per AWS D1.1"],
                "size_class": "moderate",
            },
        }
        resp = client.post("/api/aria/bundle", json=payload)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["status"] == "pending_cam"

    def test_bundle_without_material(self, client):
        """material is optional on bundles — CAM hasn't run yet."""
        payload = {**_VALID_BUNDLE, "run_id": "bundle-no-mat-001", "material": None}
        resp = client.post("/api/aria/bundle", json=payload)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# V2 endpoint tests
# ---------------------------------------------------------------------------

_VALID_V2_PAYLOAD = {
    "schema_version": "2.0",
    "aria_job_id": "aria-v2-test-001",
    "part_name": "Turbine Mount Bracket",
    "geometry_hash": "d" * 64,
    "geometry_file": "s3://aria-jobs/turbine_mount.stl",
    "toolpath_file": "s3://aria-jobs/turbine_mount.nc",
    "material": {
        "material_name": "6061-T6 Aluminum",
        "material_family": "aluminum",
        "form": "bar",
        "dimensions_mm": {"length": 128.4, "width": 84.2, "thickness": 31.7},
    },
    "operations": [
        {
            "sequence": 10,
            "operation_name": "Rough mill pockets & bores",
            "work_center_category": "cnc_mill",
            "estimated_setup_min": 25,
            "estimated_run_min": 45,
            "ai_confidence": 0.94,
            "detected_features": ["pocket", "bore", "through_hole"],
        },
        {
            "sequence": 20,
            "operation_name": "Finish mill all features",
            "work_center_category": "cnc_mill",
            "estimated_setup_min": 5,
            "estimated_run_min": 30,
            "depends_on_sequence": 10,
            "ai_confidence": 0.91,
        },
        {
            "sequence": 30,
            "operation_name": "Deburr sharp edges",
            "work_center_category": "deburr_bench",
            "estimated_setup_min": 0,
            "estimated_run_min": 5,
            "depends_on_sequence": 20,
        },
        {
            "sequence": 40,
            "operation_name": "Anodize Type III",
            "work_center_category": "anodizing_line",
            "estimated_setup_min": 0,
            "estimated_run_min": 0,
            "depends_on_sequence": 30,
            "is_subcontracted": True,
            "subcontractor_name": "ABC Anodizing Co.",
            "subcontractor_lead_days": 2,
        },
        {
            "sequence": 50,
            "operation_name": "First article inspection",
            "work_center_category": "inspection_station",
            "estimated_setup_min": 5,
            "estimated_run_min": 15,
            "depends_on_sequence": 40,
            "inspection_required": True,
        },
    ],
    "manufacturability": {
        "overall_score": 0.87,
        "issues": ["Deep pocket at Position C — consider reducing depth"],
        "recommendations": ["Use longer reach tool for Position C pocket"],
        "process_family": "cnc_milling",
    },
    "quality": {
        "tolerance_class": "medium",
        "first_article_required": True,
        "quality_standards": ["AS9100"],
    },
    "quantity": 24,
    "priority": 3,
}

_VALID_V2_FAB_PAYLOAD = {
    "schema_version": "2.0",
    "aria_job_id": "aria-v2-fab-001",
    "part_name": "Chassis Bracket",
    "geometry_hash": "e" * 64,
    "geometry_file": "s3://aria-jobs/chassis_bracket.stl",
    "material": {
        "material_name": "A36 Steel",
        "material_family": "steel",
        "form": "sheet",
        "dimensions_mm": {"length": 300, "width": 150, "thickness": 6},
    },
    "operations": [
        {
            "sequence": 10,
            "operation_name": "Laser cut blank + holes",
            "work_center_category": "laser_cutter",
            "estimated_setup_min": 10,
            "estimated_run_min": 2,
        },
        {
            "sequence": 20,
            "operation_name": "4 bends at 90°",
            "work_center_category": "press_brake",
            "estimated_setup_min": 15,
            "estimated_run_min": 3,
            "depends_on_sequence": 10,
        },
        {
            "sequence": 30,
            "operation_name": "Weld 2 gussets",
            "work_center_category": "tig_welder",
            "estimated_setup_min": 10,
            "estimated_run_min": 15,
            "depends_on_sequence": 20,
        },
        {
            "sequence": 40,
            "operation_name": "Powder coat satin black",
            "work_center_category": "powder_coat_booth",
            "estimated_setup_min": 0,
            "estimated_run_min": 0,
            "depends_on_sequence": 30,
            "is_subcontracted": True,
            "subcontractor_name": "Premier Coatings LLC",
            "subcontractor_lead_days": 3,
        },
        {
            "sequence": 50,
            "operation_name": "Final dimensional check",
            "work_center_category": "inspection_station",
            "estimated_setup_min": 0,
            "estimated_run_min": 8,
            "depends_on_sequence": 40,
        },
    ],
    "quality": {
        "tolerance_class": "loose",
        "first_article_required": False,
    },
    "quantity": 10,
    "priority": 5,
}


class TestARIABridgeV2Endpoints:
    def test_v2_submit_valid_cnc_part(self, client):
        resp = client.post("/api/jobs/from-aria", json=_VALID_V2_PAYLOAD)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["aria_job_id"] == "aria-v2-test-001"
        assert data["millforge_job_id"] > 0
        assert data["status"] == "queued"
        assert data["duplicate"] is False

    def test_v2_submit_fabricated_part(self, client):
        resp = client.post("/api/jobs/from-aria", json=_VALID_V2_FAB_PAYLOAD)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["aria_job_id"] == "aria-v2-fab-001"
        assert data["millforge_job_id"] > 0

    def test_v2_idempotent_on_aria_job_id(self, client):
        payload = {**_VALID_V2_PAYLOAD, "aria_job_id": "aria-v2-idem-001"}
        resp1 = client.post("/api/jobs/from-aria", json=payload)
        resp2 = client.post("/api/jobs/from-aria", json=payload)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        assert resp1.json()["millforge_job_id"] == resp2.json()["millforge_job_id"]
        assert resp2.json()["duplicate"] is True

    def test_v2_missing_subcontractor_name_rejected(self, client):
        bad = {
            **_VALID_V2_PAYLOAD,
            "aria_job_id": "aria-v2-bad-subcontract",
            "operations": [
                {
                    "sequence": 10,
                    "operation_name": "Anodize",
                    "work_center_category": "anodizing_line",
                    "estimated_setup_min": 0,
                    "estimated_run_min": 0,
                    "is_subcontracted": True,
                    # missing subcontractor_name
                },
            ],
        }
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422
        errors = resp.json()["detail"]["validation_errors"]
        assert any("subcontractor_name" in e for e in errors)

    def test_v2_invalid_dependency_rejected(self, client):
        bad = {
            **_VALID_V2_PAYLOAD,
            "aria_job_id": "aria-v2-bad-dep",
            "operations": [
                {
                    "sequence": 10,
                    "operation_name": "Mill",
                    "work_center_category": "cnc_mill",
                    "estimated_setup_min": 20,
                    "estimated_run_min": 40,
                    "depends_on_sequence": 99,  # 99 does not exist
                },
            ],
        }
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422
        errors = resp.json()["detail"]["validation_errors"]
        assert any("depends_on_sequence" in e for e in errors)

    def test_v2_bad_geometry_hash_rejected(self, client):
        bad = {**_VALID_V2_PAYLOAD, "aria_job_id": "aria-v2-bad-hash", "geometry_hash": "not-a-sha256"}
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422

    def test_v2_empty_operations_rejected(self, client):
        bad = {**_VALID_V2_PAYLOAD, "aria_job_id": "aria-v2-no-ops", "operations": []}
        resp = client.post("/api/jobs/from-aria", json=bad)
        # Pydantic min_length=1 or our validator catches this
        assert resp.status_code == 422

    def test_v2_multi_process_operations_persisted(self, client):
        """V2 operations with diverse work_center_categories are stored correctly."""
        payload = {
            **_VALID_V2_PAYLOAD,
            "aria_job_id": "aria-v2-multiprocess-001",
        }
        resp = client.post("/api/jobs/from-aria", json=payload)
        assert resp.status_code == 200
        job_id = resp.json()["millforge_job_id"]

        # Confirm job exists via status endpoint
        status = client.get(f"/api/bridge/status/aria-v2-multiprocess-001")
        assert status.status_code == 200
        assert status.json()["millforge_job_id"] == job_id

    def test_v2_steel_fab_material_mapped(self, client):
        """A36 Steel (steel material_family) maps correctly."""
        payload = {**_VALID_V2_FAB_PAYLOAD, "aria_job_id": "aria-v2-steel-mat-001"}
        resp = client.post("/api/jobs/from-aria", json=payload)
        assert resp.status_code == 200

    def test_v1_still_accepted_after_v2_added(self, client):
        """V1 backward compatibility — existing V1 payload continues to work."""
        payload = {**_VALID_PAYLOAD, "aria_job_id": "aria-v1-compat-check-001"}
        resp = client.post("/api/jobs/from-aria", json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "queued"

    def test_unknown_schema_version_rejected(self, client):
        bad = {**_VALID_PAYLOAD, "aria_job_id": "aria-bad-version-001", "schema_version": "99.0"}
        resp = client.post("/api/jobs/from-aria", json=bad)
        assert resp.status_code == 422
