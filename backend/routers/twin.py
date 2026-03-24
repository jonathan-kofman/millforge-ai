"""
/api/twin — scheduling digital twin accuracy endpoint.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agents.scheduling_twin import SchedulingTwin
from database import get_db

router = APIRouter(prefix="/api/twin", tags=["Digital Twin"])

_twin = SchedulingTwin()


@router.get("/accuracy", summary="Twin prediction accuracy vs logged actuals")
async def twin_accuracy(db: Session = Depends(get_db)):
    """
    Compares SchedulingTwin predictions against JobFeedbackRecord actuals.

    Returns MAE for setup and processing time, plus ML model status.
    Returns a friendly message when no feedback data has been logged yet.
    """
    return _twin.accuracy_report(db)
