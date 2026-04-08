"""
/api/learning — setup time ML accuracy and job feedback calibration report.
"""

import logging
import threading
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from agents.setup_time_predictor import SetupTimePredictor
from agents.feedback_logger import FeedbackLogger
from database import get_db, SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/learning", tags=["Learning"])

_predictor = SetupTimePredictor()
_feedback_logger = FeedbackLogger()


class FeedbackLogRequest(BaseModel):
    order_id: str
    material: str
    machine_id: int = Field(ge=1)
    actual_setup_minutes: float = Field(ge=0)
    actual_processing_minutes: float = Field(ge=0)
    predicted_setup_minutes: float = Field(default=0.0, ge=0)
    predicted_processing_minutes: float = Field(default=0.0, ge=0)
    provenance: Literal["operator_logged", "mtconnect_auto", "estimated"] = "operator_logged"
    simulation_confidence: Optional[float] = Field(None, ge=0.0, le=1.0)
    tolerance_class: Optional[str] = None


def _maybe_auto_retrain(total: int) -> None:
    """Fire background retrain when total feedback count hits a 10-record milestone ≥ 20."""
    if total < 20 or total % 10 != 0:
        return

    def _retrain() -> None:
        db = SessionLocal()
        try:
            result = _predictor.train_from_db(db)
            logger.info("Auto-retrain triggered at %d records: %s", total, result)
        except Exception as exc:
            logger.warning("Auto-retrain failed: %s", exc)
        finally:
            db.close()

    threading.Thread(target=_retrain, daemon=True).start()


@router.get("/setup-time-accuracy", summary="Setup time ML model accuracy")
async def setup_time_accuracy():
    """
    Returns accuracy metrics for the RandomForest setup time predictor.

    When untrained (<20 feedback records), reports fallback to SETUP_MATRIX.
    """
    return _predictor.accuracy_report()


@router.post("/feedback", summary="Log actual job times for scheduling twin calibration")
async def log_feedback(req: FeedbackLogRequest, db: Session = Depends(get_db)):
    """
    Operator-submitted actual setup and processing times for a completed job.
    Used to calibrate the RandomForest setup time predictor.
    Requires 20+ records before the ML model activates (falls back to SETUP_MATRIX until then).
    """
    record = _feedback_logger.log(
        db,
        order_id=req.order_id,
        material=req.material,
        machine_id=req.machine_id,
        predicted_setup_minutes=req.predicted_setup_minutes,
        actual_setup_minutes=req.actual_setup_minutes,
        predicted_processing_minutes=req.predicted_processing_minutes,
        actual_processing_minutes=req.actual_processing_minutes,
        provenance=req.provenance,
        simulation_confidence=req.simulation_confidence,
        tolerance_class=req.tolerance_class,
    )

    from db_models import JobFeedbackRecord
    total = db.query(JobFeedbackRecord).count()
    _maybe_auto_retrain(total)

    return {"status": "logged", "canonical_id": record.canonical_id}


@router.post("/retrain", summary="Retrain setup time predictor on all feedback records")
async def retrain(db: Session = Depends(get_db)):
    """
    Manually trigger a retrain of the RandomForest setup time predictor
    on all stored JobFeedbackRecord rows.

    Returns accuracy metrics. Requires ≥20 records to train.
    """
    return _predictor.train_from_db(db)


@router.get("/calibration-report", summary="Predicted vs actual job metrics (last 50 jobs)")
async def calibration_report(db: Session = Depends(get_db)):
    """
    Last 50 logged jobs showing predicted vs actual setup and processing times,
    colour-coded by data provenance (operator_logged / mtconnect_auto / estimated).
    """
    return _feedback_logger.calibration_report(db)
