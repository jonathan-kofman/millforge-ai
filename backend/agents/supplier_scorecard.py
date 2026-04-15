"""
Subcontractor scorecard — auto-track supplier performance across jobs.

Each time an Operation is marked complete with `is_subcontracted=True`,
this module rolls up:
  - on_time_pct       — completed_at vs due_date
  - quality_pass_pct  — % of operations with no NCR
  - avg_lead_days     — completed_at − created_at
  - total_jobs        — number of operations the supplier ran
  - cost_drift_pct    — actual vs quoted cost (when both available)

Combined into a 0..100 grade so the operator can rank suppliers without
manually crunching spreadsheets.

Pure aggregation — no new schema. Reads:
  Operation        (subcontractor_name, status, completed_at, etc.)
  NonConformanceReport
  Supplier         (for join when a name matches the directory)
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class SupplierScorecard:
    supplier_name: str
    total_jobs: int = 0
    completed_jobs: int = 0
    on_time_jobs: int = 0
    on_time_pct: float = 0.0
    quality_pass_pct: float = 100.0
    avg_lead_days: Optional[float] = None
    grade: float = 0.0  # 0..100
    grade_letter: str = "F"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "supplier_name": self.supplier_name,
            "total_jobs": self.total_jobs,
            "completed_jobs": self.completed_jobs,
            "on_time_jobs": self.on_time_jobs,
            "on_time_pct": round(self.on_time_pct, 1),
            "quality_pass_pct": round(self.quality_pass_pct, 1),
            "avg_lead_days": round(self.avg_lead_days, 1) if self.avg_lead_days is not None else None,
            "grade": round(self.grade, 1),
            "grade_letter": self.grade_letter,
            "notes": self.notes,
        }


def _grade_letter(score: float) -> str:
    if score >= 95: return "A+"
    if score >= 90: return "A"
    if score >= 85: return "A-"
    if score >= 80: return "B+"
    if score >= 75: return "B"
    if score >= 70: return "B-"
    if score >= 65: return "C+"
    if score >= 60: return "C"
    if score >= 55: return "C-"
    if score >= 50: return "D"
    return "F"


class SupplierScorecardAgent:
    """Aggregates Operation history into per-supplier performance scores."""

    def score_one(
        self,
        db: Session,
        *,
        supplier_name: str,
        user_id: Optional[int] = None,
        window_days: int = 365,
    ) -> Optional[SupplierScorecard]:
        """
        Build a scorecard for a single supplier name. Returns None if the
        supplier has no operation history in the window.
        """
        from db_models import Operation, NonConformanceReport

        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)
        q = (
            db.query(Operation)
            .filter(
                Operation.subcontractor_name == supplier_name,
                Operation.created_at >= cutoff,
            )
        )
        if user_id is not None:
            q = q.filter(Operation.user_id == user_id)
        ops = q.all()

        if not ops:
            return None

        total = len(ops)
        completed = [o for o in ops if o.status == "complete"]
        on_time = 0
        lead_days_acc: list[float] = []

        for o in completed:
            # Use sub_lead_days as the baseline expected lead from the supplier
            expected_days = o.subcontractor_lead_days
            if o.completed_at and o.created_at:
                lead = (o.completed_at - o.created_at).total_seconds() / 86400.0
                lead_days_acc.append(lead)
                if expected_days is None or lead <= expected_days:
                    on_time += 1
            else:
                # Missing timestamps — count as on-time to avoid penalising
                on_time += 1

        on_time_pct = (on_time / max(len(completed), 1)) * 100.0
        avg_lead = sum(lead_days_acc) / len(lead_days_acc) if lead_days_acc else None

        # Quality: count NCRs that reference these operations
        op_ids = [o.id for o in completed]
        ncr_count = 0
        if op_ids:
            ncr_count = (
                db.query(NonConformanceReport)
                .filter(NonConformanceReport.operation_id.in_(op_ids))
                .count()
            )
        quality_pct = ((len(completed) - ncr_count) / max(len(completed), 1)) * 100.0

        # Composite grade — weighted: 50% on-time, 40% quality, 10% lead-time-vs-promise
        lead_grade = 80.0  # neutral default
        if avg_lead is not None and ops[0].subcontractor_lead_days:
            promise = ops[0].subcontractor_lead_days
            ratio = avg_lead / promise if promise else 1.0
            # 1.0 = on time, <1 better, >1 worse
            lead_grade = max(0.0, min(100.0, 100.0 - (ratio - 1.0) * 100.0))

        grade = (
            0.50 * on_time_pct
            + 0.40 * quality_pct
            + 0.10 * lead_grade
        )

        notes: list[str] = []
        if on_time_pct < 70:
            notes.append("On-time rate below 70% — consider risk pricing.")
        if quality_pct < 90:
            notes.append(f"{ncr_count} NCR(s) in window — quality concern.")
        if avg_lead is not None and ops[0].subcontractor_lead_days and avg_lead > ops[0].subcontractor_lead_days * 1.2:
            notes.append("Average lead time runs >20% over promised — pad estimates.")

        return SupplierScorecard(
            supplier_name=supplier_name,
            total_jobs=total,
            completed_jobs=len(completed),
            on_time_jobs=on_time,
            on_time_pct=on_time_pct,
            quality_pass_pct=quality_pct,
            avg_lead_days=avg_lead,
            grade=grade,
            grade_letter=_grade_letter(grade),
            notes=notes,
        )

    def score_all(
        self,
        db: Session,
        *,
        user_id: Optional[int] = None,
        window_days: int = 365,
    ) -> list[SupplierScorecard]:
        """Score every distinct subcontractor seen in the window."""
        from db_models import Operation
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)

        q = (
            db.query(Operation.subcontractor_name)
            .filter(
                Operation.subcontractor_name.isnot(None),
                Operation.created_at >= cutoff,
            )
            .distinct()
        )
        if user_id is not None:
            q = q.filter(Operation.user_id == user_id)

        names = [row[0] for row in q.all() if row[0]]
        out: list[SupplierScorecard] = []
        for name in names:
            sc = self.score_one(db, supplier_name=name, user_id=user_id, window_days=window_days)
            if sc is not None:
                out.append(sc)
        out.sort(key=lambda s: -s.grade)
        return out
