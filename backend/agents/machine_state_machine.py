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
from datetime import datetime, timezone
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

    def __init__(self, machine_id: int, io: MachineIO, db=None, on_transition=None) -> None:
        self.machine_id = machine_id
        self.io = io
        self.db = db
        self.state = MachineState.IDLE
        self._on_transition = on_transition  # callable(machine_id, from_state, to_state, job_id)
        self._current_job_id: Optional[str] = None
        self._setup_duration: float = 0.0
        self._processing_duration: float = 0.0
        self._setup_complete_at: Optional[float] = None
        self._cooldown_complete_at: Optional[float] = None
        self._setup_start_wall: Optional[datetime] = None
        self._run_start_wall: Optional[datetime] = None
        self._order_material: Optional[str] = None
        # Lock protects all state transitions from concurrent access
        # (e.g., assign_job() and reset_fault() called while step() is running)
        self._transition_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assign_job(
        self,
        job_id: str,
        setup_time_minutes: float,
        processing_time_minutes: float,
        material: Optional[str] = None,
    ) -> None:
        """Assign a new job. Only valid when in IDLE state."""
        with self._transition_lock:
            if self.state != MachineState.IDLE:
                raise ValueError(
                    f"Cannot assign job to machine {self.machine_id} — current state: {self.state.name}"
                )
            self._current_job_id = job_id
            self._setup_duration = setup_time_minutes * 60
            self._processing_duration = processing_time_minutes * 60
            self._order_material = material
            logger.info(
                "Machine %d assigned job %s (setup=%.0fs run=%.0fs)",
                self.machine_id, job_id, self._setup_duration, self._processing_duration,
            )

    def step(self) -> MachineState:
        """
        Advance the state machine one tick.

        Safe to call frequently — only transitions when durations have elapsed.
        Any exception during a transition forces the machine into FAULT.
        Protected by per-machine lock to ensure atomic transitions under concurrent access.
        """
        with self._transition_lock:
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
        with self._transition_lock:
            if self.state == MachineState.FAULT:
                self._current_job_id = None
                self._transition(MachineState.IDLE)
                logger.info("Machine %d fault cleared — returning to IDLE", self.machine_id)

    # ------------------------------------------------------------------
    # Internal dispatch
    # ------------------------------------------------------------------

    def _dispatch(self) -> MachineState:
        now = time.monotonic()
        now_wall = datetime.now(timezone.utc).replace(tzinfo=None)

        if self.state == MachineState.IDLE:
            if self._current_job_id is not None:
                self.io.start_setup(self.machine_id, self._current_job_id)
                self._setup_complete_at = now + self._setup_duration
                self._setup_start_wall = now_wall
                self._transition(MachineState.SETUP)

        elif self.state == MachineState.SETUP:
            if self._setup_complete_at is not None and now >= self._setup_complete_at:
                self._transition(MachineState.READY)

        elif self.state == MachineState.READY:
            self.io.start_run(self.machine_id, self._current_job_id)
            if isinstance(self.io, MockMachineIO):
                self.io.schedule_completion(self.machine_id, self._processing_duration)
            self._run_start_wall = now_wall
            self._transition(MachineState.RUNNING)

        elif self.state == MachineState.RUNNING:
            if self.io.is_job_complete(self.machine_id):
                self.io.stop(self.machine_id)
                completed_job = self._current_job_id
                completed_material = self._order_material
                self._current_job_id = None
                self._cooldown_complete_at = now + self.COOLDOWN_SECONDS
                self._transition(MachineState.COOLDOWN)
                logger.info("Machine %d completed job %s", self.machine_id, completed_job)
                self._log_feedback(completed_job, completed_material, now_wall)

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
        if self._on_transition is not None:
            try:
                self._on_transition(self.machine_id, old_state, new_state, self._current_job_id)
            except Exception as exc:
                logger.debug("on_transition callback error: %s", exc)

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

    def _log_feedback(self, job_id: str, material: Optional[str], completion_time: datetime) -> None:
        """Log actual job performance to FeedbackLogger for self-calibration."""
        if self.db is None or job_id is None or material is None:
            return
        if self._setup_start_wall is None or self._run_start_wall is None:
            return

        try:
            from agents.feedback_logger import FeedbackLogger
            from agents.scheduler import BASE_SETUP_MINUTES

            # Compute actual timings from wall timestamps
            actual_setup_minutes = (self._run_start_wall - self._setup_start_wall).total_seconds() / 60
            actual_processing_minutes = (completion_time - self._run_start_wall).total_seconds() / 60

            # Get predicted values (same source the scheduler uses)
            # For setup time, we'd need the previous material — default to BASE_SETUP_MINUTES
            predicted_setup_minutes = float(BASE_SETUP_MINUTES)
            predicted_processing_minutes = self._processing_duration / 60

            # Log to FeedbackLogger with mtconnect_auto provenance
            logger = FeedbackLogger()
            logger.log(
                db=self.db,
                order_id=job_id,
                material=material,
                machine_id=self.machine_id,
                predicted_setup_minutes=predicted_setup_minutes,
                actual_setup_minutes=actual_setup_minutes,
                predicted_processing_minutes=predicted_processing_minutes,
                actual_processing_minutes=actual_processing_minutes,
                provenance="mtconnect_auto",
            )
        except Exception as exc:
            logger.warning("Failed to log feedback for job %s: %s", job_id, exc)
