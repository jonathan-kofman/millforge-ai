"""
/api/schedule/nl — Natural-language schedule override endpoint.

Two variants:
  POST /api/schedule/nl       — stateless; caller supplies the order list
  POST /api/schedule/nl/auto  — DB-backed; fetches caller's pending orders,
                                applies NL overrides, persists ScheduleRun
"""

import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from db_models import User, OrderRecord, ScheduleRun
from auth.dependencies import get_current_user
from models.schemas import (
    NLScheduleRequest, NLScheduleResponse, PriorityOverrideItem,
    NLAutoScheduleRequest,
    OrderScheduleResponse, ScheduleSummary, ScheduledOrderOutput,
    GanttEntry, GanttDiffEntry,
)
from agents.nl_scheduler import NLSchedulerAgent
from agents.sa_scheduler import SAScheduler
from agents.scheduler import Order, Schedule

# Re-use the shared response builder from schedule.py
from routers.schedule import _build_response


def _schedule_to_gantt(schedule: Schedule) -> list[GanttEntry]:
    """Convert a Schedule domain object into a list of GanttEntry items."""
    return [
        GanttEntry(
            order_id=s.order.order_id,
            machine_id=s.machine_id,
            start=s.processing_start,
            end=s.completion_time,
            on_time=s.on_time,
        )
        for s in schedule.scheduled_orders
    ]


def _compute_gantt_diff(before: list[GanttEntry], after: list[GanttEntry]) -> list[GanttDiffEntry]:
    """
    For every order in either schedule, emit a per-order diff showing
    machine reassignments and start-time shifts. delta_minutes is positive
    when the order was pushed later by the override.
    """
    by_id_before = {e.order_id: e for e in before}
    by_id_after = {e.order_id: e for e in after}
    all_ids = sorted(set(by_id_before) | set(by_id_after))
    out: list[GanttDiffEntry] = []
    for oid in all_ids:
        b = by_id_before.get(oid)
        a = by_id_after.get(oid)
        delta = None
        if b and a:
            delta = round((a.start - b.start).total_seconds() / 60, 1)
        out.append(GanttDiffEntry(
            order_id=oid,
            machine_before=b.machine_id if b else None,
            machine_after=a.machine_id if a else None,
            start_before=b.start if b else None,
            start_after=a.start if a else None,
            delta_minutes=delta,
            machine_changed=bool(b and a and b.machine_id != a.machine_id),
        ))
    return out

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schedule", tags=["NL Scheduler"])

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

    # 1. Interpret instruction → priority overrides + machine-down + actions
    try:
        nl_result = _nl_agent.interpret(req.instruction, req.orders)
    except Exception as exc:
        logger.error("NL interpret error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="NL interpretation error")

    start_time = datetime.now(timezone.utc).replace(tzinfo=None)

    # 2. BEFORE schedule — convert orders as-is, run SA, snapshot the Gantt.
    # This is what would happen WITHOUT the operator's instruction.
    try:
        original_orders = [_raw_to_order(o) for o in req.orders]
    except Exception as exc:
        logger.error("Order conversion error (before): %s", exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"Invalid order data: {exc}")
    try:
        before_schedule = _sa.optimize(original_orders, start_time=start_time)
    except Exception as exc:
        logger.error("SA scheduler error (before): %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")
    gantt_before = _schedule_to_gantt(before_schedule)

    # 3. Apply overrides
    override_map = {ov.order_id: ov.new_priority for ov in nl_result.overrides}
    adjusted_orders = []
    for raw in req.orders:
        raw_copy = dict(raw)
        oid = str(raw_copy.get("order_id", ""))
        if oid in override_map:
            raw_copy["priority"] = override_map[oid]
        adjusted_orders.append(raw_copy)

    try:
        domain_orders = [_raw_to_order(o) for o in adjusted_orders]
    except Exception as exc:
        logger.error("Order conversion error (after): %s", exc, exc_info=True)
        raise HTTPException(status_code=422, detail=f"Invalid order data: {exc}")

    # 4. Build the AFTER scheduler. If a machine is down, drop it from
    # machine_count so all orders re-route to the survivors.
    sa_engine = _sa
    if nl_result.machine_down is not None:
        from agents.scheduler import MACHINE_COUNT as _MC
        survivors = max(1, _MC - 1)
        sa_engine = SAScheduler(machine_count=survivors)
        logger.info(
            "NL schedule: machine %d declared down, rescheduling on %d machines",
            nl_result.machine_down, survivors
        )

    try:
        schedule = sa_engine.optimize(domain_orders, start_time=start_time)
    except Exception as exc:
        logger.error("SA scheduler error (after): %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    gantt_after = _schedule_to_gantt(schedule)
    gantt_diff = _compute_gantt_diff(gantt_before, gantt_after)
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
        targeted_work_centers=nl_result.targeted_work_centers,
        machine_down=nl_result.machine_down,
        actions=nl_result.actions,
        gantt_before=gantt_before,
        gantt_after=gantt_after,
        gantt_diff=gantt_diff,
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


def _record_to_dict(rec: OrderRecord) -> dict:
    return {
        "order_id": rec.order_id,
        "material": rec.material,
        "quantity": rec.quantity,
        "dimensions": rec.dimensions,
        "due_date": rec.due_date.isoformat(),
        "priority": rec.priority,
        "complexity": rec.complexity,
    }


# ---------------------------------------------------------------------------
# DB-backed auto endpoint
# ---------------------------------------------------------------------------

@router.post(
    "/nl/auto",
    response_model=OrderScheduleResponse,
    summary="NL-driven schedule of your pending orders (DB-backed)",
)
async def nl_auto_schedule(
    req: NLAutoScheduleRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderScheduleResponse:
    """
    Fetch your pending orders from the database, apply the natural-language
    priority override via Claude, run the SA optimizer, and persist the result.

    This is the fully automated variant — no manual order serialization needed.

    - **instruction**: plain-English override, e.g. *"Rush all titanium orders"*
    """
    records = (
        db.query(OrderRecord)
        .filter(OrderRecord.created_by_id == user.id, OrderRecord.status == "pending")
        .all()
    )
    if not records:
        raise HTTPException(status_code=400, detail="No pending orders to schedule")

    # Build order dicts for NL agent
    order_dicts = [_record_to_dict(r) for r in records]

    # Interpret instruction → priority overrides
    try:
        nl_result = _nl_agent.interpret(req.instruction, order_dicts)
    except Exception as exc:
        logger.error("NL auto interpret error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="NL interpretation error")

    # Apply overrides back to DB records (in-memory only — commit after schedule)
    override_map = {ov.order_id: ov.new_priority for ov in nl_result.overrides}
    for rec in records:
        if rec.order_id in override_map:
            rec.priority = override_map[rec.order_id]

    # Convert to domain Order objects and run SA
    domain_orders = [
        Order(
            order_id=r.order_id,
            material=r.material,
            quantity=r.quantity,
            dimensions=r.dimensions,
            due_date=r.due_date,
            priority=r.priority,
            complexity=r.complexity,
        )
        for r in records
    ]

    start_time = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        schedule = _sa.optimize(domain_orders, start_time=start_time)
    except Exception as exc:
        logger.error("NL auto scheduler error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    summary_data = {
        "total_orders": schedule.total_orders,
        "on_time_count": schedule.on_time_count,
        "on_time_rate_percent": round(schedule.on_time_rate, 2),
        "makespan_hours": round(schedule.makespan_hours, 2),
        "utilization_percent": round(schedule.utilization_percent, 1),
    }
    schedule_rows = [
        {
            "order_id": s.order.order_id,
            "machine_id": s.machine_id,
            "material": s.order.material,
            "quantity": s.order.quantity,
            "setup_start": s.setup_start.isoformat(),
            "processing_start": s.processing_start.isoformat(),
            "completion_time": s.completion_time.isoformat(),
            "setup_minutes": s.setup_minutes,
            "processing_minutes": s.processing_minutes,
            "on_time": s.on_time,
            "lateness_hours": s.lateness_hours,
            "due_date": s.order.due_date.isoformat(),
        }
        for s in schedule.scheduled_orders
    ]

    run = ScheduleRun(
        algorithm="sa+nl",
        order_ids_json=json.dumps([r.order_id for r in records]),
        summary_json=json.dumps({**summary_data, "nl_instruction": req.instruction}),
        on_time_rate=schedule.on_time_rate,
        makespan_hours=schedule.makespan_hours,
        schedule_json=json.dumps(schedule_rows),
        created_by_id=user.id,
    )
    db.add(run)
    for rec in records:
        rec.status = "scheduled"
    db.commit()
    db.refresh(run)

    logger.info(
        "NL auto schedule: run_id=%d overrides=%d orders=%d on_time=%.1f%% user=%s",
        run.id, len(nl_result.overrides), len(records), schedule.on_time_rate, user.email,
    )

    outputs = [
        ScheduledOrderOutput(
            order_id=s.order.order_id,
            machine_id=s.machine_id,
            material=s.order.material,
            quantity=s.order.quantity,
            setup_start=s.setup_start,
            processing_start=s.processing_start,
            completion_time=s.completion_time,
            setup_minutes=s.setup_minutes,
            processing_minutes=s.processing_minutes,
            on_time=s.on_time,
            lateness_hours=s.lateness_hours,
            due_date=s.order.due_date,
        )
        for s in schedule.scheduled_orders
    ]

    return OrderScheduleResponse(
        schedule_run_id=run.id,
        orders_scheduled=len(records),
        algorithm="sa+nl",
        generated_at=schedule.generated_at,
        summary=ScheduleSummary(**summary_data),
        schedule=outputs,
    )
