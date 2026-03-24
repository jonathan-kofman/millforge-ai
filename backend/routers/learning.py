"""
/api/learning — setup time ML accuracy and job feedback calibration report.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agents.setup_time_predictor import SetupTimePredictor
from agents.feedback_logger import FeedbackLogger
from database import get_db

router = APIRouter(prefix="/api/learning", tags=["Learning"])

_predictor = SetupTimePredictor()
_feedback_logger = FeedbackLogger()


@router.get("/setup-time-accuracy", summary="Setup time ML model accuracy")
async def setup_time_accuracy():
    """
    Returns accuracy metrics for the RandomForest setup time predictor.

    When untrained (<20 feedback records), reports fallback to SETUP_MATRIX.
    """
    return _predictor.accuracy_report()


@router.get("/calibration-report", summary="Predicted vs actual job metrics (last 50 jobs)")
async def calibration_report(db: Session = Depends(get_db)):
    """
    Last 50 logged jobs showing predicted vs actual setup and processing times,
    colour-coded by data provenance (operator_logged / mtconnect_auto / estimated).
    """
    return _feedback_logger.calibration_report(db)
