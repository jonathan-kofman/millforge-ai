"""
/api/energy endpoints — energy cost estimation and optimal start windows.
"""

import logging
from fastapi import APIRouter, HTTPException

from models.schemas import EnergyEstimateRequest, EnergyEstimateResponse
from agents.energy_optimizer import EnergyOptimizer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/energy", tags=["Energy"])

_optimizer = EnergyOptimizer()


@router.post(
    "/estimate",
    response_model=EnergyEstimateResponse,
    summary="Estimate energy cost for a production run",
)
async def estimate_energy(req: EnergyEstimateRequest) -> EnergyEstimateResponse:
    """
    Estimate the energy cost for a machine run of the given material and duration.
    Returns kWh, USD cost, and an optimization recommendation.
    """
    logger.info(
        "Energy estimate: material=%s duration=%.1fh start=%s",
        req.material.value, req.duration_hours, req.start_time.isoformat(),
    )
    try:
        # Normalise to naive UTC so comparisons work consistently
        start = req.start_time.replace(tzinfo=None) if req.start_time.tzinfo else req.start_time
        profile = _optimizer.estimate_energy_cost(start, req.duration_hours, req.material.value)
    except Exception as exc:
        logger.error("Energy estimate error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Energy estimation error")

    return EnergyEstimateResponse(
        start_time=profile.start_time,
        end_time=profile.end_time,
        material=profile.material,
        estimated_kwh=round(profile.estimated_kwh, 2),
        estimated_cost_usd=round(profile.estimated_cost_usd, 2),
        peak_rate=profile.peak_rate,
        off_peak_rate=profile.off_peak_rate,
        recommendation=profile.recommendation,
        data_source=profile.data_source,
        validation_failures=profile.validation_failures,
    )
