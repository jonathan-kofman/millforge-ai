"""
/api/vision/inspect endpoint – quality inspection via computer vision.
"""

import json
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from db_models import InspectionRecord, OrderRecord
from models.schemas import VisionInspectRequest, VisionInspectResponse
from agents.quality_vision import QualityVisionAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Vision"])

_vision_agent = QualityVisionAgent()


@router.post(
    "/vision/inspect",
    response_model=VisionInspectResponse,
    summary="Inspect a part image for quality defects",
)
async def inspect_part(
    req: VisionInspectRequest,
    db: Session = Depends(get_db),
) -> VisionInspectResponse:
    """
    Accept an image URL and return a quality inspection result.

    The result is persisted to the database for traceability.
    Currently returns a simulated result — will be replaced with a
    real CV model in a future phase.
    """
    logger.info(f"Vision inspect: url={req.image_url} material={req.material}")

    if not req.image_url or not req.image_url.strip():
        raise HTTPException(status_code=422, detail="image_url cannot be empty")

    try:
        result = _vision_agent.inspect(
            image_url=req.image_url,
            material=req.material,
        )
    except Exception as e:
        logger.error(f"Vision agent error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Vision inspection engine error")

    # Resolve FK to OrderRecord if order_id was provided
    order_record_id = None
    if req.order_id:
        order_rec = db.query(OrderRecord).filter(OrderRecord.order_id == req.order_id).first()
        if order_rec:
            order_record_id = order_rec.id

    inspection = InspectionRecord(
        order_record_id=order_record_id,
        order_id_str=req.order_id,
        image_url=result.image_url,
        passed=result.passed,
        confidence=result.confidence,
        defects_json=json.dumps(result.defects_detected),
        recommendation=result.recommendation,
        inspector_version=result.inspector_version,
    )
    db.add(inspection)
    db.commit()
    logger.info(f"InspectionRecord saved: passed={result.passed} order_id={req.order_id}")

    return VisionInspectResponse(
        image_url=result.image_url,
        passed=result.passed,
        confidence=result.confidence,
        defects_detected=result.defects_detected,
        defect_severities=result.defect_severities,
        recommendation=result.recommendation,
        inspector_version=result.inspector_version,
        model=result.model,
        order_id=req.order_id,
    )
