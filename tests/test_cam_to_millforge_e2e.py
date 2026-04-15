"""
tests/test_cam_to_millforge_e2e.py — End-to-end: NC file → ARIA bridge → MillForge schedule.

Simulates the full lights-out handoff:
  1. ARIA-OS produces a validated NC file in cam_output/
  2. ARIA posts the bundle (pre-CAM metadata) → MillForge creates pending_cam job
  3. ARIA posts the full CAM submission (with toolpath_file) → MillForge queues the job
  4. MillForge status endpoint confirms the job is scheduled
  5. MillForge feedback endpoint confirms the round-trip loop

These tests use known-good NC files from cam_output/ as stand-ins for real
Fusion 360 output, closing the MillForge side of the lights-out chain without
requiring Fusion 360 to run headlessly in CI.

Run with: pytest tests/test_cam_to_millforge_e2e.py -v
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "millforge-aria-common"))

# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CAM_OUTPUT = _REPO_ROOT / "cam_output"

_BRACKET_NC = "cam_output/bracket_100x60x40_al6061.nc"

_ARIA_RUN_ID    = "e2e-test-bracket-run-001"
_ARIA_JOB_ID    = "e2e-test-bracket-job-001"
_PART_NAME      = "Bracket 100x60x40mm AL6061"
_GEOMETRY_HASH  = "a" * 64   # deterministic placeholder


def _bundle_payload(run_id: str = _ARIA_RUN_ID) -> dict:
    return {
        "schema_version": "1.0",
        "run_id": run_id,
        "goal": "aluminum bracket 100x60x40mm with 4 M6 bolt holes",
        "part_name": _PART_NAME,
        "step_path": "/aria/outputs/runs/e2e-test/part.step",
        "stl_path": "/aria/outputs/runs/e2e-test/part.stl",
        "geometry_hash": None,
        "material": "aluminum",
        "validation": {
            "geometry_passed": True,
            "visual_passed": True,
            "visual_confidence": 0.93,
            "dfm_score": 88.0,
            "dfm_process": "cnc_milling",
            "watertight": True,
        },
        "priority": 5,
    }


def _cam_payload(aria_job_id: str = _ARIA_JOB_ID) -> dict:
    return {
        "schema_version": "1.0",
        "aria_job_id": aria_job_id,
        "part_name": _PART_NAME,
        "geometry_hash": _GEOMETRY_HASH,
        "geometry_file": "s3://aria-jobs/e2e-bracket.stl",
        "toolpath_file": _BRACKET_NC,          # path to known-good NC file
        "material": "aluminum",
        "material_spec": {
            "material_name": "6061-T6 Aluminum",
            "material_family": "aluminum",
        },
        "required_operations": ["milling", "drilling", "tapping"],
        "tolerance_class": "medium",
        "simulation_results": {
            "estimated_cycle_time_minutes": 55.0,
            "collision_detected": False,
            "simulation_confidence": 0.91,
        },
        "validation_passed": True,
        "estimated_cycle_time_minutes": 55.0,
        "quantity": 1,
        "priority": 5,
        "extra": {"aria_run_id": _ARIA_RUN_ID},
    }


# ---------------------------------------------------------------------------
# NC file sanity checks (no HTTP — pure filesystem)
# ---------------------------------------------------------------------------

class TestNCFileSanity:
    """Confirm sample NC files in cam_output/ are valid before submitting them."""

    def test_bracket_nc_exists(self):
        p = _CAM_OUTPUT / "bracket_100x60x40_al6061.nc"
        assert p.exists(), f"Sample NC file missing: {p}"

    def test_bracket_nc_not_empty(self):
        p = _CAM_OUTPUT / "bracket_100x60x40_al6061.nc"
        assert p.stat().st_size > 100

    def test_bracket_nc_has_program_start(self):
        text = (_CAM_OUTPUT / "bracket_100x60x40_al6061.nc").read_text(encoding="utf-8")
        assert text.strip().startswith("%"), "NC file must start with % (EIA standard)"

    def test_bracket_nc_has_m30_end(self):
        text = (_CAM_OUTPUT / "bracket_100x60x40_al6061.nc").read_text(encoding="utf-8")
        assert "M30" in text, "NC file must contain M30 (program end)"

    def test_bracket_nc_has_tool_changes(self):
        text = (_CAM_OUTPUT / "bracket_100x60x40_al6061.nc").read_text(encoding="utf-8")
        assert "M06" in text, "NC file must have at least one tool change (M06)"

    def test_bracket_nc_has_g54_work_offset(self):
        text = (_CAM_OUTPUT / "bracket_100x60x40_al6061.nc").read_text(encoding="utf-8")
        assert "G54" in text, "NC file must reference work coordinate offset G54"


# ---------------------------------------------------------------------------
# Full bridge integration tests
# ---------------------------------------------------------------------------

class TestARIAToMillForgePipeline:
    """
    End-to-end: ARIA bundle → CAM submission → status poll → feedback push.
    Each test is self-contained using the function-scoped in-memory client.
    """

    def test_bundle_then_cam_submission(self, client):
        """Bundle registers the part; full CAM submission queues it for machining."""
        # Step 1: ARIA posts pre-CAM bundle
        bundle_resp = client.post("/api/aria/bundle", json=_bundle_payload())
        assert bundle_resp.status_code == 200, bundle_resp.text
        bundle_data = bundle_resp.json()
        assert bundle_data["status"] == "pending_cam"
        assert bundle_data["duplicate"] is False
        mf_job_id = bundle_data["millforge_job_id"]
        assert mf_job_id > 0

        # Step 2: ARIA completes CAM → posts full submission
        cam_resp = client.post("/api/jobs/from-aria", json=_cam_payload())
        assert cam_resp.status_code == 200, cam_resp.text
        cam_data = cam_resp.json()
        assert cam_data["status"] == "queued"
        assert cam_data["millforge_job_id"] > 0

    def test_status_reflects_queued_after_cam_submit(self, client):
        """After CAM submission, bridge status endpoint reports the job as queued."""
        client.post("/api/jobs/from-aria", json=_cam_payload())
        resp = client.get(f"/api/bridge/status/{_ARIA_JOB_ID}")
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["aria_job_id"] == _ARIA_JOB_ID
        assert data["stage"] == "queued"
        assert data["material"] == "aluminum"

    def test_feedback_round_trip(self, client):
        """
        After machining completes, MillForge pushes actual cycle time back to ARIA.
        Validates the full lights-out feedback loop.
        """
        client.post("/api/jobs/from-aria", json=_cam_payload())

        # Simulate post-machining feedback (actual 58 min vs estimated 55 min)
        feedback_resp = client.post("/api/bridge/feedback", json={
            "aria_job_id": _ARIA_JOB_ID,
            "actual_cycle_time_minutes": 58.0,
            "qc_passed": True,
            "defects_found": [],
            "defect_confidence_scores": [],
        })
        assert feedback_resp.status_code == 200, feedback_resp.text
        fb = feedback_resp.json()
        assert fb["feedback_stored"] is True
        assert fb["estimated_cycle_time_minutes"] == 55.0
        # Delta: 55 - 58 = -3 (actual took longer)
        assert abs(fb["cycle_time_delta_minutes"] - (-3.0)) < 0.01
        # Accuracy: 58/55 * 100 ≈ 105.5%
        assert fb["cycle_time_accuracy_pct"] == pytest.approx(105.5, abs=0.2)

        # Retrieve and verify stored feedback
        get_resp = client.get(f"/api/bridge/feedback/{_ARIA_JOB_ID}")
        assert get_resp.status_code == 200
        stored = get_resp.json()["feedback"]
        assert stored["qc_passed"] is True
        assert stored["actual_cycle_time_minutes"] == 58.0

    def test_bundle_idempotent_cam_not_idempotent(self, client):
        """
        Bundle is idempotent (same run_id returns existing job).
        Full CAM submission with same aria_job_id is also idempotent.
        """
        # Submit bundle twice
        r1 = client.post("/api/aria/bundle", json=_bundle_payload("e2e-idem-run-001"))
        r2 = client.post("/api/aria/bundle", json=_bundle_payload("e2e-idem-run-001"))
        assert r1.json()["millforge_job_id"] == r2.json()["millforge_job_id"]
        assert r2.json()["duplicate"] is True

        # Submit CAM twice with same aria_job_id
        cam = {**_cam_payload("e2e-idem-cam-001")}
        c1 = client.post("/api/jobs/from-aria", json=cam)
        c2 = client.post("/api/jobs/from-aria", json=cam)
        assert c1.json()["millforge_job_id"] == c2.json()["millforge_job_id"]
        assert c2.json()["duplicate"] is True
