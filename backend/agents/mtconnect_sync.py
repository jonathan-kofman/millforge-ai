"""
MTConnect synchronizer — detects job completions and logs actual timing to FeedbackLogger.

Workflow:
  1. Call sync_device(db, device_id, machine_id, material) on a schedule (or on-demand).
  2. The synchronizer maintains a per-device state history (last N snapshots).
  3. When it detects a RUNNING → IDLE/STOPPED transition, it computes:
       actual_setup_minutes    = time from first non-IDLE snapshot to first ACTIVE snapshot
       actual_processing_minutes = time from first ACTIVE to end of ACTIVE run
  4. Calls FeedbackLogger.log(..., provenance="mtconnect_auto") to persist the record.
  5. Returns the JobFeedbackRecord, or None if no completion was detected.

Thread safety: per-device locks guard the history deques.
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, Dict, Optional, Tuple

from agents.mtconnect_client import MTConnectClient, MTConnectDeviceData

logger = logging.getLogger(__name__)

# How many snapshots to keep per device for timing computation
_HISTORY_LEN = 120


class _DeviceHistory:
    """Ring buffer of recent device snapshots for a single machine."""

    def __init__(self) -> None:
        self._snapshots: Deque[MTConnectDeviceData] = deque(maxlen=_HISTORY_LEN)
        self._lock = threading.Lock()
        self._last_was_running = False
        self._run_start: Optional[datetime] = None
        self._setup_start: Optional[datetime] = None

    def push(self, snap: MTConnectDeviceData) -> None:
        with self._lock:
            self._snapshots.append(snap)

    def detect_completion(self, snap: MTConnectDeviceData) -> Optional[Tuple[float, float, str]]:
        """
        Compare incoming snapshot to previous state.

        Returns (actual_setup_minutes, actual_processing_minutes, job_id) when a
        RUNNING → stopped transition is detected, else None.
        """
        with self._lock:
            was_running = self._last_was_running
            now_running = snap.mill_state == "RUNNING"
            now_idle = snap.mill_state in ("IDLE", "STOPPED", "COOLDOWN")
            now = snap.sampled_at.replace(tzinfo=None) if snap.sampled_at.tzinfo else snap.sampled_at

            if not was_running and now_running:
                # Transition into RUNNING — mark run start
                self._run_start = now
                if self._setup_start is None:
                    self._setup_start = now  # fallback: no setup phase captured
                self._last_was_running = True
                return None

            if was_running and now_idle:
                # Job completed
                self._last_was_running = False
                run_end = now

                if self._run_start is None:
                    # No start timestamp — can't compute timing
                    self._setup_start = None
                    return None

                setup_start = self._setup_start or self._run_start
                actual_setup = max(
                    0.0,
                    (self._run_start - setup_start).total_seconds() / 60.0,
                )
                actual_processing = max(
                    0.0,
                    (run_end - self._run_start).total_seconds() / 60.0,
                )

                # Find the job_id from the most recent snapshot that had one
                job_id: Optional[str] = None
                for s in reversed(self._snapshots):
                    if s.job_id:
                        job_id = s.job_id
                        break

                # Reset for next job
                self._run_start = None
                self._setup_start = None

                if job_id:
                    return (actual_setup, actual_processing, job_id)
                return None

            if not was_running and snap.mill_state == "SETUP":
                # Setup phase starting
                if self._setup_start is None:
                    self._setup_start = now

            self._last_was_running = now_running
            return None


# ---------------------------------------------------------------------------
# Synchronizer
# ---------------------------------------------------------------------------

class MTConnectSynchronizer:
    """
    Orchestrates MTConnect polling and FeedbackLogger integration.

    Example::

        client = MTConnectClient()
        sync = MTConnectSynchronizer(client)

        # Call periodically or from /api/mtconnect/sync
        record = sync.sync_device(db, device_id=1, machine_id=1, material="steel")
        if record:
            print("Logged:", record.canonical_id)
    """

    def __init__(self, client: MTConnectClient) -> None:
        self._client = client
        self._histories: Dict[int, _DeviceHistory] = {}
        self._histories_lock = threading.Lock()

    def _get_history(self, device_id: int) -> _DeviceHistory:
        with self._histories_lock:
            if device_id not in self._histories:
                self._histories[device_id] = _DeviceHistory()
            return self._histories[device_id]

    def sync_device(
        self,
        db,
        device_id: int,
        machine_id: int,
        material: str = "steel",
    ):
        """
        Poll device_id, update history, and log a FeedbackRecord if a job completed.

        Returns JobFeedbackRecord on completion, None otherwise. Never raises.
        """
        try:
            snap = self._client.poll_device(device_id)
            hist = self._get_history(device_id)

            completion = hist.detect_completion(snap)
            hist.push(snap)

            if completion is None:
                return None

            actual_setup_min, actual_processing_min, job_id = completion

            # Get predicted values from the SchedulingTwin if available,
            # otherwise fall back to scheduler constants.
            try:
                from agents.scheduling_twin import SchedulingTwin
                twin = SchedulingTwin()
                predicted_setup = twin.predict_setup_time(
                    from_material=material,
                    to_material=material,
                    machine_id=machine_id,
                )
                # Processing prediction requires more context; fall back to actual as best guess
                predicted_processing = actual_processing_min
            except Exception:
                from agents.scheduler import BASE_SETUP_MINUTES
                predicted_setup = float(BASE_SETUP_MINUTES)
                predicted_processing = actual_processing_min

            from agents.feedback_logger import FeedbackLogger
            record = FeedbackLogger().log(
                db=db,
                order_id=job_id,
                material=material,
                machine_id=machine_id,
                predicted_setup_minutes=predicted_setup,
                actual_setup_minutes=actual_setup_min,
                predicted_processing_minutes=predicted_processing,
                actual_processing_minutes=actual_processing_min,
                provenance="mtconnect_auto",
            )
            logger.info(
                "MTConnect sync logged job %s on machine %d: setup=%.1f min, processing=%.1f min",
                job_id, machine_id, actual_setup_min, actual_processing_min,
            )
            return record

        except Exception as exc:
            logger.error(
                "MTConnect sync failed for device %d: %s", device_id, exc, exc_info=True
            )
            return None

    def sync_all(self, db, device_machine_map: Dict[int, int], material_map: Dict[int, str]):
        """
        Sync all devices in parallel.

        device_machine_map: {device_id: machine_id}
        material_map: {device_id: material_string}

        Returns list of JobFeedbackRecord (only for devices that completed a job).
        """
        results = []
        for device_id, machine_id in device_machine_map.items():
            material = material_map.get(device_id, "steel")
            record = self.sync_device(db, device_id, machine_id, material)
            if record:
                results.append(record)
        return results
