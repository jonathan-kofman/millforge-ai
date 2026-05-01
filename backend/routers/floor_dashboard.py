"""Floor dashboard router — `/api/floor`.

Operator-facing snapshot of the shop floor that fuses MillForge's own
DB (Job, Operation, WorkCenter, ShopFloorEvent) with the lights-out
state aria_os writes to its SQLite events log on the same host.

The aria_os half is read through `services.floor_state_reader` which
opens the DB pointed to by `ARIA_FLOOR_DB_PATH` in **read-only** mode.
If that env var isn't set or the file isn't there, the endpoints still
return a sensible payload — the `aria_floor.state` field tells the UI
to hide the aria-side widgets rather than show errors.

Endpoints:

  GET /api/floor/snapshot          full operator dashboard payload
  GET /api/floor/machine/{id}      per-machine deep dive
  GET /api/floor/alerts            active alerts only (for paging UI)
  GET /api/floor/timeline          raw event timeline with optional filters
  GET /api/floor/stats             shop-wide rollups (today vs window)

Authentication mirrors the rest of the dashboard surface — same JWT
cookie via `get_current_user`. Bridge endpoints in aria_bridge.py keep
their own X-API-Key gate; this router is operator-side only.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import (
    Job, Operation, WorkCenter, ShopFloorEvent, NonConformanceReport, User,
)
from services import floor_state_reader as floor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/floor", tags=["Floor Dashboard"])


# ---------------------------------------------------------------------------
# MillForge-side rollups (no aria_os dependency)
# ---------------------------------------------------------------------------

def _job_stage_counts(db: Session, user_id: int) -> dict[str, int]:
    rows = (
        db.query(Job.stage, func.count(Job.id))
        .filter((Job.created_by_id == user_id) | (Job.created_by_id.is_(None)))
        .group_by(Job.stage)
        .all()
    )
    out: dict[str, int] = {
        "queued": 0, "in_progress": 0, "qc_pending": 0,
        "complete": 0, "qc_failed": 0, "pending_cam": 0,
    }
    for stage, n in rows:
        out[stage] = int(n)
    return out


def _operation_status_counts(db: Session, user_id: int) -> dict[str, int]:
    rows = (
        db.query(Operation.status, func.count(Operation.id))
        .filter(Operation.user_id == user_id)
        .group_by(Operation.status)
        .all()
    )
    out: dict[str, int] = {}
    for st, n in rows:
        out[st] = int(n)
    return out


def _work_center_status(db: Session, user_id: int) -> list[dict]:
    wcs = (
        db.query(WorkCenter)
        .filter(WorkCenter.user_id == user_id)
        .order_by(WorkCenter.id)
        .all()
    )
    out: list[dict] = []
    for wc in wcs:
        active = (
            db.query(func.count(Operation.id))
            .filter(
                Operation.work_center_id == wc.id,
                Operation.status == "in_progress",
            )
            .scalar()
            or 0
        )
        queued = (
            db.query(func.count(Operation.id))
            .filter(
                Operation.work_center_id == wc.id,
                Operation.status.in_(("pending", "queued")),
            )
            .scalar()
            or 0
        )
        out.append({
            "id": wc.id,
            "name": wc.name,
            "category": wc.category,
            "status": wc.status,
            "active_ops": int(active),
            "queued_ops": int(queued),
            "hourly_rate": wc.hourly_rate,
        })
    return out


def _open_ncrs(db: Session, user_id: int, *, limit: int = 10) -> list[dict]:
    rows = (
        db.query(NonConformanceReport)
        .join(Operation, NonConformanceReport.operation_id == Operation.id)
        .filter(Operation.user_id == user_id)
        .filter(NonConformanceReport.status != "closed")
        .order_by(NonConformanceReport.id.desc())
        .limit(limit)
        .all()
    )
    return [{
        "id": r.id,
        "operation_id": r.operation_id,
        "status": r.status,
        "severity": r.severity,
        "description": r.description,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    } for r in rows]


def _today_throughput(db: Session, user_id: int) -> dict:
    """Operations completed today + cycle-time accuracy."""
    since = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    completed = (
        db.query(Operation)
        .filter(
            Operation.user_id == user_id,
            Operation.status == "complete",
            Operation.completed_at >= since,
        )
        .all()
    )
    qty_done = sum(int(op.quantity_complete or 0) for op in completed)
    qty_scrap = sum(int(op.quantity_scrapped or 0) for op in completed)
    actual_min = sum(
        float(op.actual_run_min or 0) + float(op.actual_setup_min or 0)
        for op in completed
    )
    estimated_min = sum(
        float(op.estimated_run_min or 0) + float(op.estimated_setup_min or 0)
        for op in completed
    )
    accuracy = None
    if estimated_min > 0 and actual_min > 0:
        accuracy = round(actual_min / estimated_min * 100.0, 1)
    return {
        "operations_completed": len(completed),
        "units_good": qty_done,
        "units_scrap": qty_scrap,
        "actual_minutes": round(actual_min, 1),
        "estimated_minutes": round(estimated_min, 1),
        "cycle_time_accuracy_pct": accuracy,
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "/snapshot",
    summary="Operator dashboard composite snapshot",
    description=(
        "Single payload covering every widget on the operator floor view: "
        "MillForge job stages + work centers + NCRs, plus aria_os machines, "
        "queue, gauging queue, open POs, alerts, and 24h energy rollup."
    ),
)
def get_snapshot(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    aria = floor.snapshot()
    return {
        "as_of": aria["as_of"],
        "aria_floor": aria["aria_floor"],
        "millforge": {
            "job_stages": _job_stage_counts(db, user.id),
            "operation_status": _operation_status_counts(db, user.id),
            "work_centers": _work_center_status(db, user.id),
            "open_ncrs": _open_ncrs(db, user.id),
            "today_throughput": _today_throughput(db, user.id),
        },
        "aria": {
            "machines": aria["machines"],
            "queue": aria["queue"],
            "gauging": aria["gauging"],
            "purchase_orders": aria["purchase_orders"],
            "alerts": aria["alerts"],
            "energy_24h": aria["energy_24h"],
        },
    }


@router.get(
    "/machine/{machine_id}",
    summary="Per-machine deep dive",
    description=(
        "Machine envelope, current job, recent jobs, and last 50 events. "
        "Returns 404 when aria_os state is unavailable or the id is unknown."
    ),
)
def get_machine_detail(
    machine_id: int,
    timeline_limit: int = Query(50, ge=1, le=500),
    _user: User = Depends(get_current_user),
):
    if floor.db_status()["state"] != "ok":
        raise HTTPException(
            status_code=503,
            detail="aria_os floor DB is not available — set ARIA_FLOOR_DB_PATH",
        )
    detail = floor.machine_detail(machine_id, timeline_limit=timeline_limit)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"machine_id={machine_id} not found in aria_os floor DB",
        )
    return detail


@router.get(
    "/alerts",
    summary="Active alerts on the floor",
    description=(
        "Returns the non-cleared alert events from the aria_os events log. "
        "Severities: critical | high | medium | low. UI groups by severity."
    ),
)
def get_alerts(
    since_s: Optional[float] = Query(
        None,
        description="Lookback in seconds — default returns full history",
    ),
    limit: int = Query(50, ge=1, le=500),
    _user: User = Depends(get_current_user),
):
    since_ts: Optional[float] = None
    if since_s is not None:
        since_ts = time.time() - float(since_s)
    items = floor.alerts(since_ts=since_ts, limit=limit)
    by_sev: dict[str, int] = {}
    for a in items:
        by_sev[a["severity"]] = by_sev.get(a["severity"], 0) + 1
    return {
        "aria_floor": floor.db_status(),
        "count": len(items),
        "by_severity": by_sev,
        "alerts": items,
    }


@router.get(
    "/timeline",
    summary="Raw event timeline",
    description=(
        "Newest-first event stream from the aria_os events log. Useful for "
        "ops debugging and the operator audit pane. Pass `kinds` repeatedly "
        "to filter (e.g. ?kinds=machine_down&kinds=watchdog_trip)."
    ),
)
def get_timeline(
    since_s: Optional[float] = Query(
        86400.0,
        description="Lookback in seconds — defaults to last 24 hours",
    ),
    kinds: Optional[list[str]] = Query(None),
    limit: int = Query(200, ge=1, le=2000),
    _user: User = Depends(get_current_user),
):
    cutoff = time.time() - float(since_s) if since_s else 0.0
    events = floor.timeline(since_ts=cutoff, kinds=kinds, limit=limit)
    return {
        "aria_floor": floor.db_status(),
        "since_ts": cutoff,
        "count": len(events),
        "events": events,
    }


@router.get(
    "/stats",
    summary="Shop-wide rollups",
    description=(
        "Aggregates that don't live anywhere else: queue counts, open POs, "
        "energy 24h, today's throughput. Cheap enough to poll every 30s."
    ),
)
def get_stats(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return {
        "as_of": time.time(),
        "aria_floor": floor.db_status(),
        "queue": floor.queue_counts(),
        "gauging": floor.gauging_queue_summary(),
        "open_purchase_orders": len(floor.open_purchase_orders()),
        "energy_24h": floor.energy_summary(),
        "millforge": {
            "job_stages": _job_stage_counts(db, user.id),
            "today_throughput": _today_throughput(db, user.id),
        },
    }
