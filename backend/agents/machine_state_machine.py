"""
CNC machine lifecycle state machine — adapted from microgravity-manufacturing-stack.

Simulates realistic machine behavior during a production schedule:
  IDLE → SETUP (setup_time_minutes) → READY → RUNNING (processing_time_minutes) → COOLDOWN → IDLE

Every state transition is timestamped and persisted to MachineStateLog.
The MachineIO Protocol decouples real hardware from MockMachineIO.
"""

from __future__ import annotations

import logging
import threading
import time
from enum import Enum, auto
from typing import Optional, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


class MachineState(Enum):
    IDLE = auto()
    SETUP = auto()
    READY = auto()
    RUNNING = auto()
    COOLDOWN = auto()
    FAULT = auto()


@runtime_checkable
class MachineIO(Protocol):
    """Minimal IO interface — implemented by real hardware drivers and MockMachineIO."""

    def start_setup(self, machine_id: int, job_id: str) -> None: ...
    def start_run(self, machine_id: int, job_id: str) -> None: ...
    def stop(self, machine_id: int) -> None: ...
    def is_job_complete(self, machine_id: int) -> bool: ...


class MockMachineIO:
    """
    Simulates machine I/O without real hardware.

    Uses a time-based model: jobs complete after their allotted duration.
    Thread-safe for concurrent scheduler tests.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._job_complete_at: dict[int, float] = {}  # machine_id → epoch (monotonic)

    def start_setup(self, machine_id: int, job_id: str) -> None:
        logger.debug("MockIO: machine %d starting setup for job %s", machine_id, job_id)

    def start_run(self, machine_id: int, job_id: str) -> None:
        logger.debug("MockIO: machine %d starting run for job %s", machine_id, job_id)

    def stop(self, machine_id: int) -> None:
        with self._lock:
            self._job_complete_at.pop(machine_id, None)
        logger.debug("MockIO: machine %d stopped", machine_id)

    def is_job_complete(self, machine_id: int) -> bool:
        with self._lock:
            deadline = self._job_complete_at.get(machine_id)
        if deadline is None:
            return False
        return time.monotonic() >= deadline

    def schedule_completion(self, machine_id: int, duration_seconds: float) -> None:
        """Register when a running job will be complete (called by MachineStateMachine)."""
        with self._lock:
            self._job_complete_at[machine_id] = time.monotonic() + duration_seconds

    def force_complete(self, machine_id: int) -> None:
        """Test helper: mark a running job as immediately complete."""
        with self._lock:
            self._job_complete_at[machine_id] = time.monotonic() - 1.0


class MachineStateMachine:
    """
    Manages a single CNC machine through its production lifecycle.

    Usage::

        io = MockMachineIO()
        msm = MachineStateMachine(machine_id=1, io=io)
        msm.assign_job("ORD-001", setup_time_minutes=15, processing_time_minutes=45)
        msm.step()  # IDLE → SETUP
        # ...time passes...
        msm.step()  # SETUP → READY when setup_time elapses
        msm.step()  # READY → RUNNING
        io.force_complete(1)
        msm.step()  # RUNNING → COOLDOWN
    """

    COOLDOWN_SECONDS = 60  # 1-minute cooldown after each job

    def __init__(self, machine_id: int, io: MachineIO, db=None) -> None:
        self.machine_id = machine_id
        self.io = io
        self.db = db
        self.state = MachineState.IDLE
        self._current_job_id: Optional[str] = None
        self._setup_duration: float = 0.0
        self._processing_duration: float = 0.0
        self._setup_complete_at: Optional[float] = None
        self._cooldown_complete_at: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign_job(
        self,
        job_id: str,
        setup_time_minutes: float,
        processing_time_minutes: float,
    ) -> None:
        """Assign a new job. Only valid when in IDLE state."""
        if self.state != MachineState.IDLE:
            raise ValueError(
                f"Cannot assign job to machine {self.machine_id} — current state: {self.state.name}"
            )
        self._current_job_id = job_id
        self._setup_duration = setup_time_minutes * 60
        self._processing_duration = processing_time_minutes * 60
        logger.info(
            "Machine %d assigned job %s (setup=%.0fs run=%.0fs)",
            self.machine_id, job_id, self._setup_duration, self._processing_duration,
        )

    def step(self) -> MachineState:
        """
        Advance the state machine one tick.

        Safe to call frequently — only transitions when durations have elapsed.
        Any exception during a transition forces the machine into FAULT.
        """
        try:
            return self._dispatch()
        except Exception as exc:
            logger.error(
                "Machine %d fault during %s: %s", self.machine_id, self.state.name, exc
            )
            self._transition(MachineState.FAULT)
            return self.state

    def reset_fault(self) -> None:
        """Operator clears a FAULT and returns the machine to IDLE."""
        if self.state == MachineState.FAULT:
            self._current_job_id = None
            self._transition(MachineState.IDLE)
            logger.info("Machine %d fault cleared — returning to IDLE", self.machine_id)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self) -> MachineState:
        now = time.monotonic()

        if self.state == MachineState.IDLE:
            if self._current_job_id is not None:
                self.io.start_setup(self.machine_id, self._current_job_id)
                self._setup_complete_at = now + self._setup_duration
                self._transition(MachineState.SETUP)

        elif self.state == MachineState.SETUP:
            if self._setup_complete_at is not None and now >= self._setup_complete_at:
                self._transition(MachineState.READY)

        elif self.state == MachineState.READY:
            self.io.start_run(self.machine_id, self._current_job_id)
            if isinstance(self.io, MockMachineIO):
                self.io.schedule_completion(self.machine_id, self._processing_duration)
            self._transition(MachineState.RUNNING)

        elif self.state == MachineState.RUNNING:
            if self.io.is_job_complete(self.machine_id):
                self.io.stop(self.machine_id)
                completed_job = self._current_job_id
                self._current_job_id = None
                self._cooldown_complete_at = now + self.COOLDOWN_SECONDS
                self._transition(MachineState.COOLDOWN)
                logger.info("Machine %d completed job %s", self.machine_id, completed_job)

        elif self.state == MachineState.COOLDOWN:
            if self._cooldown_complete_at is not None and now >= self._cooldown_complete_at:
                self._transition(MachineState.IDLE)

        return self.state

    def _transition(self, new_state: MachineState) -> None:
        old_state = self.state
        self.state = new_state
        logger.info(
            "Machine %d: %s → %s (job=%s)",
            self.machine_id, old_state.name, new_state.name, self._current_job_id,
        )
        if self.db is not None:
            self._log_transition(old_state, new_state)

    def _log_transition(self, from_state: MachineState, to_state: MachineState) -> None:
        try:
            from db_models import MachineStateLog  # local import avoids circular deps
            record = MachineStateLog(
                machine_id=self.machine_id,
                job_id=self._current_job_id,
                from_state=from_state.name,
                to_state=to_state.name,
            )
            self.db.add(record)
            self.db.commit()
        except Exception as exc:
            logger.warning("Failed to log state transition for machine %d: %s", self.machine_id, exc)
