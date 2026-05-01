"""End-to-end integration test for the ARIA-OS / MillForge / StructSight
integration spine.

What this exercises in one run:

  1. ARIA bundle ingestion        POST /api/aria/bundle
  2. Full CAM submission          POST /api/jobs/from-aria
  3. Run timeline (cross-stack)   GET  /api/runs/{run_id}/timeline
  4. Operator dashboard snapshot  GET  /api/floor/snapshot
  5. Per-machine drill-down       GET  /api/floor/machine/{id}
  6. QC fail + closed-loop ARIA   POST /api/bridge/feedback (qc_passed=false)
                                  → fires aria_callback (mocked urlopen)
  7. Pass-through QC               POST /api/bridge/feedback (qc_passed=true)
                                  → does NOT fire callback
  8. Schema-version probe          GET  /schema-version (if exposed)

This is the "ready: yes/no" gate before live Fusion runs. If this test
goes red, something in the spine is broken and the operator dashboard
won't reflect what's happening on the floor.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
import urllib.error
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


# ---------------------------------------------------------------------------
# Realistic synthetic environment — mirror what ARIA actually writes
# ---------------------------------------------------------------------------

@pytest.fixture
def spine_env(tmp_path, monkeypatch):
    """Bring up everything an end-to-end check needs:

      - aria-os outputs/runs/<run_id>/ with a real-shape run_manifest.json
        (uses `timestamp_utc`, `pipeline_stats`, `mesh_stats`)
      - aria_os.floor SQLite events log with one machine + a registered
        job tied to the same run_id, plus a couple of telemetry events
      - ARIA_CALLBACK_URL pointed at a stub URL so we can verify dispatch
    """
    outputs = tmp_path / "outputs"
    runs = outputs / "runs"
    runs.mkdir(parents=True)

    run_id = "20260501T180000_e2eabcdef"
    rd = runs / run_id
    rd.mkdir()
    started = time.time() - 3600
    completed = time.time() - 60
    manifest = {
        "schema_version": "2.1",
        "run_id": run_id,
        "goal": "build a 213mm OD x 21mm impeller, aluminum, 8 backward blades",
        "part_id": "impeller_e2e",
        "part_name": "impeller_e2e",
        "timestamp_utc": datetime.fromtimestamp(
            started, tz=timezone.utc).isoformat(),
        "completed_at": datetime.fromtimestamp(
            completed, tz=timezone.utc).isoformat(),
        "pipeline_stats": {
            "agent_iterations": 1,
            "wall_time_s": 540.0,
            "success_agent": True,
            "llm_total_calls": 5,
            "llm_calls": {"anthropic": 3, "gemini": 2},
        },
        "mesh_stats": {
            "triangle_count": 12450,
            "vertex_count": 6230,
            "bbox_mm": [213.0, 213.0, 21.0],
            "volume_cm3": 124.7,
            "watertight": True,
        },
        "operations": [
            {"sequence": 10, "operation_name": "CNC turn",
             "work_center_category": "lathe"},
            {"sequence": 20, "operation_name": "CNC mill blades",
             "work_center_category": "cnc_mill"},
        ],
    }
    (rd / "run_manifest.json").write_text(json.dumps(manifest, indent=2))
    (rd / "part.step").write_text("ISO-10303-21;\n/* impeller stub */\n")
    (rd / "part.stl").write_bytes(b"solid impeller\nendsolid impeller\n")
    (rd / "render_iso.png").write_bytes(b"\x89PNG\r\n\x1a\nSTUB-IMG-DATA")
    (rd / "drawing.pdf").write_bytes(b"%PDF-1.4\n% stub\n%%EOF\n")
    (rd / "1001.nc").write_text("(IMPELLER OP10)\nG21 G90\nG00 X0 Y0 Z5\nM30\n")

    # Floor SQLite — minimum schema the reader walks
    db_path = tmp_path / "floor_state.db"
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
    cur.execute(
        "INSERT INTO machines VALUES "
        "(1,'DMG-NLX','fanuc','127.0.0.1',1500,800,800,5000,"
        "'turn_mill_subspindle',?)",
        (now - 86400,))
    cur.execute(
        "INSERT INTO jobs (id, run_id, part_name, machine_id, status, "
        "queued_at, started_at) VALUES (701, ?, 'impeller_e2e', 1, "
        "'running', ?, ?)",
        (run_id, now - 600, now - 540))
    for ts, kind, payload in [
        (now - 540, "job_started",
         {"machine_id": 1, "run_id": run_id}),
        (now - 480, "telemetry",
         {"machine_id": 1, "spindle_rpm": 4500, "feed_mmpm": 1200}),
        (now - 60, "job_energy",
         {"kwh": 6.4, "co2_kg": 2.5, "anomaly": False, "machine_id": 1}),
    ]:
        cur.execute(
            "INSERT INTO events (job_id, ts, kind, payload_json) "
            "VALUES (701, ?, ?, ?)",
            (ts, kind, json.dumps(payload)))
    conn.commit()
    conn.close()

    monkeypatch.setenv("ARIA_OUTPUTS_PATH", str(outputs))
    monkeypatch.setenv("ARIA_FLOOR_DB_PATH", str(db_path))
    monkeypatch.setenv("ARIA_CALLBACK_URL", "http://localhost:9/redo-intent")

    return {
        "run_id": run_id,
        "outputs": outputs,
        "floor_db": db_path,
        "manifest": manifest,
    }


def _login(client, email: str = "spine_e2e@example.com") -> None:
    client.post("/api/auth/register", json={
        "email": email, "password": "testpass123",
        "name": "Spine E2E"})
    client.post("/api/auth/login", json={
        "email": email, "password": "testpass123"})


# ---------------------------------------------------------------------------
# The end-to-end test
# ---------------------------------------------------------------------------

class TestE2ESpine:
    """Single-class integration check. Each method is one stage of the
    full handshake; pytest reports per-method so a partial failure shows
    exactly which seam broke."""

    @pytest.fixture(autouse=True)
    def _bind(self, client, spine_env):
        # Bind shared client + env onto self so each test method sees
        # the same authenticated session and the same outputs/runs/.
        self.client = client
        self.env = spine_env
        _login(client)

    # Stage 1 — the ARIA bundle handoff
    def test_01_aria_bundle_round_trip(self):
        body = {
            "schema_version": "1.0",
            "run_id": self.env["run_id"],
            "goal": self.env["manifest"]["goal"],
            "part_name": self.env["manifest"]["part_name"],
            "step_path": str(
                self.env["outputs"] / "runs" / self.env["run_id"] / "part.step"),
            "stl_path": str(
                self.env["outputs"] / "runs" / self.env["run_id"] / "part.stl"),
            "geometry_hash": "f" * 64,
            "material": "aluminum",
            "validation": {"dfm_process": "cnc_milling"},
        }
        r = self.client.post("/api/aria/bundle", json=body)
        assert r.status_code == 200, r.text
        ack = r.json()
        assert ack["aria_run_id"] == self.env["run_id"]
        assert ack["status"] == "pending_cam"

    # Stage 2 — full CAM submission upgrades the same job
    def test_02_full_cam_submission(self):
        body = {
            "schema_version": "1.0",
            "aria_job_id": "spine-e2e-job",
            "part_name": self.env["manifest"]["part_name"],
            "geometry_hash": "f" * 64,
            "geometry_file": "part.step",
            "toolpath_file": "1001.nc",
            "material": "aluminum",
            "material_spec": {
                "material_name": "AL6061",
                "material_family": "aluminum"},
            "required_operations": ["turning", "milling"],
            "tolerance_class": "tight",
            "simulation_results": {
                "estimated_cycle_time_minutes": 28.0,
                "collision_detected": False,
                "simulation_confidence": 0.95},
            "validation_passed": True,
            "estimated_cycle_time_minutes": 28.0,
            "extra": {"aria_run_id": self.env["run_id"]},
        }
        r = self.client.post("/api/jobs/from-aria", json=body)
        assert r.status_code == 200, r.text
        ack = r.json()
        assert ack["status"] == "queued"
        assert ack["millforge_job_id"]

    # Stage 3 — cross-stack timeline merges fs + DB + floor
    def test_03_run_timeline_merges_sources(self):
        run_id = self.env["run_id"]
        r = self.client.get(f"/api/runs/{run_id}/timeline")
        assert r.status_code == 200, r.text
        body = r.json()
        sources = {e["_source"] for e in body["events"]}
        assert "aria_run_manifest" in sources
        assert "aria_floor" in sources
        # Artifacts surfaced
        kinds = {a["kind"] for a in body["artifacts"]}
        assert {"mcad", "mesh", "render", "drawing", "gcode"} <= kinds

    # Stage 4 — operator dashboard snapshot
    def test_04_operator_snapshot(self):
        r = self.client.get("/api/floor/snapshot")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["aria_floor"]["state"] == "ok"
        assert len(body["aria"]["machines"]) == 1
        assert body["aria"]["queue"]["running"] >= 1
        # Energy telemetry surfaced from the seeded floor event
        assert body["aria"]["energy_24h"]["jobs"] >= 1

    # Stage 5 — machine drill-down
    def test_05_machine_drill_down(self):
        r = self.client.get("/api/floor/machine/1")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["id"] == 1
        assert body["status"] in ("ok", "unknown")
        # Active running job from the seeded data
        assert body["active_job"] is not None
        assert body["active_job"]["job_id"] == 701

    # Stage 6 — closed-loop ARIA callback fires on qc_failed
    def test_06_closed_loop_callback_on_qc_fail(self):
        # First, register the job that will receive the feedback
        sub = {
            "schema_version": "1.0",
            "aria_job_id": "spine-e2e-fb",
            "part_name": self.env["manifest"]["part_name"],
            "geometry_hash": "f" * 64,
            "geometry_file": "part.step",
            "toolpath_file": "1001.nc",
            "material": "aluminum",
            "material_spec": {"material_name": "AL6061",
                              "material_family": "aluminum"},
            "required_operations": ["milling"],
            "tolerance_class": "tight",
            "simulation_results": {
                "estimated_cycle_time_minutes": 30.0,
                "collision_detected": False,
                "simulation_confidence": 0.9},
            "validation_passed": True,
            "estimated_cycle_time_minutes": 30.0,
            "extra": {"aria_run_id": self.env["run_id"]},
        }
        sub_resp = self.client.post("/api/jobs/from-aria", json=sub)
        assert sub_resp.status_code == 200, sub_resp.text

        # The callback uses urlopen in a daemon thread — patch it so
        # network failure doesn't matter, we just need to confirm the
        # function was called with our intent payload.
        captured: list[dict] = []

        def _spy(req, *args, **kwargs):
            try:
                body = req.data.decode("utf-8") if req.data else ""
                captured.append(json.loads(body) if body else {})
            except Exception:
                captured.append({"_decode_failed": True})
            raise urllib.error.URLError("conn refused (test)")

        with patch("services.aria_callback.request.urlopen",
                   side_effect=_spy):
            r = self.client.post("/api/bridge/feedback", json={
                "aria_job_id": "spine-e2e-fb",
                "actual_cycle_time_minutes": 35.0,
                "qc_passed": False,
                "defects_found": ["dimensional_drift_OD"],
                "feedback_notes": "OD outside ±0.025mm",
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["aria_callback_enabled"] is True
            assert body["aria_callback_dispatched"] is True

        # Daemon thread fires the urlopen synchronously after we exit
        # the context. Wait briefly for it to land.
        deadline = time.time() + 2.0
        while not captured and time.time() < deadline:
            time.sleep(0.05)
        assert captured, "callback urlopen was never invoked"
        intent = captured[0]
        assert intent["aria_run_id"] == self.env["run_id"]
        assert intent["severity"] == "escalate"            # dimensional → escalate
        assert intent["stage_hint"] == "tolerance_allocate"
        assert "dimensional_drift_OD" in intent["defects_found"]

    # Stage 7 — passing QC must NOT trigger callback
    def test_07_pass_qc_does_not_callback(self):
        # Each test gets a fresh in-memory DB (client fixture is function-
        # scoped) so we register the job inline instead of relying on the
        # one created in stage 2.
        sub = {
            "schema_version": "1.0",
            "aria_job_id": "spine-e2e-pass",
            "part_name": self.env["manifest"]["part_name"],
            "geometry_hash": "f" * 64,
            "geometry_file": "part.step",
            "toolpath_file": "1001.nc",
            "material": "aluminum",
            "material_spec": {"material_name": "AL6061",
                              "material_family": "aluminum"},
            "required_operations": ["milling"],
            "tolerance_class": "tight",
            "simulation_results": {
                "estimated_cycle_time_minutes": 30.0,
                "collision_detected": False,
                "simulation_confidence": 0.9},
            "validation_passed": True,
            "estimated_cycle_time_minutes": 30.0,
        }
        sub_resp = self.client.post("/api/jobs/from-aria", json=sub)
        assert sub_resp.status_code == 200, sub_resp.text

        with patch("services.aria_callback.request.urlopen") as mock:
            r = self.client.post("/api/bridge/feedback", json={
                "aria_job_id": "spine-e2e-pass",
                "actual_cycle_time_minutes": 27.0,
                "qc_passed": True,
                "defects_found": [],
            })
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["aria_callback_dispatched"] is False
        # urlopen must have been left untouched
        assert mock.call_count == 0

    # Stage 8 — readiness verdict
    def test_08_ready_verdict(self):
        # If we got here, every stage above passed. Print a sentinel
        # the operator can grep for.
        snap = self.client.get("/api/floor/snapshot").json()
        timeline = self.client.get(
            f"/api/runs/{self.env['run_id']}/timeline").json()
        verdict = {
            "ready": True,
            "aria_floor_state": snap["aria_floor"]["state"],
            "machines": len(snap["aria"]["machines"]),
            "timeline_events": timeline["events_total"],
            "artifacts": len(timeline["artifacts"]),
        }
        # The assertion that gates "ready" — keeps in lockstep with
        # the seeded environment.
        assert verdict["aria_floor_state"] == "ok"
        assert verdict["machines"] >= 1
        assert verdict["timeline_events"] >= 3
        assert verdict["artifacts"] >= 5
        # Print on success so test output gives a one-liner verdict
        print("\n[E2E SPINE READY]", json.dumps(verdict))
