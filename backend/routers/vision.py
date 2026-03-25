"""
/api/vision/inspect endpoint – quality inspection via computer vision.
"""

import json
import logging
import subprocess
import threading
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from db_models import InspectionRecord, OrderRecord, User
from models.schemas import VisionInspectRequest, VisionInspectResponse
from agents.quality_vision import QualityVisionAgent, MODEL_AVAILABLE
from auth.dependencies import get_current_user

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
        model_map50=result.model_map50,
        order_id=req.order_id,
        inspection_mode="onnx" if MODEL_AVAILABLE else "heuristic",
    )


@router.post(
    "/vision/train",
    summary="Trigger NEU-DET model training in background (requires auth)",
)
async def trigger_training(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Kick off YOLOv8n training on NEU Surface Defect Database in background.
    Returns immediately; training runs async.
    Check /health for vision_model_trained status once complete.
    """
    script_path = Path(__file__).parent.parent / "scripts" / "train_vision_model.py"
    if not script_path.exists():
        return JSONResponse(
            status_code=404,
            content={"error": "Training script not found", "path": str(script_path)}
        )

    def run_training():
        import sys
        try:
            subprocess.run([sys.executable, str(script_path)], check=True)
            logger.info("Vision model training completed successfully")
        except subprocess.CalledProcessError as exc:
            logger.error("Vision model training failed: %s", exc)

    thread = threading.Thread(target=run_training, daemon=True)
    thread.start()

    return {
        "status": "training_started",
        "estimated_time_minutes": 15,
        "note": "Check GET /health for vision_model_trained status when complete",
        "script": str(script_path),
    }
