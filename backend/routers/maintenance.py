"""
/api/maintenance endpoints — predictive maintenance signals.

All endpoints require authentication.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import User
from auth.dependencies import get_current_user
from agents.predictive_maintenance import PredictiveMaintenanceAgent

router = APIRouter(prefix="/api/maintenance", tags=["Predictive Maintenance"])
_agent = PredictiveMaintenanceAgent()


@router.get(
    "/signals",
    summary="Predictive maintenance risk signals for all machines",
)
async def get_maintenance_signals(
    lookback_hours: int = Query(168, ge=1, le=720, description="History window in hours (default 7 days)"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """
    Return per-machine maintenance risk signals derived from MachineStateLog history.

    Each machine entry includes:
    - **fault_count_24h / fault_count_7d** — fault frequency in recent windows
    - **mtbf_hours** — mean time between faults (None if fewer than 2 faults recorded)
    - **mttr_minutes** — mean time to repair (time spent in FAULT state)
    - **risk_score** — composite 0–100 score
    - **risk_level** — `ok` | `watch` | `service_soon` | `urgent`
    - **recommendation** — human-readable action string
    """
    signals = _agent.signals(db, lookback_hours=lookback_hours)
    return {
        "machine_count": len(signals),
        "lookback_hours": lookback_hours,
        "machines": signals,
    }


@router.get(
    "/signals/{machine_id}",
    summary="Predictive maintenance risk signal for a single machine",
)
async def get_machine_signal(
    machine_id: int,
    lookback_hours: int = Query(168, ge=1, le=720),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Return the maintenance risk signal for one machine by ID."""
    signal = _agent.signal_for_machine(db, machine_id, lookback_hours=lookback_hours)
    return signal
