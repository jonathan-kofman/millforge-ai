"""
/api/schedule/nl — Natural-language schedule override endpoint.

Accepts an instruction + order list, applies priority overrides via the
NLSchedulerAgent, then runs the SA scheduler on the adjusted orders.
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from models.schemas import (
    NLScheduleRequest, NLScheduleResponse, PriorityOverrideItem,
    OrderInput,
)
from agents.nl_scheduler import NLSchedulerAgent
from agents.sa_scheduler import SAScheduler
from agents.scheduler import Order

# Re-use the shared response builder from schedule.py
from routers.schedule import _build_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schedule", tags=["Schedule"])

_nl_agent = NLSchedulerAgent()
_sa = SAScheduler()


@router.post(
    "/nl",
    response_model=NLScheduleResponse,
    summary="Schedule with a natural-language override instruction",
)
async def nl_schedule(req: NLScheduleRequest) -> NLScheduleResponse:
    """
    Apply a plain-English scheduling instruction, then run the SA optimizer.

    Example instructions:
    - "Rush all titanium orders — aerospace deadline moved up"
    - "Defer low priority steel to the end of the queue"
    - "Treat copper as urgent today"
    """
    logger.info(
        "NL schedule: instruction=%r orders=%d",
        req.instruction[:80], len(req.orders)
    )

    # 1. Interpret instruction → priority overrides
    try:
        nl_result = _nl_agent.interpret(req.instruction, req.orders)
    except Exception as exc:
        logger.error("NL interpret error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="NL interpretation error")

    # 2. Apply overrides to order list
    override_map = {ov.order_id: ov.new_priority for ov in nl_result.overrides}
    adjusted_orders = []
    for raw in req.orders:
        raw_copy = dict(raw)
        oid = str(raw_copy.get("order_id", ""))
        if oid in override_map:
            raw_copy["priority"] = override_map[oid]
        adjusted_orders.append(raw_copy)

    # 3. Convert to domain Order objects
    try:
        domain_orders = [_raw_to_order(o) for o in adjusted_orders]
    except Exception as exc:
        logger.error("Order conversion error: %s", exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"Invalid order data: {exc}")

    # 4. Run SA scheduler
    start_time = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        schedule = _sa.optimize(domain_orders, start_time=start_time)
    except Exception as exc:
        logger.error("SA scheduler error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    schedule_response = _build_response(schedule, "sa")

    return NLScheduleResponse(
        instruction=req.instruction,
        overrides_applied=[
            PriorityOverrideItem(
                order_id=ov.order_id,
                new_priority=ov.new_priority,
                reason=ov.reason,
            )
            for ov in nl_result.overrides
        ],
        override_summary=nl_result.summary,
        schedule=schedule_response,
        validation_failures=nl_result.validation_failures,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_to_order(raw: dict) -> Order:
    """Convert a raw order dict to the domain Order dataclass."""
    due_raw = raw.get("due_date", "")
    if isinstance(due_raw, str):
        due_raw = due_raw.rstrip("Z").split("+")[0]
        for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
            try:
                due = datetime.strptime(due_raw, fmt)
                break
            except ValueError:
                continue
        else:
            raise ValueError(f"Cannot parse due_date: {raw.get('due_date')}")
    elif isinstance(due_raw, datetime):
        due = due_raw.replace(tzinfo=None) if due_raw.tzinfo else due_raw
    else:
        raise ValueError(f"due_date must be a string or datetime, got {type(due_raw)}")

    return Order(
        order_id=str(raw.get("order_id", "")),
        material=str(raw.get("material", "steel")),
        quantity=int(raw.get("quantity", 1)),
        dimensions=str(raw.get("dimensions", "0x0x0mm")),
        due_date=due,
        priority=int(raw.get("priority", 5)),
        complexity=float(raw.get("complexity", 1.0)),
    )
