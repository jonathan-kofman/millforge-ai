"""
/api/schedule/rework endpoint – schedule rework orders from failed inspections.

Accepts a list of failed-inspection items (order_id, material, quantity,
defect_severity) and schedules them as priority-1 rework orders with a
complexity boost calibrated to defect severity.

Severity → complexity multiplier:
  critical  → 2.5×  (full rework, tight deadline 24 h)
  major     → 1.8×  (significant rework,          48 h)
  minor     → 1.3×  (light rework,                72 h)
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict

from fastapi import APIRouter, HTTPException

from models.schemas import ReworkItem, ReworkRequest, ReworkScheduleResponse, ScheduleResponse
from agents.scheduler import Order
from agents.sa_scheduler import SAScheduler
from routers.schedule import _build_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Schedule"])

_sa = SAScheduler()

# Severity → (complexity_multiplier, deadline_hours)
_SEVERITY_CONFIG: Dict[str, tuple[float, int]] = {
    "critical": (2.5, 24),
    "major":    (1.8, 48),
    "minor":    (1.3, 72),
}
_DEFAULT_CONFIG = (1.5, 48)


def _rework_order_id(original_id: str) -> str:
    return f"RW-{original_id}"


def _item_to_order(item: ReworkItem) -> tuple[Order, float]:
    """Convert a ReworkItem to an Order domain object and return the complexity multiplier."""
    severity = item.defect_severity.lower()
    multiplier, deadline_hours = _SEVERITY_CONFIG.get(severity, _DEFAULT_CONFIG)

    due = (
        item.due_date.replace(tzinfo=None) if item.due_date and item.due_date.tzinfo is not None
        else item.due_date
    )
    if due is None:
        due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=deadline_hours)

    order = Order(
        order_id=_rework_order_id(item.order_id),
        material=item.material.value,
        quantity=item.quantity,
        dimensions=item.dimensions,
        due_date=due,
        priority=1,          # rework is always highest urgency
        complexity=multiplier,
    )
    return order, multiplier


@router.post(
    "/schedule/rework",
    response_model=ReworkScheduleResponse,
    summary="Schedule rework orders from failed quality inspections",
)
async def schedule_rework(req: ReworkRequest) -> ReworkScheduleResponse:
    """
    Convert failed inspection results into priority-1 rework orders and
    return an optimised schedule.

    Each rework order is assigned:
    - **priority = 1** (highest urgency)
    - **complexity** scaled by defect severity (critical=2.5×, major=1.8×, minor=1.3×)
    - **due_date** defaulting to 24 h / 48 h / 72 h from now if not provided
    """
    logger.info("Rework schedule request: %d items", len(req.items))

    # Validate severities
    valid_severities = {"critical", "major", "minor"}
    invalid = [
        item.order_id
        for item in req.items
        if item.defect_severity.lower() not in valid_severities
    ]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown defect_severity for orders: {invalid}. Must be critical|major|minor.",
        )

    orders: list[Order] = []
    complexity_boosts: Dict[str, float] = {}

    for item in req.items:
        order, multiplier = _item_to_order(item)
        orders.append(order)
        complexity_boosts[order.order_id] = multiplier

    start_time = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        schedule = _sa.optimize(orders, start_time=start_time)
    except Exception as e:
        logger.error("Rework scheduler error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    sched_response: ScheduleResponse = _build_response(schedule, algorithm="sa")

    return ReworkScheduleResponse(
        rework_orders_count=len(orders),
        complexity_boosts=complexity_boosts,
        schedule=sched_response,
    )
