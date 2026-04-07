"""
Drawing Reader router — upload engineering drawings, extract GD&T, generate inspection plans.

Prefix: /api/quality/drawing
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from db_models import DrawingInspection, AS9100AuditTrail, AS9100ComplianceStatus
from agents.drawing_reader import DrawingReaderAgent
from models.quality_models import (
    DrawingUploadResponse, InspectionPlanResponse, DrawingListItem,
    GDTCallout as GDTCalloutSchema, InspectionStep as InspectionStepSchema,
)

logger = logging.getLogger("millforge.drawing_router")

router = APIRouter(prefix="/api/quality/drawing", tags=["Quality — Drawing Reader"])

_agent = DrawingReaderAgent()


def _as9100_enabled(db: Session, user_id: int) -> bool:
    return db.query(AS9100ComplianceStatus).filter(
        AS9100ComplianceStatus.user_id == user_id
    ).first() is not None


def _record_audit_trail(db: Session, user_id: int, event_type: str,
                        source_table: str, source_id: int, description: str) -> None:
    if not _as9100_enabled(db, user_id):
        return
    trail = AS9100AuditTrail(
        user_id=user_id,
        event_type=event_type,
        source_table=source_table,
        source_id=source_id,
        description=description,
    )
    db.add(trail)
    db.commit()


@router.post("/upload", response_model=DrawingUploadResponse, status_code=201)
async def upload_drawing(
    file: UploadFile = File(...),
    job_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Upload an engineering drawing PDF, extract GD&T callouts."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    callouts = _agent.extract_callouts(pdf_bytes)

    callouts_data = [
        {
            "feature_id": c.feature_id,
            "dimension_type": c.dimension_type,
            "nominal": c.nominal,
            "tolerance_plus": c.tolerance_plus,
            "tolerance_minus": c.tolerance_minus,
            "datum_refs": c.datum_refs,
            "surface_finish": c.surface_finish,
            "gdt_symbol": c.gdt_symbol,
            "units": c.units,
        }
        for c in callouts
    ]

    record = DrawingInspection(
        job_id=job_id,
        filename=file.filename,
        callouts_json=json.dumps(callouts_data),
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    return DrawingUploadResponse(
        id=record.id,
        filename=record.filename,
        callouts=[
            GDTCalloutSchema(**c) for c in callouts_data
        ],
        callout_count=len(callouts_data),
        status=record.status,
    )


@router.get("/{drawing_id}", response_model=DrawingUploadResponse)
def get_drawing(drawing_id: int, db: Session = Depends(get_db)):
    """Get a single drawing with callouts."""
    record = db.query(DrawingInspection).filter(DrawingInspection.id == drawing_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail=f"Drawing {drawing_id} not found")

    callouts_data = record.callouts
    return DrawingUploadResponse(
        id=record.id,
        filename=record.filename,
        callouts=[GDTCalloutSchema(**c) for c in callouts_data],
        callout_count=len(callouts_data),
        status=record.status,
    )


@router.get("", response_model=list[DrawingListItem])
def list_drawings(
    job_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List drawings with optional filtering."""
    q = db.query(DrawingInspection)
    if job_id is not None:
        q = q.filter(DrawingInspection.job_id == job_id)
    if status:
        q = q.filter(DrawingInspection.status == status)
    q = q.order_by(DrawingInspection.created_at.desc())
    records = q.offset(skip).limit(limit).all()
    return [
        DrawingListItem(
            id=r.id,
            filename=r.filename,
            callout_count=len(r.callouts),
            status=r.status,
            job_id=r.job_id,
            created_at=r.created_at.isoformat(),
        )
        for r in records
    ]


@router.post("/{drawing_id}/generate-plan", response_model=InspectionPlanResponse)
def generate_plan(drawing_id: int, db: Session = Depends(get_db)):
    """Generate or regenerate an inspection plan from the extracted callouts."""
    record = db.query(DrawingInspection).filter(DrawingInspection.id == drawing_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail=f"Drawing {drawing_id} not found")

    from agents.drawing_reader import GDTCallout as AgentCallout
    callouts = [
        AgentCallout(**c) for c in record.callouts
    ]
    plan = _agent.generate_inspection_plan(callouts)

    plan_data = [
        {
            "sequence": s.sequence,
            "feature_id": s.feature_id,
            "measurement_method": s.measurement_method,
            "instrument": s.instrument,
            "acceptance_criteria": s.acceptance_criteria,
            "notes": s.notes,
        }
        for s in plan.steps
    ]
    record.inspection_plan_json = json.dumps(plan_data)
    record.instruments_json = json.dumps(plan.instruments_required)
    db.commit()

    return InspectionPlanResponse(
        id=record.id,
        steps=[InspectionStepSchema(**s) for s in plan_data],
        total_estimated_time_minutes=plan.total_estimated_time_minutes,
        instruments_required=plan.instruments_required,
        status=record.status,
    )


@router.post("/{drawing_id}/approve-plan")
def approve_plan(drawing_id: int, db: Session = Depends(get_db)):
    """Approve the inspection plan (locks it for use)."""
    record = db.query(DrawingInspection).filter(DrawingInspection.id == drawing_id).first()
    if record is None:
        raise HTTPException(status_code=404, detail=f"Drawing {drawing_id} not found")

    if not record.inspection_plan:
        raise HTTPException(status_code=400, detail="No inspection plan generated yet")

    record.status = "approved"
    db.commit()

    _record_audit_trail(
        db, user_id=0,
        event_type="inspection_plan_approved",
        source_table="drawing_inspections",
        source_id=record.id,
        description=f"Inspection plan approved for drawing: {record.filename}",
    )

    return {"status": "approved", "drawing_id": drawing_id}
