"""
Predictive maintenance auto-slot — find the next idle window on a machine
where a maintenance task can be inserted without bumping a scheduled job.

Queries the most recent ``ScheduleRun`` and walks through its serialized
``ScheduledOrderOutput`` list to find the first contiguous gap of at least
``duration_minutes`` on the target machine. Returns the recommended slot,
or ``None`` if no window exists inside the horizon (caller decides what
to do — defer, escalate, or force a maintenance hold).

No modification to existing scheduling tables — this is a read-only helper
that shops can call from the UI:

    "Cutter vibration elevated on MC-2. Find a 90-minute slot for
     spindle bearing check." → recommends the window.

Used by the /api/maintenance/auto-slot endpoint and by background alert
agents when a PdM risk crosses the service_soon threshold.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session


logger = logging.getLogger(__name__)


# Default lookahead window if the schedule doesn't define an explicit horizon.
_DEFAULT_HORIZON_HOURS = 72
# Treat anything shorter than this as "no gap" — prevents slotting into
# a 30-second sliver between two queued jobs.
_MIN_USEFUL_GAP_MINUTES = 5


def _parse_dt(value: Any) -> Optional[datetime]:
    """Parse a datetime from the scheduled_orders JSON (ISO string or datetime)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str):
        return None
    v = value.rstrip("Z")
    try:
        return datetime.fromisoformat(v).replace(tzinfo=None)
    except ValueError:
        return None


def _extract_operations_for_machine(
    scheduled: list[dict[str, Any]],
    machine_id: int,
) -> list[tuple[datetime, datetime]]:
    """Extract (start, end) tuples for operations running on a given machine.

    The ``ScheduledOrderOutput`` dict shape used inside ScheduleRun:
        {order_id, machine_id, start_time, end_time, ...}

    Silently skips entries with missing / unparseable times.
    """
    windows: list[tuple[datetime, datetime]] = []
    for entry in scheduled:
        if not isinstance(entry, dict):
            continue
        mid = entry.get("machine_id")
        if mid is None:
            continue
        try:
            if int(mid) != int(machine_id):
                continue
        except (TypeError, ValueError):
            continue
        start = _parse_dt(entry.get("start_time"))
        end = _parse_dt(entry.get("end_time"))
        if start is None or end is None or end <= start:
            continue
        windows.append((start, end))
    windows.sort(key=lambda w: w[0])
    return windows


def _find_gap(
    busy: list[tuple[datetime, datetime]],
    horizon_start: datetime,
    horizon_end: datetime,
    duration: timedelta,
) -> Optional[tuple[datetime, datetime]]:
    """Walk busy intervals, return first gap >= duration inside the horizon."""
    min_gap = timedelta(minutes=_MIN_USEFUL_GAP_MINUTES)
    cursor = horizon_start

    for start, end in busy:
        if end <= cursor:
            continue  # entirely in the past
        if start >= horizon_end:
            break
        if start > cursor:
            gap = start - cursor
            if gap >= duration and gap >= min_gap:
                return (cursor, cursor + duration)
        cursor = max(cursor, end)
        if cursor >= horizon_end:
            return None

    # Tail gap — from last busy end to horizon end.
    if horizon_end - cursor >= duration:
        return (cursor, cursor + duration)
    return None


def find_maintenance_window(
    db: Session,
    machine_id: int,
    duration_minutes: int,
    *,
    horizon_hours: int = _DEFAULT_HORIZON_HOURS,
    reference_time: Optional[datetime] = None,
) -> dict[str, Any]:
    """Find the next open window on a machine for a maintenance task.

    Parameters
    ----------
    db :
        Live SQLAlchemy session.
    machine_id :
        Integer machine ID to slot against.
    duration_minutes :
        Required contiguous idle minutes (setup + service + cooldown).
    horizon_hours :
        How far ahead to look. Default 72 (three days).
    reference_time :
        Optional "now" override (tests). Defaults to UTC naive now.

    Returns
    -------
    dict with keys:
        machine_id, duration_minutes, horizon_hours, slot (bool),
        slot_start, slot_end, reason, schedule_run_id, operations_considered.
    """
    # Avoid circular import (db_models → database → ...).
    from db_models import ScheduleRun

    if duration_minutes <= 0:
        raise ValueError(f"duration_minutes must be positive, got {duration_minutes}")
    if horizon_hours <= 0:
        raise ValueError(f"horizon_hours must be positive, got {horizon_hours}")

    now = reference_time or datetime.now(timezone.utc).replace(tzinfo=None)
    duration = timedelta(minutes=duration_minutes)
    horizon_end = now + timedelta(hours=horizon_hours)

    # Latest schedule run — the "canonical" plan to slot against.
    last_run = (
        db.query(ScheduleRun)
        .order_by(desc(ScheduleRun.created_at))
        .first()
    )

    if last_run is None:
        # No plan yet → machine is effectively idle for the whole horizon.
        return {
            "machine_id": machine_id,
            "duration_minutes": duration_minutes,
            "horizon_hours": horizon_hours,
            "slot": True,
            "slot_start": now.isoformat(),
            "slot_end": (now + duration).isoformat(),
            "reason": "no_active_schedule_machine_idle",
            "schedule_run_id": None,
            "operations_considered": 0,
        }

    try:
        scheduled = last_run.scheduled_orders
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        logger.warning("Failed to parse scheduled_orders on run %s: %s", last_run.id, exc)
        scheduled = []

    busy = _extract_operations_for_machine(scheduled, machine_id)

    if not busy:
        return {
            "machine_id": machine_id,
            "duration_minutes": duration_minutes,
            "horizon_hours": horizon_hours,
            "slot": True,
            "slot_start": now.isoformat(),
            "slot_end": (now + duration).isoformat(),
            "reason": "no_operations_on_machine",
            "schedule_run_id": last_run.id,
            "operations_considered": 0,
        }

    gap = _find_gap(busy, now, horizon_end, duration)

    if gap is None:
        return {
            "machine_id": machine_id,
            "duration_minutes": duration_minutes,
            "horizon_hours": horizon_hours,
            "slot": False,
            "slot_start": None,
            "slot_end": None,
            "reason": "no_sufficient_gap_in_horizon",
            "schedule_run_id": last_run.id,
            "operations_considered": len(busy),
        }

    start, end = gap
    return {
        "machine_id": machine_id,
        "duration_minutes": duration_minutes,
        "horizon_hours": horizon_hours,
        "slot": True,
        "slot_start": start.isoformat(),
        "slot_end": end.isoformat(),
        "reason": "gap_found",
        "schedule_run_id": last_run.id,
        "operations_considered": len(busy),
    }
