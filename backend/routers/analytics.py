"""
/api/analytics — QC defect analytics + product analytics + health score.
"""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from db_models import (
    Job, QCResult, User, ProductEvent, ScheduleRun, OrderRecord, Operation,
)
from auth.dependencies import get_current_user, get_current_user_optional
from models.schemas import QCAnalyticsResponse, QCAnalyticsItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


# ---------------------------------------------------------------------------
# Product analytics — self-hosted event log + health score
# ---------------------------------------------------------------------------

EVENT_CATEGORIES = {
    "scheduling", "quality", "supplier", "energy",
    "onboarding", "billing", "operator", "bridge",
}


class ProductEventRequest(BaseModel):
    event_category: str = Field(..., description="scheduling | quality | supplier | energy | onboarding | billing | operator | bridge")
    event_type: str = Field(..., max_length=100, description="schedule_run | nl_override | qc_inspected | supplier_searched | energy_analysis | order_created | quote_generated | etc.")
    source_table: Optional[str] = Field(None, max_length=100)
    source_id: Optional[int] = None
    payload: Optional[dict[str, Any]] = None


class ProductEventResponse(BaseModel):
    id: int
    event_category: str
    event_type: str
    occurred_at: datetime


def record_event(
    db: Session,
    *,
    user_id: Optional[int],
    event_category: str,
    event_type: str,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    payload: Optional[dict[str, Any]] = None,
) -> Optional[ProductEvent]:
    """
    Module-level helper for other routers to fire-and-forget product events
    without coupling to the analytics route handlers. Never raises — silent
    failure is preferable to dropping the original request.
    """
    try:
        category = (event_category or "").strip().lower()
        if category not in EVENT_CATEGORIES:
            category = "other"
        ev = ProductEvent(
            user_id=user_id,
            event_category=category,
            event_type=str(event_type)[:100],
            source_table=str(source_table)[:100] if source_table else None,
            source_id=source_id,
            payload_json=json.dumps(payload) if payload else None,
        )
        db.add(ev)
        db.commit()
        return ev
    except Exception as exc:
        logger.warning("record_event failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        return None


@router.post("/event", response_model=ProductEventResponse)
def post_event(
    req: ProductEventRequest,
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
):
    """
    Record a product analytics event. Used by the frontend to track every
    meaningful user action (schedule run, quote generated, supplier
    searched, etc.) so the founder dashboard can compute engagement.
    Auth is optional — anonymous events are accepted with user_id=None.
    """
    ev = record_event(
        db,
        user_id=user.id if user else None,
        event_category=req.event_category,
        event_type=req.event_type,
        source_table=req.source_table,
        source_id=req.source_id,
        payload=req.payload,
    )
    if ev is None:
        raise HTTPException(status_code=500, detail="failed to record event")
    return ProductEventResponse(
        id=ev.id,
        event_category=ev.event_category,
        event_type=ev.event_type,
        occurred_at=ev.occurred_at,
    )


@router.get("/health-score")
def health_score(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    4-pillar product health score in [0..100] for the authenticated user.

    Weights:
      30% scheduling: latest ScheduleRun.on_time_rate
      25% quality:    QCResult pass rate over the user's jobs
      20% supplier:   % of operations with a supplier resolution path
      25% energy:     1 - (current_cost / baseline_cost) when energy
                      analysis exists; otherwise neutral 70

    Returns the final score plus per-pillar breakdown so the dashboard
    can show why the score is what it is.
    """
    pillars: dict[str, dict[str, Any]] = {}

    # 1. Scheduling pillar — latest schedule run on-time rate
    latest_run = (
        db.query(ScheduleRun)
        .filter(ScheduleRun.created_by_id == user.id)
        .order_by(ScheduleRun.created_at.desc())
        .first()
    )
    if latest_run and latest_run.on_time_rate is not None:
        sched_score = round(float(latest_run.on_time_rate), 1)
    else:
        sched_score = 70.0  # neutral when no data
    pillars["scheduling"] = {
        "score": sched_score,
        "weight": 0.30,
        "source": "latest ScheduleRun.on_time_rate" if latest_run else "no data — neutral",
    }

    # 2. Quality pillar — pass rate over user's QC results
    user_jobs = [j.id for j in db.query(Job.id).filter(Job.created_by_id == user.id).all()]
    if user_jobs:
        qc_rows = db.query(QCResult).filter(QCResult.job_id.in_(user_jobs)).all()
        if qc_rows:
            passed = sum(1 for r in qc_rows if r.passed)
            quality_score = round(passed / len(qc_rows) * 100, 1)
        else:
            quality_score = 70.0
    else:
        quality_score = 70.0
    pillars["quality"] = {
        "score": quality_score,
        "weight": 0.25,
        "source": "QCResult pass rate" if user_jobs else "no jobs — neutral",
    }

    # 3. Supplier pillar — % of operations marked as resolved (have a work_center
    # OR a subcontractor_name set). Falls back to neutral if no operations.
    user_ops_q = db.query(Operation).filter(Operation.user_id == user.id)
    total_ops = user_ops_q.count()
    if total_ops:
        resolved = user_ops_q.filter(
            (Operation.work_center_id.isnot(None))
            | (Operation.subcontractor_name.isnot(None))
        ).count()
        supplier_score = round(resolved / total_ops * 100, 1)
    else:
        supplier_score = 70.0
    pillars["supplier"] = {
        "score": supplier_score,
        "weight": 0.20,
        "source": "operations with work_center or subcontractor" if total_ops else "no ops — neutral",
    }

    # 4. Energy pillar — count of energy events in last 30 days as a proxy
    # for engagement with energy intelligence. 5+ events = 100, scaled down.
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    energy_events = (
        db.query(func.count(ProductEvent.id))
        .filter(
            ProductEvent.user_id == user.id,
            ProductEvent.event_category == "energy",
            ProductEvent.occurred_at >= cutoff,
        )
        .scalar() or 0
    )
    energy_score = round(min(100.0, energy_events / 5.0 * 100.0), 1) if energy_events else 50.0
    pillars["energy"] = {
        "score": energy_score,
        "weight": 0.25,
        "source": f"{energy_events} energy events in last 30 days",
    }

    # Weighted total
    total = sum(p["score"] * p["weight"] for p in pillars.values())
    return {
        "user_id": user.id,
        "health_score": round(total, 1),
        "pillars": pillars,
        "generated_at": datetime.now(timezone.utc),
    }


@router.get("/founder")
def founder_dashboard(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    """
    Cross-tenant founder dashboard. Aggregates ProductEvent counts by
    category over the last 7 days plus DAU and total active shops.

    NOTE: any authenticated user can hit this right now — the proper
    founder gate (admin role flag) is a TODO. Acceptable for v0 since
    the dashboard is unlinked from any UI route.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=7)

    by_category = (
        db.query(ProductEvent.event_category, func.count(ProductEvent.id))
        .filter(ProductEvent.occurred_at >= cutoff)
        .group_by(ProductEvent.event_category)
        .all()
    )
    by_type = (
        db.query(ProductEvent.event_type, func.count(ProductEvent.id))
        .filter(ProductEvent.occurred_at >= cutoff)
        .group_by(ProductEvent.event_type)
        .order_by(func.count(ProductEvent.id).desc())
        .limit(20)
        .all()
    )
    daily = (
        db.query(func.count(func.distinct(ProductEvent.user_id)))
        .filter(
            ProductEvent.occurred_at >= now - timedelta(days=1),
            ProductEvent.user_id.isnot(None),
        )
        .scalar() or 0
    )
    active_shops_7d = (
        db.query(func.count(func.distinct(ProductEvent.user_id)))
        .filter(
            ProductEvent.occurred_at >= cutoff,
            ProductEvent.user_id.isnot(None),
        )
        .scalar() or 0
    )

    return {
        "window_days": 7,
        "dau": int(daily),
        "active_shops_7d": int(active_shops_7d),
        "events_by_category": [{"category": c, "count": int(n)} for c, n in by_category],
        "top_event_types": [{"type": t, "count": int(n)} for t, n in by_type],
        "generated_at": now,
    }


@router.get("/qc", response_model=QCAnalyticsResponse)
def qc_analytics(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Defect rate by machine_type and material across all QC results for this user's jobs.
    """
    job_ids = [j.id for j in db.query(Job.id).filter(Job.created_by_id == user.id).all()]

    if not job_ids:
        return QCAnalyticsResponse(
            total_inspections=0,
            overall_pass_rate_percent=0.0,
            by_machine_type=[],
            by_material=[],
            generated_at=datetime.now(timezone.utc),
        )

    results = db.query(QCResult).filter(QCResult.job_id.in_(job_ids)).all()
    total = len(results)

    if total == 0:
        return QCAnalyticsResponse(
            total_inspections=0,
            overall_pass_rate_percent=0.0,
            by_machine_type=[],
            by_material=[],
            generated_at=datetime.now(timezone.utc),
        )

    overall_passed = sum(1 for r in results if r.passed)
    overall_pass_rate = round(overall_passed / total * 100, 1)

    # Build job lookup
    jobs = {j.id: j for j in db.query(Job).filter(Job.id.in_(job_ids)).all()}

    # Aggregate by machine_type and material
    def _make_bucket():
        return {"total": 0, "passed": 0, "defects": defaultdict(int)}

    by_machine: dict = defaultdict(_make_bucket)
    by_material: dict = defaultdict(_make_bucket)

    for r in results:
        job = jobs.get(r.job_id)
        mtype = (job.required_machine_type or "unknown") if job else "unknown"
        mat = (job.material or "unknown") if job else "unknown"

        for dim_key, bucket_dict in [(mtype, by_machine), (mat, by_material)]:
            b = bucket_dict[dim_key]
            b["total"] += 1
            if r.passed:
                b["passed"] += 1
            for defect in r.defects_found:
                b["defects"][defect] += 1

    def _to_items(bucket_dict: dict, dimension: str) -> list:
        items = []
        for val, b in bucket_dict.items():
            top = sorted(b["defects"].items(), key=lambda x: -x[1])[:3]
            items.append(QCAnalyticsItem(
                dimension=dimension,
                value=val,
                total_inspections=b["total"],
                passed=b["passed"],
                failed=b["total"] - b["passed"],
                pass_rate_percent=round(b["passed"] / b["total"] * 100, 1),
                top_defects=[d for d, _ in top],
            ))
        return sorted(items, key=lambda x: -x.total_inspections)

    return QCAnalyticsResponse(
        total_inspections=total,
        overall_pass_rate_percent=overall_pass_rate,
        by_machine_type=_to_items(by_machine, "machine_type"),
        by_material=_to_items(by_material, "material"),
        generated_at=datetime.now(timezone.utc),
    )
