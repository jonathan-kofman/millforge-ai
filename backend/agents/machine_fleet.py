"""
MachineFleet — manages a pool of MachineStateMachines and broadcasts state changes.

The fleet runs a background asyncio task that calls step() on every machine once
per second. When a machine transitions, it fires the registered broadcast callback
so the WebSocket layer can push the event to all connected clients.

Usage::

    fleet = MachineFleet(machine_count=3, broadcast_fn=connection_manager.broadcast)
    await fleet.start()          # begin background stepping
    fleet.assign_job(1, "ORD-001", setup_time_minutes=15, processing_time_minutes=60, material="steel")
    snapshot = fleet.snapshot()  # [{machine_id, state, job_id, ...}, ...]
    await fleet.stop()
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from agents.machine_state_machine import MachineState, MachineStateMachine, MockMachineIO

logger = logging.getLogger(__name__)

# How often the background loop calls step() on each machine (seconds)
_STEP_INTERVAL = 1.0


class MachineFleet:
    """
    Manages N MachineStateMachine instances with a shared broadcast callback.

    The fleet is started once during app lifespan and runs until shutdown.
    REST and WebSocket routers interact with it via the module-level singleton.
    """

    def __init__(self, machine_count: int = 3, broadcast_fn: Optional[Callable] = None) -> None:
        self._machine_count = machine_count
        self._broadcast_fn = broadcast_fn  # async callable(event_dict)
        self._machines: Dict[int, MachineStateMachine] = {}
        self._io = MockMachineIO()
        self._task: Optional[asyncio.Task] = None
        self._running = False

        for mid in range(1, machine_count + 1):
            self._machines[mid] = MachineStateMachine(
                machine_id=mid,
                io=self._io,
                on_transition=self._on_transition,
            )

        logger.info("MachineFleet initialized with %d machines.", machine_count)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start the background stepping loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._step_loop(), name="machine-fleet-step")
        logger.info("MachineFleet background loop started.")

    async def stop(self) -> None:
        """Stop the background stepping loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MachineFleet background loop stopped.")

    # ------------------------------------------------------------------
    # Job management
    # ------------------------------------------------------------------

    def assign_job(
        self,
        machine_id: int,
        job_id: str,
        setup_time_minutes: float,
        processing_time_minutes: float,
        material: Optional[str] = None,
    ) -> None:
        """
        Assign a job to a machine. Raises ValueError if machine is not IDLE.
        """
        machine = self._get_machine(machine_id)
        machine.assign_job(
            job_id=job_id,
            setup_time_minutes=setup_time_minutes,
            processing_time_minutes=processing_time_minutes,
            material=material,
        )

    def reset_fault(self, machine_id: int) -> None:
        """Clear a FAULT state. No-op if machine is not in FAULT."""
        machine = self._get_machine(machine_id)
        machine.reset_fault()

    def force_complete(self, machine_id: int) -> None:
        """Test helper: immediately complete the running job on a machine."""
        self._io.force_complete(machine_id)

    # ------------------------------------------------------------------
    # State query
    # ------------------------------------------------------------------

    def snapshot(self) -> List[dict]:
        """Return current state of all machines as a list of dicts."""
        return [self._machine_dict(m) for m in self._machines.values()]

    def machine_snapshot(self, machine_id: int) -> dict:
        """Return current state of a single machine."""
        return self._machine_dict(self._get_machine(machine_id))

    @property
    def machine_count(self) -> int:
        return self._machine_count

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_machine(self, machine_id: int) -> MachineStateMachine:
        if machine_id not in self._machines:
            raise ValueError(f"Machine {machine_id} not found (fleet has {self._machine_count} machines)")
        return self._machines[machine_id]

    def _machine_dict(self, m: MachineStateMachine) -> dict:
        return {
            "machine_id": m.machine_id,
            "state": m.state.name,
            "job_id": m._current_job_id,
            "setup_duration_s": m._setup_duration,
            "processing_duration_s": m._processing_duration,
            "sampled_at": datetime.now(timezone.utc).isoformat(),
        }

    def _on_transition(
        self,
        machine_id: int,
        from_state: MachineState,
        to_state: MachineState,
        job_id: Optional[str],
    ) -> None:
        """Synchronous callback fired by MachineStateMachine._transition."""
        event = {
            "type": "state_change",
            "machine_id": machine_id,
            "from_state": from_state.name,
            "to_state": to_state.name,
            "job_id": job_id,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._broadcast_fn is not None:
            # Schedule the async broadcast on the running event loop.
            # _on_transition is called from synchronous step() inside the loop task.
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._broadcast_fn(event))
            except RuntimeError:
                pass  # no event loop — test environment

    async def _step_loop(self) -> None:
        """Tick every machine once per second."""
        while self._running:
            for machine in self._machines.values():
                try:
                    machine.step()
                except Exception as exc:
                    logger.error("Fleet step error machine %d: %s", machine.machine_id, exc)
            await asyncio.sleep(_STEP_INTERVAL)
