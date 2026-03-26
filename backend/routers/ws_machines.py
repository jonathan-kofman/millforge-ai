"""
WebSocket + REST endpoints for live machine state.

WebSocket: ws://host/ws/machines
  - On connect: immediately sends a "snapshot" message with all machine states
  - On each state transition: sends a "state_change" event to every connected client
  - Ping/pong keepalive: client may send {"type": "ping"}, server replies {"type": "pong"}

REST (polling fallback for clients that don't support WebSockets):
  GET  /api/machines                    — current state of all machines
  GET  /api/machines/{id}               — single machine state
  POST /api/machines/{id}/assign        — assign a job to an idle machine
  POST /api/machines/{id}/reset-fault   — clear a faulted machine
  POST /api/machines/{id}/force-complete — (test/demo) immediately finish the running job

Message schema
--------------
Snapshot (sent on connect)::

    {
      "type": "snapshot",
      "machines": [
        {"machine_id": 1, "state": "IDLE", "job_id": null, ...},
        ...
      ],
      "sent_at": "2026-03-26T10:00:00Z"
    }

State-change event (broadcast on transition)::

    {
      "type": "state_change",
      "machine_id": 2,
      "from_state": "SETUP",
      "to_state": "RUNNING",
      "job_id": "ORD-042",
      "occurred_at": "2026-03-26T10:05:30Z"
    }
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Set

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Machines"])

# ---------------------------------------------------------------------------
# Connection manager
# ---------------------------------------------------------------------------

class ConnectionManager:
    """Thread-safe WebSocket connection registry with JSON broadcast."""

    def __init__(self) -> None:
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._connections.add(ws)
        logger.info("WS client connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.discard(ws)
        logger.info("WS client disconnected (%d remaining)", len(self._connections))

    async def broadcast(self, event: dict) -> None:
        """Send JSON to every connected client. Dead connections are removed."""
        if not self._connections:
            return
        message = json.dumps(event)
        dead: list[WebSocket] = []
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._connections.discard(ws)

    async def send(self, ws: WebSocket, event: dict) -> None:
        """Send JSON to a single client."""
        await ws.send_text(json.dumps(event))

    @property
    def client_count(self) -> int:
        return len(self._connections)


# Module-level singleton — shared between router and MachineFleet
connection_manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Fleet accessor (imported at request time to avoid circular imports)
# ---------------------------------------------------------------------------

def _fleet():
    from main import machine_fleet
    return machine_fleet


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/machines")
async def ws_machines(websocket: WebSocket):
    """
    Live machine state stream.

    Connect to receive real-time state-change events for all CNC machines.

    **On connect** — server immediately sends a `snapshot` message so the client
    can render the current floor state without waiting for the next transition.

    **On each state transition** — server broadcasts a `state_change` event.

    **Ping/pong** — send `{"type": "ping"}` to keep the connection alive;
    server replies `{"type": "pong"}`.

    **Reconnection** — clients should reconnect with exponential backoff on disconnect.
    """
    await connection_manager.connect(websocket)
    try:
        # Send initial snapshot
        fleet = _fleet()
        await connection_manager.send(websocket, {
            "type": "snapshot",
            "machines": fleet.snapshot(),
            "sent_at": datetime.now(timezone.utc).isoformat(),
        })

        # Keep connection alive; handle incoming pings
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await connection_manager.send(websocket, {"type": "pong"})
            except asyncio.TimeoutError:
                # No message for 30s — send a keepalive ping from server side
                await connection_manager.send(websocket, {
                    "type": "ping",
                    "server_time": datetime.now(timezone.utc).isoformat(),
                })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.warning("WS error: %s", exc)
    finally:
        connection_manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@router.get("/api/machines", summary="Current state of all machines")
async def get_machines():
    """
    Returns current state of every machine in the fleet.

    Use the WebSocket endpoint `/ws/machines` for real-time updates.
    This REST endpoint is a polling fallback.
    """
    fleet = _fleet()
    return {
        "machine_count": fleet.machine_count,
        "machines": fleet.snapshot(),
        "sampled_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/api/machines/{machine_id}", summary="Single machine state")
async def get_machine(machine_id: int):
    fleet = _fleet()
    try:
        return fleet.machine_snapshot(machine_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


class AssignJobRequest(BaseModel):
    job_id: str
    setup_time_minutes: float = 15.0
    processing_time_minutes: float = 60.0
    material: Optional[str] = None


@router.post("/api/machines/{machine_id}/assign", summary="Assign a job to an idle machine")
async def assign_job(machine_id: int, req: AssignJobRequest):
    """
    Assign a job to the specified machine. The machine must be in IDLE state.

    Once assigned, the fleet's background loop will drive it through:
    IDLE → SETUP → READY → RUNNING → COOLDOWN → IDLE

    State changes are broadcast over `/ws/machines` in real time.
    """
    fleet = _fleet()
    try:
        fleet.machine_snapshot(machine_id)  # raises ValueError if machine doesn't exist
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    try:
        fleet.assign_job(
            machine_id=machine_id,
            job_id=req.job_id,
            setup_time_minutes=req.setup_time_minutes,
            processing_time_minutes=req.processing_time_minutes,
            material=req.material,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"machine_id": machine_id, "job_id": req.job_id, "status": "assigned"}


@router.post("/api/machines/{machine_id}/reset-fault", summary="Clear a faulted machine")
async def reset_fault(machine_id: int):
    """
    Clear FAULT state and return the machine to IDLE.

    This is the operator acknowledgement action — machines only reach FAULT when
    the state machine catches an unexpected exception. An operator must physically
    inspect the machine before calling reset.
    """
    fleet = _fleet()
    try:
        fleet.reset_fault(machine_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"machine_id": machine_id, "status": "fault_cleared"}


@router.post(
    "/api/machines/{machine_id}/force-complete",
    summary="Force-complete the running job (demo/test only)",
    include_in_schema=False,
)
async def force_complete(machine_id: int):
    """Mark the running job as immediately complete. For demo and testing only."""
    fleet = _fleet()
    try:
        fleet.force_complete(machine_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"machine_id": machine_id, "status": "force_completed"}
