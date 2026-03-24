"""
/api/anomaly endpoints — detect anomalous patterns in order batches.
"""

import logging
from fastapi import APIRouter, HTTPException

from models.schemas import AnomalyDetectRequest, AnomalyDetectResponse, AnomalyItem
from agents.anomaly_detector import AnomalyDetector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/anomaly", tags=["Anomaly"])

_detector = AnomalyDetector()


@router.post(
    "/detect",
    response_model=AnomalyDetectResponse,
    summary="Detect anomalous patterns in an order batch",
)
async def detect_anomalies(req: AnomalyDetectRequest) -> AnomalyDetectResponse:
    """
    Analyse a batch of orders for unusual patterns such as quantity spikes,
    impossible deadlines, duplicate IDs, and material clustering.

    Returns a list of anomalies with severity levels and a plain-English summary.
    """
    logger.info("Anomaly detect: %d orders", len(req.orders))
    try:
        report = _detector.detect(req.orders)
    except Exception as exc:
        logger.error("Anomaly detection error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Anomaly detection error")

    return AnomalyDetectResponse(
        orders_analysed=report.orders_analysed,
        anomalies=[
            AnomalyItem(
                order_id=a.order_id,
                anomaly_type=a.anomaly_type,
                severity=a.severity,
                description=a.description,
            )
            for a in report.anomalies
        ],
        summary=report.summary,
        analysed_at=report.analysed_at,
        validation_failures=report.validation_failures,
    )
