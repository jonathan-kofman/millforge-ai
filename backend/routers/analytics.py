"""
/api/analytics — QC defect analytics aggregated across all jobs.
"""

import logging
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from db_models import Job, QCResult, User
from auth.dependencies import get_current_user
from models.schemas import QCAnalyticsResponse, QCAnalyticsItem

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


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
