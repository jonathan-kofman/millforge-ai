"""
Shift handover report endpoints.

GET  /api/shift/report         — JSON shift summary (default: last 8 hours)
GET  /api/shift/report.pdf     — PDF download of the same report
POST /api/shift/report         — JSON with explicit shift_start / shift_end

Query params (GET):
  hours_back   int     (default 8)  — look back N hours from now
  shift_start  ISO-8601 datetime    — explicit window start (overrides hours_back)
  shift_end    ISO-8601 datetime    — explicit window end   (overrides hours_back)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/shift", tags=["Shift Handover"])

# ---------------------------------------------------------------------------
# Lazy singletons
# ---------------------------------------------------------------------------

def _get_agent():
    from agents.shift_report import ShiftReportAgent
    return ShiftReportAgent()


def _get_fleet():
    try:
        from main import machine_fleet
        return machine_fleet
    except ImportError:
        return None


def _get_inventory():
    try:
        from routers.inventory import _inventory
        return _inventory
    except ImportError:
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_window(
    hours_back: int,
    shift_start: Optional[str],
    shift_end: Optional[str],
):
    """Return (start, end) as naive UTC datetimes."""
    if shift_start and shift_end:
        try:
            start = datetime.fromisoformat(shift_start.replace("Z", "+00:00")).replace(tzinfo=None)
            end = datetime.fromisoformat(shift_end.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"Invalid datetime: {exc}") from exc
    else:
        end = datetime.now(timezone.utc).replace(tzinfo=None)
        start = end - timedelta(hours=max(1, min(hours_back, 168)))  # cap at 1 week
    if start >= end:
        raise HTTPException(status_code=422, detail="shift_start must be before shift_end")
    return start, end


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/report", summary="JSON shift handover report")
async def get_shift_report(
    hours_back: int = 8,
    shift_start: Optional[str] = None,
    shift_end: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Return a structured shift handover report as JSON.

    Covers jobs completed, held orders, quality failures, rework dispatched,
    open exceptions, and an energy consumption estimate — all scoped to the
    requested time window (default: last 8 hours).

    This endpoint eliminates the supervisor-writes-handover-notes touchpoint.
    """
    start, end = _parse_window(hours_back, shift_start, shift_end)
    agent = _get_agent()
    try:
        return agent.gather(
            db,
            shift_start=start,
            shift_end=end,
            fleet=_get_fleet(),
            inventory_agent=_get_inventory(),
        )
    except Exception as exc:
        logger.error("Shift report error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/report.pdf", summary="PDF shift handover report download")
async def get_shift_report_pdf(
    hours_back: int = 8,
    shift_start: Optional[str] = None,
    shift_end: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Download shift handover report as a PDF.

    Same data as `GET /api/shift/report` but rendered as a formatted PDF
    suitable for records or operator handoff.
    """
    start, end = _parse_window(hours_back, shift_start, shift_end)
    agent = _get_agent()
    try:
        report = agent.gather(
            db,
            shift_start=start,
            shift_end=end,
            fleet=_get_fleet(),
            inventory_agent=_get_inventory(),
        )
        pdf_bytes = agent.build_pdf(report)
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Shift PDF error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    filename = (
        f"millforge_shift_{start.strftime('%Y%m%d_%H%M')}"
        f"_to_{end.strftime('%Y%m%d_%H%M')}.pdf"
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class ShiftReportRequest(BaseModel):
    shift_start: str  # ISO-8601
    shift_end: str    # ISO-8601


@router.post("/report", summary="JSON shift handover report (explicit window)")
async def post_shift_report(
    req: ShiftReportRequest,
    db: Session = Depends(get_db),
):
    """POST variant with explicit shift_start / shift_end in the body."""
    start, end = _parse_window(8, req.shift_start, req.shift_end)
    agent = _get_agent()
    try:
        return agent.gather(
            db,
            shift_start=start,
            shift_end=end,
            fleet=_get_fleet(),
            inventory_agent=_get_inventory(),
        )
    except Exception as exc:
        logger.error("Shift report error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
