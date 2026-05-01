"""Tests for /api/floor/* — operator dashboard wiring + floor_state_reader.

Covers two paths:

  1. ARIA_FLOOR_DB_PATH unset → endpoints still work, aria-side widgets
     report `state="unconfigured"` and stay empty.

  2. ARIA_FLOOR_DB_PATH points at a temp SQLite that mirrors the
     aria_os/floor schema → snapshot/alerts/timeline/machine_detail
     surface real machines, jobs, and events.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from services import floor_state_reader as floor


# ---------------------------------------------------------------------------
# Fixture — a synthetic aria_os floor DB
# ---------------------------------------------------------------------------

def _build_floor_db(path: Path) -> None:
    """Mirror the aria_os/floor/state_store.py schema closely enough for
    the reader to walk it. We only create the tables this dashboard reads."""
    conn = sqlite3.connect(str(path))
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE machines (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            controller TEXT,
            controller_addr TEXT,
            max_x_mm REAL,
            max_y_mm REAL,
            max_z_mm REAL,
            max_spindle_rpm INTEGER,
            kinematics TEXT,
            created_at REAL
        );
        CREATE TABLE jobs (
            id INTEGER PRIMARY KEY,
            run_id TEXT,
            part_name TEXT,
            machine_id INTEGER,
            fixture_id INTEGER,
            gcode_path TEXT,
            stock_spec_json TEXT,
            status TEXT,
            queued_at REAL,
            started_at REAL,
            completed_at REAL,
            tool_use_log_json TEXT,
            fault_log_json TEXT,
            output_log_path TEXT
        );
        CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            job_id INTEGER,
            ts REAL,
            kind TEXT,
            payload_json TEXT
        );
    """)
    now = time.time()
    cur.execute(
        "INSERT INTO machines VALUES (1,'HAAS-VF2','haas','127.0.0.1',"
        "762,406,508,12000,'3axis_mill',?)",
        (now - 86400,),
    )
    cur.execute(
        "INSERT INTO machines VALUES (2,'DMG-NLX','fanuc','127.0.0.2',"
        "1500,800,800,5000,'turn_mill_subspindle',?)",
        (now - 86400,),
    )
    cur.execute(
        "INSERT INTO jobs VALUES (101,'r1','impeller_v3',1,NULL,NULL,NULL,"
        "'running',?,?,NULL,NULL,NULL,NULL)",
        (now - 600, now - 300),
    )
    cur.execute(
        "INSERT INTO jobs VALUES (102,'r2','flange_a',1,NULL,NULL,NULL,"
        "'queued',?,NULL,NULL,NULL,NULL,NULL)",
        (now - 100,),
    )
    cur.execute(
        "INSERT INTO jobs VALUES (103,'r3','shaft_b',2,NULL,NULL,NULL,"
        "'complete',?,?,?,NULL,NULL,NULL)",
        (now - 7200, now - 7000, now - 3600),
    )
    # Machine 2 is currently down; machine 1 had a transient down/up.
    events = [
        # Machine 1: trip then clear → status should be 'ok'
        (None, now - 1000, "machine_down",
         {"machine_id": 1, "reason": "spindle warning"}),
        (None, now - 800, "machine_up",
         {"machine_id": 1}),
        # Machine 2: tripped, never cleared → status 'down'
        (None, now - 200, "machine_down",
         {"machine_id": 2, "reason": "comm fail"}),
        # Watchdog tripped on machine 2
        (None, now - 150, "watchdog_trip",
         {"machine_id": 2, "trip_reason": "telemetry stall"}),
        # Lights-off escalation
        (None, now - 100, "lights_off_escalate",
         {"serial": "SN-123", "machine_id": 1,
          "reason": "tolerance breach"}),
        # Gauging queue: one queued, one in_transit, one done
        (None, now - 90, "gauging_queued",
         {"serial": "SN-200", "features": ["datum_chain"]}),
        (None, now - 80, "gauging_queued",
         {"serial": "SN-201", "features": ["cylindricity"]}),
        (None, now - 70, "gauging_in_transit",
         {"serial": "SN-201", "cmm_id": 1}),
        (None, now - 60, "gauging_queued",
         {"serial": "SN-202", "features": ["profile_of_surface"]}),
        (None, now - 50, "gauging_done",
         {"serial": "SN-202", "decision": {"verdict": "pass"}}),
        # Purchase orders: one open, one received
        (None, now - 1500, "purchase_order",
         {"material": "brass_C36000", "form": "bar", "diameter_mm": 12.7,
          "qty": 5, "vendor": "OnlineMetals", "estimated_cost_usd": 250.0}),
        (None, now - 1200, "purchase_order",
         {"material": "alum_6061", "form": "bar", "diameter_mm": 25.4,
          "qty": 3, "vendor": "McMaster", "estimated_cost_usd": 180.0}),
        (None, now - 600, "po_received",
         {"po_id": 11, "qty_received": 5}),
        # Tool needs preset
        (None, now - 40, "tool_needs_preset",
         {"machine_id": 1, "slot": 4, "kind": "length"}),
        # Energy events
        (101, now - 500, "job_energy",
         {"kwh": 4.2, "co2_kg": 1.6, "anomaly": False, "machine_id": 1}),
        (103, now - 3800, "job_energy",
         {"kwh": 7.1, "co2_kg": 2.7, "anomaly": True, "machine_id": 2}),
    ]
    for job_id, ts, kind, payload in events:
        cur.execute(
            "INSERT INTO events (job_id, ts, kind, payload_json) "
            "VALUES (?,?,?,?)",
            (job_id, ts, kind, json.dumps(payload)),
        )
    conn.commit()
    conn.close()


@pytest.fixture
def floor_db(tmp_path, monkeypatch):
    db_path = tmp_path / "floor_state.db"
    _build_floor_db(db_path)
    monkeypatch.setenv("ARIA_FLOOR_DB_PATH", str(db_path))
    yield db_path


@pytest.fixture
def no_floor_db(monkeypatch):
    monkeypatch.delenv("ARIA_FLOOR_DB_PATH", raising=False)
    yield


# ---------------------------------------------------------------------------
# Helper — register + login a fresh user in the test client
# ---------------------------------------------------------------------------

def _login(client, email: str = "floor_op@example.com") -> None:
    client.post("/api/auth/register", json={
        "email": email, "password": "testpass123", "name": "Floor Op",
    })
    client.post("/api/auth/login", json={
        "email": email, "password": "testpass123",
    })


# ---------------------------------------------------------------------------
# Reader unit tests
# ---------------------------------------------------------------------------

class TestFloorStateReader:

    def test_db_status_unconfigured(self, no_floor_db):
        s = floor.db_status()
        assert s["state"] == "unconfigured"
        assert s["path"] is None

    def test_db_status_missing(self, monkeypatch, tmp_path):
        monkeypatch.setenv("ARIA_FLOOR_DB_PATH",
                           str(tmp_path / "does_not_exist.db"))
        s = floor.db_status()
        assert s["state"] == "missing"

    def test_db_status_ok(self, floor_db):
        s = floor.db_status()
        assert s["state"] == "ok"
        assert s["events_total"] > 0

    def test_list_machines_derives_status(self, floor_db):
        ms = floor.list_machines()
        ids = {m["id"]: m for m in ms}
        assert set(ids) == {1, 2}
        # machine 1 was down then up → ok
        assert ids[1]["status"] == "ok"
        # machine 2 down with no clearing event → down
        assert ids[2]["status"] == "down"
        assert ids[2]["watchdog_tripped"] is True
        # machine 1 has running job 101
        assert ids[1]["active_job"] is not None
        assert ids[1]["active_job"]["job_id"] == 101
        assert ids[2]["active_job"] is None

    def test_queue_counts(self, floor_db):
        q = floor.queue_counts()
        assert q["running"] == 1
        assert q["queued"] == 1
        assert q["complete"] == 1

    def test_gauging_summary(self, floor_db):
        g = floor.gauging_queue_summary()
        # SN-200 queued, SN-201 in_transit, SN-202 done
        assert g["queued"] == 1
        assert g["in_transit"] == 1
        assert g["done"] == 1

    def test_open_purchase_orders(self, floor_db):
        pos = floor.open_purchase_orders()
        # Two emitted; one received → only one open
        assert len(pos) == 1
        assert pos[0]["state"] == "emitted"
        assert pos[0]["material"] == "alum_6061"

    def test_alerts_filter_and_severity(self, floor_db):
        a = floor.alerts(limit=20)
        kinds = [x["kind"] for x in a]
        assert "machine_down" in kinds                 # machine 2
        assert "watchdog_trip" in kinds
        assert "lights_off_escalate" in kinds
        assert "tool_needs_preset" in kinds
        # machine 1's machine_down was cleared → must NOT appear
        machine_ids = [x["machine_id"] for x in a if x["kind"] == "machine_down"]
        assert 1 not in machine_ids
        assert 2 in machine_ids
        # severity tagging
        crits = [x for x in a if x["severity"] == "critical"]
        assert any(x["kind"] == "lights_off_escalate" for x in crits)

    def test_energy_summary_24h(self, floor_db):
        e = floor.energy_summary()
        # Both job_energy events are within 24h
        assert e["jobs"] == 2
        assert e["kwh_total"] == pytest.approx(11.3, abs=0.01)
        assert e["anomalies"] == 1

    def test_timeline_kind_filter(self, floor_db):
        ev = floor.timeline(kinds=["machine_down"], limit=10)
        assert len(ev) == 2
        assert all(e["kind"] == "machine_down" for e in ev)

    def test_machine_detail(self, floor_db):
        d = floor.machine_detail(2)
        assert d is not None
        assert d["status"] == "down"
        assert d["watchdog_tripped"] is True
        # recent_events should include the watchdog_trip we wrote
        assert any(e["kind"] == "watchdog_trip" for e in d["recent_events"])

    def test_machine_detail_missing(self, floor_db):
        assert floor.machine_detail(9999) is None

    def test_snapshot_unconfigured_safe(self, no_floor_db):
        s = floor.snapshot()
        assert s["aria_floor"]["state"] == "unconfigured"
        assert s["machines"] == []
        assert s["queue"] == {}
        assert s["alerts"] == []


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------

class TestFloorDashboardRouter:

    def test_snapshot_requires_auth(self, client, floor_db):
        r = client.get("/api/floor/snapshot")
        assert r.status_code == 401

    def test_snapshot_ok_with_db(self, client, floor_db):
        _login(client)
        r = client.get("/api/floor/snapshot")
        assert r.status_code == 200
        body = r.json()
        for k in ("aria_floor", "millforge", "aria"):
            assert k in body
        assert body["aria_floor"]["state"] == "ok"
        assert len(body["aria"]["machines"]) == 2
        assert body["aria"]["queue"]["running"] == 1
        # Alerts must be non-empty given the seeded events
        assert len(body["aria"]["alerts"]) >= 3

    def test_snapshot_ok_without_db(self, client, no_floor_db):
        _login(client, email="floor_no_db@example.com")
        r = client.get("/api/floor/snapshot")
        assert r.status_code == 200
        body = r.json()
        assert body["aria_floor"]["state"] == "unconfigured"
        # MillForge side still populated (zeros, not crash)
        assert "job_stages" in body["millforge"]
        assert body["aria"]["machines"] == []

    def test_machine_detail_endpoint(self, client, floor_db):
        _login(client, email="floor_md@example.com")
        r = client.get("/api/floor/machine/1")
        assert r.status_code == 200
        d = r.json()
        assert d["id"] == 1
        assert d["status"] == "ok"
        assert d["active_job"]["job_id"] == 101

    def test_machine_detail_not_found(self, client, floor_db):
        _login(client, email="floor_md_nf@example.com")
        r = client.get("/api/floor/machine/9999")
        assert r.status_code == 404

    def test_machine_detail_503_when_no_db(self, client, no_floor_db):
        _login(client, email="floor_md_503@example.com")
        r = client.get("/api/floor/machine/1")
        assert r.status_code == 503

    def test_alerts_endpoint(self, client, floor_db):
        _login(client, email="floor_alerts@example.com")
        r = client.get("/api/floor/alerts?limit=20")
        assert r.status_code == 200
        body = r.json()
        assert body["count"] >= 3
        assert "by_severity" in body

    def test_timeline_filter(self, client, floor_db):
        _login(client, email="floor_tl@example.com")
        r = client.get("/api/floor/timeline?kinds=machine_down&limit=50")
        assert r.status_code == 200
        body = r.json()
        # All returned events match the filter
        for e in body["events"]:
            assert e["kind"] == "machine_down"

    def test_stats_endpoint(self, client, floor_db):
        _login(client, email="floor_stats@example.com")
        r = client.get("/api/floor/stats")
        assert r.status_code == 200
        body = r.json()
        assert "queue" in body
        assert "energy_24h" in body
        assert body["open_purchase_orders"] == 1
