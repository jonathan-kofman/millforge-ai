"""
Tests for live machine state — MachineFleet, ConnectionManager, and REST/WS endpoints.
"""

import asyncio
import json
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from agents.machine_fleet import MachineFleet
from agents.machine_state_machine import MachineState, MockMachineIO
from routers.ws_machines import ConnectionManager
from fastapi.testclient import TestClient
from main import app

_tc = TestClient(app)


# ---------------------------------------------------------------------------
# MachineFleet — basic state management
# ---------------------------------------------------------------------------

def _make_fleet(machine_count: int = 3) -> MachineFleet:
    return MachineFleet(machine_count=machine_count)


def test_fleet_initializes_correct_count():
    fleet = _make_fleet(4)
    assert fleet.machine_count == 4


def test_fleet_snapshot_returns_all_machines():
    fleet = _make_fleet(3)
    snap = fleet.snapshot()
    assert len(snap) == 3
    ids = {s["machine_id"] for s in snap}
    assert ids == {1, 2, 3}


def test_fleet_initial_state_idle():
    fleet = _make_fleet(2)
    for s in fleet.snapshot():
        assert s["state"] == "IDLE"
        assert s["job_id"] is None


def test_fleet_assign_job_transitions_machine():
    fleet = _make_fleet(2)
    fleet.assign_job(1, "ORD-001", setup_time_minutes=0.01, processing_time_minutes=0.01)
    snap = fleet.machine_snapshot(1)
    # After assign but before step, job_id should be set and state still IDLE
    assert snap["job_id"] == "ORD-001"


def test_fleet_assign_to_invalid_machine_raises():
    fleet = _make_fleet(2)
    with pytest.raises(ValueError, match="Machine 99"):
        fleet.assign_job(99, "ORD-X", setup_time_minutes=5, processing_time_minutes=10)


def test_fleet_machine_snapshot_404_on_missing():
    fleet = _make_fleet(2)
    with pytest.raises(ValueError):
        fleet.machine_snapshot(99)


def test_fleet_force_complete_does_not_raise():
    fleet = _make_fleet(1)
    fleet.assign_job(1, "ORD-TEST", setup_time_minutes=0.001, processing_time_minutes=0.001)
    # Force complete should not raise even if not in RUNNING state
    fleet.force_complete(1)


def test_fleet_reset_fault_no_op_when_not_faulted():
    fleet = _make_fleet(1)
    # reset_fault when IDLE should be a no-op (MachineStateMachine only resets FAULT)
    fleet.reset_fault(1)
    assert fleet.machine_snapshot(1)["state"] == "IDLE"


# ---------------------------------------------------------------------------
# MachineFleet — on_transition callback
# ---------------------------------------------------------------------------

def test_on_transition_callback_fired():
    events = []

    def capture(machine_id, from_state, to_state, job_id):
        events.append((machine_id, from_state.name, to_state.name))

    fleet = MachineFleet(machine_count=1, broadcast_fn=None)
    fleet._machines[1]._on_transition = capture

    fleet.assign_job(1, "ORD-CB", setup_time_minutes=0.001, processing_time_minutes=0.001)
    fleet._machines[1].step()  # IDLE → SETUP

    assert len(events) == 1
    assert events[0] == (1, "IDLE", "SETUP")


def test_on_transition_multiple_steps():
    events = []

    def capture(machine_id, from_state, to_state, job_id):
        events.append(to_state.name)

    fleet = MachineFleet(machine_count=1, broadcast_fn=None)
    m = fleet._machines[1]
    m._on_transition = capture

    fleet.assign_job(1, "ORD-MS", setup_time_minutes=0.001, processing_time_minutes=0.001)
    m.step()   # IDLE → SETUP
    time.sleep(0.1)
    m.step()   # SETUP → READY (after setup elapses)
    m.step()   # READY → RUNNING

    assert "SETUP" in events
    assert "READY" in events
    assert "RUNNING" in events


# ---------------------------------------------------------------------------
# MachineFleet — async background loop
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_fleet_start_stop():
    fleet = MachineFleet(machine_count=2)
    await fleet.start()
    assert fleet._running is True
    await asyncio.sleep(0.1)
    await fleet.stop()
    assert fleet._running is False


@pytest.mark.asyncio
async def test_fleet_double_start_is_idempotent():
    fleet = MachineFleet(machine_count=1)
    await fleet.start()
    task1 = fleet._task
    await fleet.start()  # second call should no-op
    assert fleet._task is task1
    await fleet.stop()


@pytest.mark.asyncio
async def test_fleet_broadcasts_on_transition():
    broadcast_calls = []

    async def fake_broadcast(event):
        broadcast_calls.append(event)

    fleet = MachineFleet(machine_count=1, broadcast_fn=fake_broadcast)
    await fleet.start()

    fleet.assign_job(1, "ORD-ASYNC", setup_time_minutes=0.001, processing_time_minutes=0.001)
    await asyncio.sleep(0.3)  # let the step loop fire at least once

    await fleet.stop()

    # At least one state_change event should have been broadcast
    state_change_events = [e for e in broadcast_calls if e.get("type") == "state_change"]
    assert len(state_change_events) >= 1
    assert state_change_events[0]["machine_id"] == 1
    assert "from_state" in state_change_events[0]
    assert "to_state" in state_change_events[0]


# ---------------------------------------------------------------------------
# ConnectionManager
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_connection_manager_connect_disconnect():
    mgr = ConnectionManager()
    ws = AsyncMock()
    await mgr.connect(ws)
    assert mgr.client_count == 1
    mgr.disconnect(ws)
    assert mgr.client_count == 0


@pytest.mark.asyncio
async def test_connection_manager_broadcast_sends_to_all():
    mgr = ConnectionManager()
    ws1 = AsyncMock()
    ws2 = AsyncMock()
    await mgr.connect(ws1)
    await mgr.connect(ws2)

    event = {"type": "state_change", "machine_id": 1}
    await mgr.broadcast(event)

    ws1.send_text.assert_called_once_with(json.dumps(event))
    ws2.send_text.assert_called_once_with(json.dumps(event))


@pytest.mark.asyncio
async def test_connection_manager_removes_dead_connections():
    mgr = ConnectionManager()
    dead_ws = AsyncMock()
    dead_ws.send_text.side_effect = RuntimeError("connection closed")
    await mgr.connect(dead_ws)

    await mgr.broadcast({"type": "ping"})
    assert mgr.client_count == 0


@pytest.mark.asyncio
async def test_connection_manager_broadcast_noop_when_empty():
    mgr = ConnectionManager()
    # Should not raise
    await mgr.broadcast({"type": "state_change"})


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

def test_get_machines_ok():
    resp = _tc.get("/api/machines")
    assert resp.status_code == 200
    body = resp.json()
    assert "machines" in body
    assert "machine_count" in body
    assert body["machine_count"] >= 1
    assert len(body["machines"]) == body["machine_count"]


def test_get_machines_all_have_required_fields():
    resp = _tc.get("/api/machines")
    for m in resp.json()["machines"]:
        assert "machine_id" in m
        assert "state" in m
        assert "job_id" in m
        assert "sampled_at" in m


def test_get_single_machine_ok():
    resp = _tc.get("/api/machines/1")
    assert resp.status_code == 200
    body = resp.json()
    assert body["machine_id"] == 1
    assert body["state"] in ("IDLE", "SETUP", "READY", "RUNNING", "COOLDOWN", "FAULT")


def test_get_missing_machine_404():
    resp = _tc.get("/api/machines/9999")
    assert resp.status_code == 404


def test_assign_job_ok():
    resp = _tc.post("/api/machines/1/assign", json={
        "job_id": "ORD-WS-TEST",
        "setup_time_minutes": 30,
        "processing_time_minutes": 60,
        "material": "steel",
    })
    # May be 200 or 409 if machine is not idle (fleet background task may have changed it)
    assert resp.status_code in (200, 409)


def test_assign_to_missing_machine_404():
    resp = _tc.post("/api/machines/9999/assign", json={
        "job_id": "ORD-X",
        "setup_time_minutes": 5,
        "processing_time_minutes": 10,
    })
    assert resp.status_code == 404


def test_reset_fault_ok():
    resp = _tc.post("/api/machines/1/reset-fault")
    assert resp.status_code == 200


def test_reset_fault_missing_machine_404():
    resp = _tc.post("/api/machines/9999/reset-fault")
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

def test_ws_connect_receives_snapshot():
    with _tc.websocket_connect("/ws/machines") as ws:
        msg = json.loads(ws.receive_text())
        assert msg["type"] == "snapshot"
        assert "machines" in msg
        assert "sent_at" in msg


def test_ws_snapshot_machine_count_matches_rest():
    rest = _tc.get("/api/machines").json()["machine_count"]
    with _tc.websocket_connect("/ws/machines") as ws:
        snap = json.loads(ws.receive_text())
        assert len(snap["machines"]) == rest


def test_ws_ping_pong():
    with _tc.websocket_connect("/ws/machines") as ws:
        ws.receive_text()  # consume snapshot
        ws.send_text(json.dumps({"type": "ping"}))
        reply = json.loads(ws.receive_text())
        assert reply["type"] == "pong"


def test_ws_multiple_clients_connect():
    with _tc.websocket_connect("/ws/machines") as ws1:
        with _tc.websocket_connect("/ws/machines") as ws2:
            snap1 = json.loads(ws1.receive_text())
            snap2 = json.loads(ws2.receive_text())
            assert snap1["type"] == "snapshot"
            assert snap2["type"] == "snapshot"
