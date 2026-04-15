"""
Job profitability autopsy — quoted vs actual margin analysis.

After a job finishes, compare what we ASSUMED at quote time
(estimated_run_min, estimated_setup_min, material price, labor rate)
against what ACTUALLY happened (actual_run_min, actual_setup_min, real
material cost). Surface the variance so the shop knows where its
estimates leak money.

Inputs are pulled from existing tables — no new schema:
  ShopQuote      — quoted price, predicted hours
  Operation      — actual_setup_min, actual_run_min, status=complete
  WorkCenter     — hourly_rate
  ScheduleRun    — when scheduled
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


@dataclass
class ProfitabilityReport:
    """Per-job quote-vs-actual breakdown."""
    job_id: str
    quoted_price_usd: float
    quoted_hours: float
    actual_hours: float
    actual_cost_usd: float
    realized_margin_usd: float
    quoted_margin_pct: Optional[float] = None
    actual_margin_pct: Optional[float] = None
    margin_drift_pp: Optional[float] = None
    setup_variance_min: Optional[float] = None
    run_variance_min: Optional[float] = None
    biggest_leak: Optional[str] = None  # "setup_overrun" | "run_overrun" | "material" | "rework"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "quoted_price_usd": round(self.quoted_price_usd, 2),
            "quoted_hours": round(self.quoted_hours, 2),
            "actual_hours": round(self.actual_hours, 2),
            "actual_cost_usd": round(self.actual_cost_usd, 2),
            "realized_margin_usd": round(self.realized_margin_usd, 2),
            "quoted_margin_pct": round(self.quoted_margin_pct, 1) if self.quoted_margin_pct is not None else None,
            "actual_margin_pct": round(self.actual_margin_pct, 1) if self.actual_margin_pct is not None else None,
            "margin_drift_pp": round(self.margin_drift_pp, 1) if self.margin_drift_pp is not None else None,
            "setup_variance_min": round(self.setup_variance_min, 1) if self.setup_variance_min is not None else None,
            "run_variance_min": round(self.run_variance_min, 1) if self.run_variance_min is not None else None,
            "biggest_leak": self.biggest_leak,
            "notes": self.notes,
        }


class ProfitabilityAnalyzer:
    """Runs quote-vs-actual analysis on completed operations."""

    def autopsy_quote(
        self,
        db: Session,
        *,
        shop_quote_id: int,
    ) -> Optional[ProfitabilityReport]:
        """
        Compute the autopsy for a single ShopQuote and its linked operations.
        Returns None if the quote doesn't exist or has no completed operations.
        """
        # Lazy imports to avoid coupling at module load
        from db_models import ShopQuote, Operation, WorkCenter

        quote = db.query(ShopQuote).filter(ShopQuote.id == shop_quote_id).first()
        if quote is None:
            return None

        ops = (
            db.query(Operation)
            .filter(Operation.shop_quote_id == shop_quote_id, Operation.status == "complete")
            .all()
        )
        if not ops:
            return None

        # Aggregate planned vs actual minutes
        quoted_run_min = sum((o.estimated_run_min or 0) for o in ops)
        quoted_setup_min = sum((o.estimated_setup_min or 0) for o in ops)
        actual_run_min = sum((o.actual_run_min or 0) for o in ops)
        actual_setup_min = sum((o.actual_setup_min or 0) for o in ops)

        # Cost = sum(minutes * hourly_rate / 60) per operation
        wc_lookup: dict[int, float] = {}
        for o in ops:
            if o.work_center_id and o.work_center_id not in wc_lookup:
                wc = db.query(WorkCenter).filter(WorkCenter.id == o.work_center_id).first()
                if wc and wc.hourly_rate:
                    wc_lookup[o.work_center_id] = float(wc.hourly_rate)

        actual_cost_usd = 0.0
        for o in ops:
            rate = wc_lookup.get(o.work_center_id, 80.0)  # default $80/hr
            mins = (o.actual_run_min or 0) + (o.actual_setup_min or 0)
            actual_cost_usd += (mins / 60.0) * rate

        # Material cost from quote (pass-through)
        actual_cost_usd += float(quote.material_cost or 0)
        # Subcontract cost from quote
        actual_cost_usd += float(quote.subcontract_cost or 0)

        quoted_price = float(quote.total_price or 0)
        realized_margin_usd = quoted_price - actual_cost_usd

        quoted_total_cost = (
            float(quote.material_cost or 0)
            + float(quote.labor_cost or 0)
            + float(quote.overhead_cost or 0)
            + float(quote.subcontract_cost or 0)
        )
        quoted_margin_pct = None
        actual_margin_pct = None
        if quoted_price > 0:
            quoted_margin_pct = (1.0 - quoted_total_cost / quoted_price) * 100.0
            actual_margin_pct = (1.0 - actual_cost_usd / quoted_price) * 100.0

        margin_drift = None
        if quoted_margin_pct is not None and actual_margin_pct is not None:
            margin_drift = actual_margin_pct - quoted_margin_pct

        setup_variance = actual_setup_min - quoted_setup_min
        run_variance = actual_run_min - quoted_run_min

        # Identify biggest leak
        biggest_leak: Optional[str] = None
        notes: list[str] = []
        if margin_drift is not None and margin_drift < -5:
            # Find the dominant variance
            candidates = {
                "setup_overrun": setup_variance,
                "run_overrun": run_variance,
            }
            biggest_leak = max(candidates, key=candidates.get) if any(v > 0 for v in candidates.values()) else None
            notes.append(f"Margin drifted {margin_drift:+.1f}pp from quote.")
        elif margin_drift is not None and margin_drift > 5:
            notes.append(f"Margin BEAT quote by {margin_drift:+.1f}pp — estimate was conservative.")

        if setup_variance > 0:
            pct = (setup_variance / max(quoted_setup_min, 1)) * 100
            notes.append(f"Setup ran {pct:.0f}% over plan ({setup_variance:.0f} extra minutes).")
        if run_variance > 0:
            pct = (run_variance / max(quoted_run_min, 1)) * 100
            notes.append(f"Run ran {pct:.0f}% over plan ({run_variance:.0f} extra minutes).")

        return ProfitabilityReport(
            job_id=str(quote.id),
            quoted_price_usd=quoted_price,
            quoted_hours=(quoted_run_min + quoted_setup_min) / 60.0,
            actual_hours=(actual_run_min + actual_setup_min) / 60.0,
            actual_cost_usd=actual_cost_usd,
            realized_margin_usd=realized_margin_usd,
            quoted_margin_pct=quoted_margin_pct,
            actual_margin_pct=actual_margin_pct,
            margin_drift_pp=margin_drift,
            setup_variance_min=setup_variance,
            run_variance_min=run_variance,
            biggest_leak=biggest_leak,
            notes=notes,
        )

    def shop_summary(self, db: Session, *, user_id: int, limit: int = 50) -> dict:
        """
        Roll up the last N quote autopsies for a shop. Returns aggregate
        metrics: avg margin drift, % of jobs with positive margin, top
        leak categories.
        """
        from db_models import ShopQuote

        quotes = (
            db.query(ShopQuote)
            .filter(
                ShopQuote.created_by_id == user_id,
                ShopQuote.status.in_(["accepted", "completed"]),
            )
            .order_by(ShopQuote.created_at.desc())
            .limit(limit)
            .all()
        )

        reports: list[ProfitabilityReport] = []
        for q in quotes:
            r = self.autopsy_quote(db, shop_quote_id=q.id)
            if r is not None:
                reports.append(r)

        if not reports:
            return {
                "user_id": user_id,
                "report_count": 0,
                "message": "no completed jobs with operations to analyze yet",
            }

        margin_drifts = [r.margin_drift_pp for r in reports if r.margin_drift_pp is not None]
        avg_drift = sum(margin_drifts) / len(margin_drifts) if margin_drifts else None
        positive_jobs = sum(1 for r in reports if r.realized_margin_usd > 0)

        leak_counts: dict[str, int] = {}
        for r in reports:
            if r.biggest_leak:
                leak_counts[r.biggest_leak] = leak_counts.get(r.biggest_leak, 0) + 1

        return {
            "user_id": user_id,
            "report_count": len(reports),
            "avg_margin_drift_pp": round(avg_drift, 2) if avg_drift is not None else None,
            "profitable_job_pct": round(positive_jobs / len(reports) * 100, 1),
            "top_leaks": sorted(leak_counts.items(), key=lambda x: -x[1]),
            "reports": [r.to_dict() for r in reports[:10]],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
