"""
Tool Presetter router — receive measurements from CV presetter sub-project.

Prefix: /api/toolwear/preset
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import ToolRecord, ToolPresetMeasurement
from models.quality_models import (
    PresetMeasurementRequest, PresetMeasurementResponse,
)

logger = logging.getLogger("millforge.presetter_router")

router = APIRouter(prefix="/api/toolwear/preset", tags=["Tooling — CV Presetter"])


@router.post("/measurements", response_model=PresetMeasurementResponse, status_code=201)
def receive_measurement(req: PresetMeasurementRequest, db: Session = Depends(get_db)):
    """Receive a measurement from the CV presetter sub-project."""
    # Verify tool exists
    tool = db.query(ToolRecord).filter(ToolRecord.tool_id == req.tool_id).first()
    tool_updated = False

    # Store measurement
    measurement = ToolPresetMeasurement(
        tool_id=req.tool_id,
        measured_length_mm=req.measured_length_mm,
        measured_diameter_mm=req.measured_diameter_mm,
        image_path=req.image_path,
    )
    db.add(measurement)

    # Update tool record if it exists
    if tool is not None:
        try:
            from sqlalchemy import text
            db.execute(
                text("UPDATE tool_records SET measured_length_mm = :l, measured_diameter_mm = :d WHERE tool_id = :tid"),
                {"l": req.measured_length_mm, "d": req.measured_diameter_mm, "tid": req.tool_id}
            )
            tool_updated = True
        except Exception as exc:
            logger.warning("Could not update tool_records columns: %s", exc)

    db.commit()
    db.refresh(measurement)

    return PresetMeasurementResponse(
        id=measurement.id,
        tool_id=measurement.tool_id,
        measured_length_mm=measurement.measured_length_mm,
        measured_diameter_mm=measurement.measured_diameter_mm,
        measured_at=measurement.measured_at.isoformat(),
        tool_record_updated=tool_updated,
    )


@router.get("/measurements", response_model=list[PresetMeasurementResponse])
def list_measurements(
    tool_id: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List preset measurements."""
    q = db.query(ToolPresetMeasurement)
    if tool_id:
        q = q.filter(ToolPresetMeasurement.tool_id == tool_id)
    q = q.order_by(ToolPresetMeasurement.measured_at.desc())
    measurements = q.offset(skip).limit(limit).all()
    return [
        PresetMeasurementResponse(
            id=m.id, tool_id=m.tool_id,
            measured_length_mm=m.measured_length_mm,
            measured_diameter_mm=m.measured_diameter_mm,
            measured_at=m.measured_at.isoformat(),
        )
        for m in measurements
    ]
