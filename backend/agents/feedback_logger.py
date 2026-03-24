"""
Job feedback logger — canonical IDs and data provenance tracking.

Canonical ID format:
    ORD-{order_id}_M{material}_MC{machine_id}_{YYYYMMDDTHHMMSS}

data_provenance values (trust ranking, highest first):
    operator_logged  — human entered the actual time at the machine
    mtconnect_auto   — pulled automatically from machine controller (MTConnect)
    estimated        — derived from production records; least trustworthy
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Literal

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

DataProvenance = Literal["operator_logged", "mtconnect_auto", "estimated"]


def _canonical_id(order_id: str, material: str, machine_id: int, ts: datetime) -> str:
    return f"ORD-{order_id}_M{material}_MC{machine_id}_{ts.strftime('%Y%m%dT%H%M%S')}"


class FeedbackLogger:
    """Records actual job outcomes for SchedulingTwin calibration."""

    def log(
        self,
        db: Session,
        order_id: str,
        material: str,
        machine_id: int,
        predicted_setup_minutes: float,
        actual_setup_minutes: float,
        predicted_processing_minutes: float,
        actual_processing_minutes: float,
        provenance: DataProvenance = "operator_logged",
    ):
        """Persist a single job outcome. Returns the saved JobFeedbackRecord."""
        from db_models import JobFeedbackRecord  # avoid circular import at module level

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        canonical_id = _canonical_id(order_id, material, machine_id, now)

        record = JobFeedbackRecord(
            canonical_id=canonical_id,
            order_id=order_id,
            material=material,
            machine_id=machine_id,
            predicted_setup_minutes=predicted_setup_minutes,
            actual_setup_minutes=actual_setup_minutes,
            predicted_processing_minutes=predicted_processing_minutes,
            actual_processing_minutes=actual_processing_minutes,
            data_provenance=provenance,
            logged_at=now,
        )
        db.add(record)
        db.commit()
        logger.info(
            "Feedback logged: %s | provenance=%s | setup_err=+%.1f min",
            canonical_id, provenance,
            actual_setup_minutes - predicted_setup_minutes,
        )
        return record

    def calibration_report(self, db: Session, limit: int = 50) -> dict:
        """Last `limit` jobs with predicted vs actual, grouped by provenance."""
        from db_models import JobFeedbackRecord

        records = (
            db.query(JobFeedbackRecord)
            .order_by(JobFeedbackRecord.logged_at.desc())
            .limit(limit)
            .all()
        )

        jobs = [
            {
                "canonical_id": r.canonical_id,
                "order_id": r.order_id,
                "material": r.material,
                "machine_id": r.machine_id,
                "predicted_setup_minutes": r.predicted_setup_minutes,
                "actual_setup_minutes": r.actual_setup_minutes,
                "setup_error_minutes": round(
                    r.actual_setup_minutes - r.predicted_setup_minutes, 2
                ),
                "predicted_processing_minutes": r.predicted_processing_minutes,
                "actual_processing_minutes": r.actual_processing_minutes,
                "processing_error_minutes": round(
                    r.actual_processing_minutes - r.predicted_processing_minutes, 2
                ),
                "data_provenance": r.data_provenance,
                "logged_at": r.logged_at.isoformat(),
            }
            for r in records
        ]

        by_prov: dict[str, list[float]] = defaultdict(list)
        for j in jobs:
            by_prov[j["data_provenance"]].append(abs(j["setup_error_minutes"]))

        provenance_summary = {
            prov: {
                "count": len(errs),
                "mean_abs_error_minutes": round(sum(errs) / len(errs), 2),
            }
            for prov, errs in by_prov.items()
        }

        return {
            "total_records": len(jobs),
            "jobs": jobs,
            "provenance_summary": provenance_summary,
        }
