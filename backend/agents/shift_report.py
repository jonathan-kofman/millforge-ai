"""
ShiftReportAgent — automated end-of-shift handover.

Collects from DB:
  - Jobs completed (JobFeedbackRecord in shift window)
  - Held orders (OrderRecord status='held' updated in window)
  - Quality failures (InspectionRecord passed=False in window)
  - Rework dispatched (OrderRecord id starts with 'RW-' created in window)

Collects from live singletons (optional):
  - Jobs in progress (MachineFleet snapshot)
  - Open exceptions (ExceptionQueueAgent)

Generates both a JSON summary and a reportlab PDF.

Usage::

    agent = ShiftReportAgent()
    report = agent.gather(db, shift_start=start, shift_end=end,
                          fleet=machine_fleet, inventory_agent=_inventory)
    pdf_bytes = agent.build_pdf(report)
"""

from __future__ import annotations

import io
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from db_models import InspectionRecord, JobFeedbackRecord, OrderRecord

# Average machine power draw (kW) by material; fallback for energy estimate
_MACHINE_POWER_KW: Dict[str, float] = {
    "steel": 85.0,
    "aluminum": 55.0,
    "titanium": 110.0,
    "copper": 65.0,
}
_DEFAULT_POWER_KW = 70.0


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _power_kw(material: str) -> float:
    return _MACHINE_POWER_KW.get((material or "").lower(), _DEFAULT_POWER_KW)


class ShiftReportAgent:
    """Collects and formats end-of-shift data."""

    # ------------------------------------------------------------------
    # Data gathering
    # ------------------------------------------------------------------

    def gather(
        self,
        db: Session,
        *,
        shift_start: datetime,
        shift_end: datetime,
        fleet=None,
        inventory_agent=None,
    ) -> Dict[str, Any]:
        """
        Gather all shift data and return a structured report dict.

        Parameters
        ----------
        db : Session          SQLAlchemy session
        shift_start/end :     Window for DB queries (naive UTC datetimes)
        fleet :               Optional MachineFleet for live machine state
        inventory_agent :     Optional InventoryAgent to feed ExceptionQueueAgent
        """
        jobs_completed = self._jobs_completed(db, shift_start, shift_end)
        held_orders = self._held_orders(db, shift_start, shift_end)
        quality_failures = self._quality_failures(db, shift_start, shift_end)
        rework_dispatched = self._rework_dispatched(db, shift_start, shift_end)
        jobs_in_progress = self._jobs_in_progress(fleet)
        open_exceptions = self._open_exceptions(db, inventory_agent)
        energy = self._energy_summary(jobs_completed)

        summary = {
            "jobs_completed_count": len(jobs_completed),
            "jobs_in_progress_count": len(jobs_in_progress),
            "held_orders_count": len(held_orders),
            "quality_failures_count": len(quality_failures),
            "rework_dispatched_count": len(rework_dispatched),
            "open_exceptions_count": len(open_exceptions),
            "total_energy_kwh": round(energy["total_kwh"], 2),
            "estimated_energy_cost_usd": round(energy["cost_usd"], 2),
        }

        return {
            "shift_start": shift_start.isoformat(),
            "shift_end": shift_end.isoformat(),
            "generated_at": _now().isoformat(),
            "summary": summary,
            "jobs_completed": jobs_completed,
            "jobs_in_progress": jobs_in_progress,
            "held_orders": held_orders,
            "quality_failures": quality_failures,
            "rework_dispatched": rework_dispatched,
            "open_exceptions": open_exceptions,
            "energy": energy,
        }

    def _jobs_completed(
        self, db: Session, shift_start: datetime, shift_end: datetime
    ) -> List[dict]:
        """Jobs logged as complete by FeedbackLogger during this shift."""
        records = (
            db.query(JobFeedbackRecord)
            .filter(
                JobFeedbackRecord.logged_at >= shift_start,
                JobFeedbackRecord.logged_at <= shift_end,
            )
            .order_by(JobFeedbackRecord.logged_at.desc())
            .all()
        )
        return [
            {
                "order_id": r.order_id,
                "machine_id": r.machine_id,
                "material": r.material,
                "actual_setup_minutes": round(r.actual_setup_minutes, 1),
                "actual_processing_minutes": round(r.actual_processing_minutes, 1),
                "predicted_setup_minutes": round(r.predicted_setup_minutes, 1),
                "predicted_processing_minutes": round(r.predicted_processing_minutes, 1),
                "setup_delta_minutes": round(
                    r.actual_setup_minutes - r.predicted_setup_minutes, 1
                ),
                "processing_delta_minutes": round(
                    r.actual_processing_minutes - r.predicted_processing_minutes, 1
                ),
                "provenance": r.data_provenance,
                "logged_at": r.logged_at.isoformat(),
            }
            for r in records
        ]

    def _held_orders(
        self, db: Session, shift_start: datetime, shift_end: datetime
    ) -> List[dict]:
        """Orders with status='held' updated during this shift."""
        records = (
            db.query(OrderRecord)
            .filter(
                OrderRecord.status == "held",
                OrderRecord.updated_at >= shift_start,
                OrderRecord.updated_at <= shift_end,
            )
            .order_by(OrderRecord.updated_at.desc())
            .all()
        )
        return [
            {
                "order_id": r.order_id,
                "material": r.material,
                "quantity": r.quantity,
                "priority": r.priority,
                "due_date": r.due_date.isoformat(),
                "notes": r.notes,
                "held_at": r.updated_at.isoformat(),
            }
            for r in records
        ]

    def _quality_failures(
        self, db: Session, shift_start: datetime, shift_end: datetime
    ) -> List[dict]:
        """Inspections that failed during this shift."""
        records = (
            db.query(InspectionRecord)
            .filter(
                InspectionRecord.passed == False,  # noqa: E712
                InspectionRecord.created_at >= shift_start,
                InspectionRecord.created_at <= shift_end,
            )
            .order_by(InspectionRecord.created_at.desc())
            .all()
        )
        return [
            {
                "order_id": r.order_id_str or "",
                "confidence": round(r.confidence, 3),
                "defects": r.defects,
                "recommendation": r.recommendation,
                "inspector_version": r.inspector_version,
                "failed_at": r.created_at.isoformat(),
            }
            for r in records
        ]

    def _rework_dispatched(
        self, db: Session, shift_start: datetime, shift_end: datetime
    ) -> List[dict]:
        """Rework orders (RW- prefix) created during this shift."""
        records = (
            db.query(OrderRecord)
            .filter(
                OrderRecord.order_id.like("RW-%"),
                OrderRecord.created_at >= shift_start,
                OrderRecord.created_at <= shift_end,
            )
            .order_by(OrderRecord.created_at.desc())
            .all()
        )
        return [
            {
                "order_id": r.order_id,
                "original_order_id": r.order_id[3:],  # strip "RW-"
                "material": r.material,
                "priority": r.priority,
                "complexity": r.complexity,
                "due_date": r.due_date.isoformat(),
                "created_at": r.created_at.isoformat(),
            }
            for r in records
        ]

    def _jobs_in_progress(self, fleet) -> List[dict]:
        """Live machine states from MachineFleet (if available)."""
        if fleet is None:
            return []
        return [
            m for m in fleet.snapshot()
            if m["state"] not in ("IDLE",)
        ]

    def _open_exceptions(self, db: Session, inventory_agent) -> List[dict]:
        """Current open exceptions from ExceptionQueueAgent."""
        try:
            from agents.exception_queue import ExceptionQueueAgent
            agent = ExceptionQueueAgent(inventory_agent=inventory_agent)
            items = agent.gather(db, include_resolved=False, limit=50)
            return [
                {
                    "exc_id": e.exc_id,
                    "source": e.source,
                    "severity": e.severity,
                    "title": e.title,
                    "detail": e.detail,
                    "occurred_at": e.occurred_at.isoformat()
                    if isinstance(e.occurred_at, datetime)
                    else e.occurred_at,
                }
                for e in items
            ]
        except Exception:
            return []

    def _energy_summary(self, jobs_completed: List[dict]) -> dict:
        """Estimate energy consumed based on completed job minutes."""
        total_kwh = 0.0
        by_material: Dict[str, float] = {}

        for job in jobs_completed:
            material = job.get("material", "")
            kw = _power_kw(material)
            total_minutes = (
                job.get("actual_setup_minutes", 0)
                + job.get("actual_processing_minutes", 0)
            )
            kwh = kw * total_minutes / 60.0
            total_kwh += kwh
            by_material[material] = by_material.get(material, 0.0) + kwh

        # Blended rate ≈ $0.12/kWh (US industrial average)
        cost_usd = total_kwh * 0.12

        return {
            "total_kwh": round(total_kwh, 2),
            "cost_usd": round(cost_usd, 2),
            "by_material": {k: round(v, 2) for k, v in by_material.items()},
            "rate_per_kwh": 0.12,
            "note": "Estimated from FeedbackLogger actual run times × rated machine power.",
        }

    # ------------------------------------------------------------------
    # PDF export
    # ------------------------------------------------------------------

    def build_pdf(self, report: Dict[str, Any]) -> bytes:
        """Render the shift report as a PDF and return raw bytes."""
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import letter
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.lib.units import inch
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
            from reportlab.platypus import (
                SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            )
        except ImportError as exc:
            raise ImportError(
                "reportlab is required for PDF export — pip install reportlab"
            ) from exc

        PAGE_W, _ = letter
        MARGIN = 0.65 * inch
        CONTENT_W = PAGE_W - 2 * MARGIN

        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            leftMargin=MARGIN, rightMargin=MARGIN,
            topMargin=MARGIN, bottomMargin=MARGIN,
        )
        styles = getSampleStyleSheet()
        story = []

        # ---- helpers --------------------------------------------------
        h1 = styles["Heading1"]
        h1.alignment = TA_CENTER
        h2 = styles["Heading2"]
        h2.alignment = TA_LEFT
        normal = styles["Normal"]
        small = styles["Normal"]
        small.fontSize = 8

        BLUE = colors.HexColor("#2B6CB0")
        LIGHT_BLUE = colors.HexColor("#EBF8FF")
        RED_BG = colors.HexColor("#FFF5F5")
        GRAY = colors.HexColor("#718096")
        WHITE = colors.white

        def _header_style():
            return TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT_BLUE]),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ])

        # ---- Title ----------------------------------------------------
        story.append(Paragraph("MillForge Shift Handover Report", h1))

        summary = report["summary"]
        story.append(Paragraph(
            f"Shift: {report['shift_start'][:16]} → {report['shift_end'][:16]} UTC"
            f"  &nbsp;|&nbsp;  Generated: {report['generated_at'][:16]} UTC",
            normal,
        ))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Summary KPIs ---------------------------------------------
        kpi_data = [
            ["Metric", "Value"],
            ["Jobs Completed", str(summary["jobs_completed_count"])],
            ["Jobs In Progress", str(summary["jobs_in_progress_count"])],
            ["Held Orders", str(summary["held_orders_count"])],
            ["Quality Failures", str(summary["quality_failures_count"])],
            ["Rework Dispatched", str(summary["rework_dispatched_count"])],
            ["Open Exceptions", str(summary["open_exceptions_count"])],
            ["Energy Used (est.)", f"{summary['total_energy_kwh']} kWh  ≈  ${summary['estimated_energy_cost_usd']:.2f}"],
        ]
        kpi_tbl = Table(kpi_data, colWidths=[CONTENT_W * 0.5, CONTENT_W * 0.5])
        kpi_tbl.setStyle(_header_style())
        story.append(kpi_tbl)
        story.append(Spacer(1, 0.2 * inch))

        # ---- Jobs Completed -------------------------------------------
        story.append(Paragraph(f"Jobs Completed ({summary['jobs_completed_count']})", h2))
        if report["jobs_completed"]:
            cols = [CONTENT_W * c for c in [0.18, 0.10, 0.12, 0.14, 0.14, 0.14, 0.18]]
            jc_data = [["Order ID", "M#", "Material",
                         "Setup act/pred", "Proc act/pred",
                         "Setup Δ", "Prov."]]
            for j in report["jobs_completed"]:
                delta_s = j["setup_delta_minutes"]
                delta_p = j["processing_delta_minutes"]
                jc_data.append([
                    j["order_id"],
                    str(j["machine_id"]),
                    j["material"],
                    f"{j['actual_setup_minutes']}/{j['predicted_setup_minutes']}",
                    f"{j['actual_processing_minutes']}/{j['predicted_processing_minutes']}",
                    f"{'+' if delta_s >= 0 else ''}{delta_s}",
                    j["provenance"],
                ])
            jc_tbl = Table(jc_data, colWidths=cols, repeatRows=1)
            jc_tbl.setStyle(_header_style())
            story.append(jc_tbl)
        else:
            story.append(Paragraph("No jobs completed during this shift.", normal))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Jobs In Progress -----------------------------------------
        story.append(Paragraph(f"Machines In Progress ({summary['jobs_in_progress_count']})", h2))
        if report["jobs_in_progress"]:
            ip_data = [["Machine ID", "State", "Job ID"]]
            for m in report["jobs_in_progress"]:
                ip_data.append([str(m["machine_id"]), m["state"], m.get("job_id") or "—"])
            ip_tbl = Table(ip_data, colWidths=[CONTENT_W / 3] * 3)
            ip_tbl.setStyle(_header_style())
            story.append(ip_tbl)
        else:
            story.append(Paragraph("No machines currently in progress.", normal))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Held Orders ----------------------------------------------
        story.append(Paragraph(f"Held Orders ({summary['held_orders_count']})", h2))
        if report["held_orders"]:
            ho_data = [["Order ID", "Material", "Qty", "Priority", "Due Date"]]
            for o in report["held_orders"]:
                ho_data.append([
                    o["order_id"], o["material"], str(o["quantity"]),
                    str(o["priority"]), o["due_date"][:10],
                ])
            ho_tbl = Table(ho_data, colWidths=[CONTENT_W * c for c in [0.22, 0.18, 0.12, 0.12, 0.36]])
            s = _header_style()
            s.add("BACKGROUND", (0, 1), (-1, -1), RED_BG)
            ho_tbl.setStyle(s)
            story.append(ho_tbl)
        else:
            story.append(Paragraph("No held orders during this shift.", normal))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Quality Failures -----------------------------------------
        story.append(Paragraph(f"Quality Failures ({summary['quality_failures_count']})", h2))
        if report["quality_failures"]:
            qf_data = [["Order ID", "Confidence", "Defects", "Recommendation"]]
            for q in report["quality_failures"]:
                defects = ", ".join(q["defects"][:3]) or "—"
                qf_data.append([
                    q["order_id"] or "—",
                    f"{q['confidence']:.1%}",
                    defects,
                    q["recommendation"][:60],
                ])
            qf_tbl = Table(qf_data, colWidths=[CONTENT_W * c for c in [0.18, 0.12, 0.28, 0.42]])
            qf_tbl.setStyle(_header_style())
            story.append(qf_tbl)
        else:
            story.append(Paragraph("No quality failures during this shift.", normal))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Rework ---------------------------------------------------
        story.append(Paragraph(f"Rework Dispatched ({summary['rework_dispatched_count']})", h2))
        if report["rework_dispatched"]:
            rw_data = [["RW Order ID", "Original ID", "Material", "Priority", "Due Date"]]
            for r in report["rework_dispatched"]:
                rw_data.append([
                    r["order_id"], r["original_order_id"], r["material"],
                    str(r["priority"]), r["due_date"][:10],
                ])
            rw_tbl = Table(rw_data, colWidths=[CONTENT_W * c for c in [0.22, 0.22, 0.18, 0.12, 0.26]])
            rw_tbl.setStyle(_header_style())
            story.append(rw_tbl)
        else:
            story.append(Paragraph("No rework dispatched during this shift.", normal))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Open Exceptions ------------------------------------------
        story.append(Paragraph(f"Open Exceptions ({summary['open_exceptions_count']})", h2))
        if report["open_exceptions"]:
            ex_data = [["ID", "Source", "Severity", "Title"]]
            for e in report["open_exceptions"][:20]:  # cap at 20 for PDF
                ex_data.append([
                    e["exc_id"][:12], e["source"], e["severity"], e["title"][:60],
                ])
            ex_tbl = Table(ex_data, colWidths=[CONTENT_W * c for c in [0.14, 0.16, 0.12, 0.58]])
            s = _header_style()
            for i, e in enumerate(report["open_exceptions"][:20], start=1):
                if e["severity"] == "critical":
                    s.add("BACKGROUND", (0, i), (-1, i), RED_BG)
            ex_tbl.setStyle(s)
            story.append(ex_tbl)
        else:
            story.append(Paragraph("No open exceptions.", normal))
        story.append(Spacer(1, 0.15 * inch))

        # ---- Energy Summary -------------------------------------------
        story.append(Paragraph("Energy Summary (Estimated)", h2))
        energy = report["energy"]
        en_data = [
            ["Metric", "Value"],
            ["Total Energy Used", f"{energy['total_kwh']} kWh"],
            ["Estimated Cost", f"${energy['cost_usd']:.2f} @ ${energy['rate_per_kwh']}/kWh"],
        ]
        for mat, kwh in (energy.get("by_material") or {}).items():
            en_data.append([f"  {mat.capitalize()}", f"{kwh} kWh"])
        en_data.append(["Note", energy.get("note", "")])
        en_tbl = Table(en_data, colWidths=[CONTENT_W * 0.45, CONTENT_W * 0.55])
        en_tbl.setStyle(_header_style())
        story.append(en_tbl)
        story.append(Spacer(1, 0.2 * inch))

        # ---- Footer ---------------------------------------------------
        footer_style = styles["Normal"]
        footer_style.fontSize = 8
        footer_style.textColor = GRAY
        footer_style.alignment = TA_CENTER
        story.append(Paragraph(
            "MillForge — Lights-Out American Metal Manufacturing Intelligence  |  "
            "Auto-generated shift handover  |  No human touchpoint required.",
            footer_style,
        ))

        doc.build(story)
        return buf.getvalue()
