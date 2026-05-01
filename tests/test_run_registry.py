"""Tests for the cross-stack run registry — `/api/runs/*` plus the
`services.run_registry` and `services.aria_callback` modules.

Covers:
  * Reading a synthetic outputs/runs/<id>/ tree
  * Joining a MillForge Job tagged with the same aria_run_id
  * Pulling matching events from a synthetic aria_os.floor SQLite
  * Path-traversal guard on the artifact endpoint
  * Closed-loop ARIA callback: enabled/disabled, defect-driven stage_hint
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services import run_registry, aria_callback


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def aria_outputs(tmp_path, monkeypatch):
    """Build a fake aria-os outputs/runs/<run_id>/ directory with a
    realistic run_manifest.json + a couple of artifacts."""
    outputs = tmp_path / "outputs"
    runs = outputs / "runs"
    runs.mkdir(parents=True)

    run_id = "20260501T120000_deadbeef"
    rd = runs / run_id
    rd.mkdir()
    started = time.time() - 600
    completed = time.time() - 60
    manifest = {
        "schema_version": "2.1",
        "run_id": run_id,
        "goal": "build a precision flange",
        "part_name": "flange",
        "part_id": "flange_001",
        "started_at": started,
        "completed_at": completed,
        "success": True,
        "pipeline_stats": {
            "agent_iterations": 2, "wall_time_s": 540.0,
            "success_agent": True, "llm_total_calls": 7,
        },
        "mesh_stats": {"triangle_count": 8420,
                       "bbox_mm": [120.0, 120.0, 21.0],
                       "watertight": True, "volume_cm3": 95.4},
        "operations": [{"sequence": 10,
                        "operation_name": "CNC mill",
                        "work_center_category": "cnc_mill"}],
    }
    (rd / "run_manifest.json").write_text(json.dumps(manifest))
    (rd / "part.step").write_text("ISO-10303-21;\n/* stub */\n")
    (rd / "part.stl").write_bytes(b"solid stub\nendsolid stub\n")
    (rd / "render_iso.png").write_bytes(b"\x89PNG\r\n\x1a\nstub")

    monkeypatch.setenv("ARIA_OUTPUTS_PATH", str(outputs))
    yield {"outputs": outputs, "runs": runs, "run_id": run_id}


@pytest.fixture
def floor_db_with_run(tmp_path, monkeypatch, aria_outputs):
    """Floor SQLite carrying events that mention the same run_id."""
    db_path = tmp_path / "floor.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE machines (id INTEGER PRIMARY KEY, name TEXT,
            controller TEXT, controller_addr TEXT,
            max_x_mm REAL, max_y_mm REAL, max_z_mm REAL,
            max_spindle_rpm INTEGER, kinematics TEXT, created_at REAL);
        CREATE TABLE jobs (id INTEGER PRIMARY KEY, run_id TEXT,
            part_name TEXT, machine_id INTEGER, fixture_id INTEGER,
            gcode_path TEXT, stock_spec_json TEXT, status TEXT,
            queued_at REAL, started_at REAL, completed_at REAL,
            tool_use_log_json TEXT, fault_log_json TEXT,
            output_log_path TEXT);
        CREATE TABLE events (id INTEGER PRIMARY KEY, job_id INTEGER,
            ts REAL, kind TEXT, payload_json TEXT);
    """)
    cur = conn.cursor()
    now = time.time()
    cur.execute("INSERT INTO machines VALUES (1,'HAAS','haas','127.0.0.1',"
                "762,406,508,12000,'3axis',?)", (now - 86400,))
    cur.execute("INSERT INTO jobs (id, run_id, part_name, machine_id, "
                "status, queued_at) VALUES (501, ?, 'flange', 1, "
                "'complete', ?)", (aria_outputs["run_id"], now - 500))
    # An event tagged with the run_id (job_id linked)
    cur.execute("INSERT INTO events (job_id, ts, kind, payload_json) "
                "VALUES (501, ?, 'job_started', ?)",
                (now - 480, json.dumps({"machine_id": 1,
                                        "run_id": aria_outputs["run_id"]})))
    cur.execute("INSERT INTO events (job_id, ts, kind, payload_json) "
                "VALUES (501, ?, 'job_completed', ?)",
                (now - 60, json.dumps({"machine_id": 1, "duration_s": 420})))
    conn.commit()
    conn.close()

    monkeypatch.setenv("ARIA_FLOOR_DB_PATH", str(db_path))
    yield db_path


def _login(client, email: str = "runs_user@example.com") -> None:
    client.post("/api/auth/register", json={
        "email": email, "password": "testpass123", "name": "Runs User"})
    client.post("/api/auth/login", json={
        "email": email, "password": "testpass123"})


# ---------------------------------------------------------------------------
# run_registry unit tests
# ---------------------------------------------------------------------------

class TestRunRegistry:

    def test_list_runs_finds_run(self, aria_outputs):
        runs = run_registry.list_runs(limit=10)
        assert len(runs) == 1
        r = runs[0]
        assert r["run_id"] == aria_outputs["run_id"]
        assert r["part_name"] == "flange"
        assert r["agent_iterations"] == 2
        assert r["artifact_count"] == 3

    def test_get_run_returns_artifacts(self, aria_outputs):
        d = run_registry.get_run(aria_outputs["run_id"])
        assert d is not None
        kinds = {a["name"]: a["kind"] for a in d["artifacts"]}
        assert kinds["part.step"] == "mcad"
        assert kinds["part.stl"] == "mesh"
        assert kinds["render_iso.png"] == "render"
        assert d["manifest"]["goal"] == "build a precision flange"

    def test_get_run_unknown(self, aria_outputs):
        assert run_registry.get_run("nope") is None

    def test_floor_events_for_run(self, aria_outputs, floor_db_with_run):
        evs = run_registry.floor_events_for_run(aria_outputs["run_id"])
        kinds = [e["kind"] for e in evs]
        assert "job_started" in kinds
        assert "job_completed" in kinds


# ---------------------------------------------------------------------------
# Router integration
# ---------------------------------------------------------------------------

class TestRunsRouter:

    def test_list_requires_auth(self, client):
        assert client.get("/api/runs").status_code == 401

    def test_list_runs_endpoint(self, client, aria_outputs):
        _login(client)
        r = client.get("/api/runs")
        assert r.status_code == 200
        body = r.json()
        assert len(body["runs"]) == 1
        assert body["runs"][0]["run_id"] == aria_outputs["run_id"]

    def test_get_run_endpoint(self, client, aria_outputs):
        _login(client, email="runs_get@example.com")
        run_id = aria_outputs["run_id"]
        r = client.get(f"/api/runs/{run_id}")
        assert r.status_code == 200
        body = r.json()
        assert body["run_id"] == run_id
        assert any(a["kind"] == "mcad" for a in body["artifacts"])

    def test_get_run_404(self, client, aria_outputs):
        _login(client, email="runs_404@example.com")
        r = client.get("/api/runs/does_not_exist")
        assert r.status_code == 404

    def test_timeline_merges_sources(self, client, aria_outputs,
                                     floor_db_with_run):
        _login(client, email="runs_tl@example.com")
        run_id = aria_outputs["run_id"]
        r = client.get(f"/api/runs/{run_id}/timeline")
        assert r.status_code == 200
        body = r.json()
        sources = {e["_source"] for e in body["events"]}
        # Manifest milestones AND floor events present
        assert "aria_run_manifest" in sources
        assert "aria_floor" in sources
        # Events sorted ascending
        ts = [e.get("ts") or 0 for e in body["events"]]
        assert ts == sorted(ts)

    def test_artifact_download(self, client, aria_outputs):
        _login(client, email="runs_art@example.com")
        run_id = aria_outputs["run_id"]
        r = client.get(f"/api/runs/{run_id}/artifact/part.stl")
        assert r.status_code == 200
        assert r.content.startswith(b"solid stub")

    def test_artifact_path_traversal_blocked(self, client, aria_outputs):
        _login(client, email="runs_trav@example.com")
        run_id = aria_outputs["run_id"]
        # encoded relative escape
        r = client.get(f"/api/runs/{run_id}/artifact/..%2F..%2Fpasswd")
        # FastAPI normalizes %2F before routing — fall back to literal
        if r.status_code == 404:
            r2 = client.get(f"/api/runs/{run_id}/artifact/../../etc")
            assert r2.status_code in (400, 404)
        else:
            assert r.status_code in (400, 404)

    def test_artifact_unknown_404(self, client, aria_outputs):
        _login(client, email="runs_artnf@example.com")
        run_id = aria_outputs["run_id"]
        r = client.get(f"/api/runs/{run_id}/artifact/nope.bin")
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# aria_callback unit tests
# ---------------------------------------------------------------------------

class TestAriaCallback:

    def test_disabled_when_url_unset(self, monkeypatch):
        monkeypatch.delenv("ARIA_CALLBACK_URL", raising=False)
        assert aria_callback.is_enabled() is False
        intent = aria_callback.RedoIntent(
            aria_run_id="r1", aria_job_id=None,
            millforge_job_id=42, reason="QC failed")
        assert aria_callback.notify_redo(intent) is False

    def test_dispatched_when_url_set(self, monkeypatch):
        monkeypatch.setenv("ARIA_CALLBACK_URL", "http://localhost:9/redo")
        assert aria_callback.is_enabled() is True
        # Block actual network — our thread will hit urlopen, fail
        # quickly, log, and exit. We only verify the function returned True.
        intent = aria_callback.RedoIntent(
            aria_run_id="r1", aria_job_id=None,
            millforge_job_id=42, reason="QC failed")
        with patch("services.aria_callback.request.urlopen",
                   side_effect=urllib.error.URLError("conn refused")):
            assert aria_callback.notify_redo(intent) is True

    def test_intent_builder_dimensional_defect(self, monkeypatch):
        cam_meta = {"aria_run_id": "r-x"}
        intent = aria_callback.build_intent_from_qc(
            millforge_job_id=99, cam_metadata=cam_meta,
            qc_passed=False, defects_found=["dimensional_drift_OD"])
        assert intent.aria_run_id == "r-x"
        assert intent.severity == "escalate"
        assert intent.stage_hint == "tolerance_allocate"

    def test_intent_builder_surface_defect(self):
        intent = aria_callback.build_intent_from_qc(
            millforge_job_id=99, cam_metadata={"aria_job_id": "j1"},
            qc_passed=False, defects_found=["surface_finish_high"])
        assert intent.aria_job_id == "j1"
        assert intent.stage_hint == "cam_emit"
        assert intent.severity == "redo"

    def test_intent_builder_crack(self):
        intent = aria_callback.build_intent_from_qc(
            millforge_job_id=99, cam_metadata={},
            qc_passed=False, defects_found=["microcrack_root"])
        assert intent.severity == "escalate"
        assert intent.stage_hint == "fea_self_heal"


# ---------------------------------------------------------------------------
# QC feedback wiring — disabled vs enabled flag in response
# ---------------------------------------------------------------------------

class TestFeedbackCallbackWiring:

    def _post_minimal_job(self, client) -> int:
        """Use the existing /api/jobs/from-aria path to create a job
        we can then feed back against."""
        body = {
            "schema_version": "1.0",
            "aria_job_id": "feedback-loop-001",
            "part_name": "loopback_part",
            "geometry_hash": "a" * 64,
            "geometry_file": "x.step",
            "toolpath_file": "x.nc",
            "material": "aluminum",
            "material_spec": {
                "material_name": "AL6061",
                "material_family": "aluminum",
            },
            "required_operations": ["milling"],
            "tolerance_class": "medium",
            "simulation_results": {
                "estimated_cycle_time_minutes": 30.0,
                "collision_detected": False,
                "simulation_confidence": 0.9,
            },
            "validation_passed": True,
            "estimated_cycle_time_minutes": 30.0,
        }
        r = client.post("/api/jobs/from-aria", json=body)
        assert r.status_code == 200, r.text
        return r.json()["millforge_job_id"]

    def test_callback_disabled_in_response(self, client, monkeypatch):
        monkeypatch.delenv("ARIA_CALLBACK_URL", raising=False)
        self._post_minimal_job(client)
        r = client.post("/api/bridge/feedback", json={
            "aria_job_id": "feedback-loop-001",
            "actual_cycle_time_minutes": 35.0,
            "qc_passed": False,
            "defects_found": ["surface_finish_high"],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["aria_callback_enabled"] is False
        assert body["aria_callback_dispatched"] is False

    def test_callback_dispatched_in_response(self, client, monkeypatch):
        monkeypatch.setenv("ARIA_CALLBACK_URL", "http://localhost:9/redo")
        self._post_minimal_job(client)
        with patch("services.aria_callback.request.urlopen",
                   side_effect=urllib.error.URLError("conn refused")):
            r = client.post("/api/bridge/feedback", json={
                "aria_job_id": "feedback-loop-001",
                "actual_cycle_time_minutes": 35.0,
                "qc_passed": False,
                "defects_found": ["dimensional_drift"],
            })
        assert r.status_code == 200
        body = r.json()
        assert body["aria_callback_enabled"] is True
        assert body["aria_callback_dispatched"] is True

    def test_pass_does_not_dispatch(self, client, monkeypatch):
        monkeypatch.setenv("ARIA_CALLBACK_URL", "http://localhost:9/redo")
        self._post_minimal_job(client)
        r = client.post("/api/bridge/feedback", json={
            "aria_job_id": "feedback-loop-001",
            "actual_cycle_time_minutes": 28.0,
            "qc_passed": True,
            "defects_found": [],
        })
        assert r.status_code == 200
        body = r.json()
        # Even with the URL set, a passing QC does NOT trigger a callback
        assert body["aria_callback_dispatched"] is False
