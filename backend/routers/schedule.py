"""
/api/schedule endpoint – optimize a production schedule from a list of orders.
"""

import time
import logging
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, HTTPException, Query

from models.schemas import (
    ScheduleRequest, ScheduleResponse, ScheduleSummary,
    ScheduledOrderOutput, OrderInput, BenchmarkResponse, BenchmarkEntry,
)
from agents.scheduler import Scheduler, Order, get_mock_orders
from agents.sa_scheduler import SAScheduler

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Schedule"])

# Instantiated once — SA is stateless between calls
_edd = Scheduler()
_sa  = SAScheduler()


def _build_response(schedule, algorithm: str) -> ScheduleResponse:
    """Convert a Schedule domain object to a ScheduleResponse."""
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
    summary = ScheduleSummary(
        total_orders=schedule.total_orders,
        on_time_count=schedule.on_time_count,
        on_time_rate_percent=schedule.on_time_rate,
        makespan_hours=round(schedule.makespan_hours, 2),
        utilization_percent=round(schedule.utilization_percent, 1),
    )
    return ScheduleResponse(
        generated_at=schedule.generated_at,
        summary=summary,
        schedule=outputs,
        algorithm=algorithm,
    )


@router.post("/schedule", response_model=ScheduleResponse, summary="Optimize production schedule")
async def optimize_schedule(
    req: ScheduleRequest,
    algorithm: str = Query("sa", enum=["edd", "sa"], description="edd = greedy EDD, sa = simulated annealing"),
) -> ScheduleResponse:
    """
    Optimize a production schedule for the provided order list.

    - **edd**: Earliest Due Date with greedy machine assignment (fast, O(n log n))
    - **sa**: Simulated Annealing optimizer — minimizes weighted tardiness (default, recommended)
    """
    logger.info(f"Schedule request: {len(req.orders)} orders | algorithm={algorithm}")

    orders = [_order_input_to_domain(o) for o in req.orders]
    start_time = req.start_time or datetime.now(timezone.utc).replace(tzinfo=None)
    engine = _sa if algorithm == "sa" else _edd

    try:
        schedule = engine.optimize(orders, start_time=start_time)
    except Exception as e:
        logger.error(f"Scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    return _build_response(schedule, algorithm)


@router.get("/schedule/demo", response_model=ScheduleResponse, summary="Demo schedule with mock data")
async def demo_schedule(
    algorithm: str = Query("sa", enum=["edd", "sa"]),
) -> ScheduleResponse:
    """Return a schedule built from the built-in mock order dataset."""
    mock_orders = get_mock_orders()
    engine = _sa if algorithm == "sa" else _edd
    try:
        schedule = engine.optimize(mock_orders)
    except Exception as e:
        logger.error(f"Demo scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")
    return _build_response(schedule, algorithm)


@router.get("/schedule/benchmark", response_model=BenchmarkResponse, summary="Compare EDD vs SA on mock data")
async def benchmark_schedule() -> BenchmarkResponse:
    """
    Run both EDD and SA on the mock order dataset and return a side-by-side
    comparison. Used by the frontend BenchmarkPanel and useful for demos.
    """
    mock_orders = get_mock_orders()

    t0 = time.perf_counter()
    edd_sched = _edd.optimize(mock_orders)
    edd_ms = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    sa_sched = _sa.optimize(mock_orders)
    sa_ms = (time.perf_counter() - t0) * 1000

    def _entry(sched, algo, ms) -> BenchmarkEntry:
        return BenchmarkEntry(
            algorithm=algo,
            on_time_rate_percent=sched.on_time_rate,
            makespan_hours=round(sched.makespan_hours, 2),
            utilization_percent=round(sched.utilization_percent, 1),
            on_time_count=sched.on_time_count,
            total_orders=sched.total_orders,
            solve_ms=round(ms, 1),
        )

    edd_entry = _entry(edd_sched, "edd", edd_ms)
    sa_entry  = _entry(sa_sched,  "sa",  sa_ms)

    improvement = round(sa_entry.on_time_rate_percent - edd_entry.on_time_rate_percent, 1)

    return BenchmarkResponse(
        edd=edd_entry,
        sa=sa_entry,
        on_time_improvement_pp=improvement,
        winner="sa" if improvement >= 0 else "edd",
    )


def _order_input_to_domain(o: OrderInput) -> Order:
    """Convert API OrderInput to internal Order domain object."""
    return Order(
        order_id=o.order_id,
        material=o.material.value,
        quantity=o.quantity,
        dimensions=o.dimensions,
        due_date=o.due_date,
        priority=o.priority,
        complexity=o.complexity,
    )
