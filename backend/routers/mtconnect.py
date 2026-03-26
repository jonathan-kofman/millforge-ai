"""
MTConnect router — /api/mtconnect

GET  /api/mtconnect/status  — current state snapshot from all connected devices
POST /api/mtconnect/sync    — manual poll + FeedbackLogger sync
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from agents.mtconnect_client import MTConnectClient
from agents.mtconnect_sync import MTConnectSynchronizer
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/mtconnect", tags=["MTConnect"])

# ---------------------------------------------------------------------------
# Module-level singletons (lazy init on first request)
# ---------------------------------------------------------------------------
_client: Optional[MTConnectClient] = None
_synchronizer: Optional[MTConnectSynchronizer] = None


def _get_client() -> MTConnectClient:
    global _client
    if _client is None:
        url = os.getenv("MTCONNECT_AGENT_URL", "mock://")
        timeout = float(os.getenv("MTCONNECT_POLL_TIMEOUT_SECONDS", "5.0"))
        _client = MTConnectClient(agent_url=url, poll_timeout_seconds=timeout)
    return _client


def _get_synchronizer() -> MTConnectSynchronizer:
    global _synchronizer
    if _synchronizer is None:
        _synchronizer = MTConnectSynchronizer(_get_client())
    return _synchronizer


def _device_ids() -> list[int]:
    return _get_client().default_device_ids()


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/status",
    summary="Current MTConnect device status",
    response_description="Live or cached state snapshot for all configured devices.",
)
async def mtconnect_status():
    """
    Returns a state snapshot from every configured MTConnect device.

    When the MTConnect agent is unreachable, the last-known cached state is
    returned with `is_healthy: false`. In mock mode (default), synthetic
    rotating states are returned so the UI always has data.

    **connection_status values:**
    - `connected` — all devices healthy
    - `partial` — some devices unreachable
    - `unreachable` — no devices reachable
    - `mock_fallback` — no real agent configured (dev/CI mode)
    """
    client = _get_client()
    ids = _device_ids()
    all_data = client.poll_all_devices(ids)

    devices = {}
    for device_id, snap in all_data.items():
        devices[str(device_id)] = {
            "device_id": snap.device_id,
            "device_name": snap.device_name,
            "program_name": snap.program_name,
            "job_id": snap.job_id,
            "execution_state": snap.execution_state,
            "mill_state": snap.mill_state,
            "spindle_speed_rpm": snap.spindle_speed_rpm,
            "feed_rate_override_percent": snap.feed_rate_override_percent,
            "part_count": snap.part_count,
            "sampled_at": snap.sampled_at.isoformat(),
            "is_healthy": snap.is_healthy,
            "error_message": snap.error_message,
        }

    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "connection_status": client.connection_status,
        "device_count": len(devices),
        "devices": devices,
    }


@router.post(
    "/sync",
    summary="Trigger MTConnect poll + feedback log",
    response_description="Jobs logged to FeedbackLogger from completed MTConnect runs.",
)
async def mtconnect_sync(db: Session = Depends(get_db)):
    """
    Polls all configured devices and logs any completed jobs to FeedbackLogger
    with `data_provenance = mtconnect_auto`.

    Safe to call frequently — only records when a RUNNING → IDLE transition is
    detected. Use this endpoint from a cron job, a Celery beat task, or the
    MillForge dashboard's "Sync machines" button.

    **Returns:**
    - `jobs_logged` — how many feedback records were written this call
    - `feedback_records` — list of canonical IDs and timing details
    """
    sync = _get_synchronizer()
    ids = _device_ids()

    # Device → machine mapping: 1:1 by default. Override via env var JSON if needed.
    device_machine_map = {did: did for did in ids}
    material_map: dict[int, str] = {}  # default "steel" inside sync_all

    records = sync.sync_all(db, device_machine_map, material_map)

    feedback = [
        {
            "canonical_id": r.canonical_id,
            "order_id": r.order_id,
            "machine_id": r.machine_id,
            "actual_setup_minutes": r.actual_setup_minutes,
            "actual_processing_minutes": r.actual_processing_minutes,
            "data_provenance": r.data_provenance,
        }
        for r in records
    ]

    return {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "devices_polled": len(ids),
        "jobs_logged": len(feedback),
        "feedback_records": feedback,
    }
