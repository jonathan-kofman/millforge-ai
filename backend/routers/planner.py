"""
/api/planner endpoints — weekly production capacity planning via Claude.
"""

import logging
from fastapi import APIRouter, HTTPException

from models.schemas import WeeklyPlanRequest, WeeklyPlanResponse, DailyPlanItem
from agents.production_planner import ProductionPlannerAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/planner", tags=["Planner"])

_planner = ProductionPlannerAgent()


@router.post(
    "/week",
    response_model=WeeklyPlanResponse,
    summary="Generate a weekly production plan from a demand forecast",
)
async def plan_week(req: WeeklyPlanRequest) -> WeeklyPlanResponse:
    """
    Translate a natural-language demand signal and capacity envelope into a
    concrete 5-day production plan.

    Uses Claude when ``ANTHROPIC_API_KEY`` is set; falls back to a
    deterministic heuristic planner otherwise (CI-safe).
    """
    logger.info("Planner week: demand=%r capacity=%s", req.demand_signal[:60], req.capacity)
    try:
        plan = _planner.plan_week(req.demand_signal, req.capacity)
    except Exception as exc:
        logger.error("Planner error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Production planner error")

    return WeeklyPlanResponse(
        week_start=plan.week_start,
        total_units_planned=plan.total_units_planned,
        daily_plans=[
            DailyPlanItem(
                day=dp.day,
                material=dp.material,
                units=dp.units,
                machine_hours=dp.machine_hours,
            )
            for dp in plan.daily_plans
        ],
        capacity_utilization_percent=plan.capacity_utilization_percent,
        bottlenecks=plan.bottlenecks,
        recommendations=plan.recommendations,
        validation_failures=plan.validation_failures,
        data_source=plan.data_source,
    )
