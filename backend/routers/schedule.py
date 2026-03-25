"""
/api/schedule endpoint – optimize a production schedule from a list of orders.

MillForge is an intelligence layer on top of a job shop's existing constraints.
It does not change machines, staff, or suppliers — it makes the same resources
run at maximum efficiency. The benchmark endpoint exists to quantify that delta:
a shop running FIFO typically sits at 40–60% on-time; MillForge targets 80–95%
on the same order set.
"""

import time
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from db_models import User, ScheduleRun, ShopConfig
from auth.dependencies import get_current_user, get_current_user_optional
from models.schemas import (
    ScheduleRequest, ScheduleResponse, ScheduleSummary,
    ScheduledOrderOutput, OrderInput, BenchmarkResponse, BenchmarkEntry,
    EnergyAnalysis,
)
from agents.scheduler import Scheduler, Order, get_mock_orders, THROUGHPUT, BASE_SETUP_MINUTES, MACHINE_COUNT, check_order_warnings
from agents.sa_scheduler import SAScheduler
from agents.benchmark_data import get_benchmark_orders, DATASET_DESCRIPTION, ORDER_COUNT
from agents.energy_optimizer import EnergyOptimizer
from agents.pdf_exporter import build_schedule_pdf

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Schedule"])

# Instantiated once — SA is stateless between calls
_edd = Scheduler()
_sa  = SAScheduler()
_energy = EnergyOptimizer()


def _build_response(schedule, algorithm: str, energy_analysis: Optional[EnergyAnalysis] = None, orders: list = None) -> ScheduleResponse:
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
    warnings = check_order_warnings(orders) if orders else []
    return ScheduleResponse(
        generated_at=schedule.generated_at,
        summary=summary,
        schedule=outputs,
        algorithm=algorithm,
        validation_failures=getattr(schedule, "validation_failures", []),
        warnings=warnings,
        energy_analysis=energy_analysis,
    )


@router.post("/schedule", response_model=ScheduleResponse, summary="Optimize production schedule within shop constraints")
async def optimize_schedule(
    req: ScheduleRequest,
    algorithm: str = Query("sa", enum=["edd", "sa"], description="edd = greedy EDD, sa = simulated annealing"),
    db: Session = Depends(get_db),
    user: Optional[User] = Depends(get_current_user_optional),
) -> ScheduleResponse:
    """
    Optimize a production schedule for the provided order list using the shop's
    real constraints (machines, throughput, setup times). MillForge does not change
    the constraints — it sequences work to maximise on-time delivery within them.

    - **edd**: Earliest Due Date with greedy machine assignment (fast, O(n log n))
    - **sa**: Simulated Annealing optimizer — minimises weighted tardiness (default, recommended)
    """
    logger.info(f"Schedule request: {len(req.orders)} orders | algorithm={algorithm}")

    orders = [_order_input_to_domain(o) for o in req.orders]
    start_time = req.start_time or datetime.now(timezone.utc).replace(tzinfo=None)

    # Determine machine count: use ShopConfig if authenticated, else default
    machine_count = MACHINE_COUNT
    if user:
        try:
            shop_config = db.query(ShopConfig).filter(ShopConfig.user_id == user.id).first()
            if shop_config and shop_config.machine_count:
                machine_count = shop_config.machine_count
                logger.info(f"Using user's ShopConfig machine_count: {machine_count}")
        except Exception as e:
            logger.warning(f"Failed to lookup user's ShopConfig: {e}")

    # Create or reuse scheduler with the appropriate machine count
    if algorithm == "sa":
        if machine_count != MACHINE_COUNT:
            engine = SAScheduler(machine_count=machine_count)
        else:
            engine = _sa
    else:
        if machine_count != MACHINE_COUNT:
            engine = Scheduler(machine_count=machine_count)
        else:
            engine = _edd

    try:
        schedule = engine.optimize(orders, start_time=start_time)
    except Exception as e:
        logger.error(f"Scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    energy_analysis = None
    try:
        ea = _energy.compute_schedule_energy_analysis(
            schedule.scheduled_orders,
            battery_soc_percent=req.battery_soc_percent,
        )
        energy_analysis = EnergyAnalysis(
            total_energy_kwh=ea["total_energy_kwh"],
            current_schedule_cost_usd=ea["current_schedule_cost_usd"],
            optimal_schedule_cost_usd=ea["optimal_schedule_cost_usd"],
            potential_savings_usd=ea["potential_savings_usd"],
            carbon_footprint_kg_co2=ea["carbon_footprint_kg_co2"],
            carbon_delta_kg_co2=ea["carbon_delta_kg_co2"],
            battery_recommendation=ea.get("battery_recommendation"),
            data_source=ea.get("data_source", "simulated_fallback"),
        )
    except Exception as e:
        logger.warning(f"Energy analysis failed (non-fatal): {e}")

    return _build_response(schedule, algorithm, energy_analysis, orders)


@router.get("/schedule/demo", response_model=ScheduleResponse, summary="Demo schedule on built-in mock order set")
async def demo_schedule(
    algorithm: str = Query("sa", enum=["edd", "sa"]),
) -> ScheduleResponse:
    """Return an optimised schedule built from the built-in mock order dataset.
    Useful for frontend demos and integration tests without needing real order data."""
    mock_orders = get_mock_orders()
    engine = _sa if algorithm == "sa" else _edd
    try:
        schedule = engine.optimize(mock_orders)
    except Exception as e:
        logger.error(f"Demo scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")
    return _build_response(schedule, algorithm, orders=mock_orders)


def _avg_lateness(sched) -> float:
    """Compute mean lateness in hours across all orders (late orders only; on-time = 0)."""
    if not sched.scheduled_orders:
        return 0.0
    total = sum(max(s.lateness_hours, 0.0) for s in sched.scheduled_orders)
    return round(total / len(sched.scheduled_orders), 2)


def _fifo_schedule(orders: list) -> tuple:
    """
    Simulate naive FIFO scheduling: process orders in arrival order with greedy
    machine assignment. Uses the same throughput, setup, and machine constants as
    the real scheduler so the comparison is apples-to-apples.

    Returns (on_time_rate, avg_lateness_hours, makespan_hours, utilization_percent,
    on_time_count, solve_ms).

    This is the baseline a typical job shop runs before MillForge — no optimisation,
    just work the queue in the order jobs arrived.
    """
    from datetime import timedelta

    start = datetime.now(timezone.utc).replace(tzinfo=None)
    machine_free = [start] * MACHINE_COUNT
    setup_hours = BASE_SETUP_MINUTES / 60

    t0 = time.perf_counter()
    on_time_count = 0
    lateness_total = 0.0
    completion_times = []

    for order in orders:  # FIFO: no sort — process in arrival order
        tput = THROUGHPUT.get(order.material.lower(), 3.0)
        # mirrors Order.base_processing_minutes: hours = quantity / throughput * complexity
        proc_h = (order.quantity / tput) * order.complexity

        mi = min(range(MACHINE_COUNT), key=lambda i: machine_free[i])
        proc_start = machine_free[mi] + timedelta(hours=setup_hours)
        completion = proc_start + timedelta(hours=proc_h)
        machine_free[mi] = completion
        completion_times.append(completion)

        late = (completion - order.due_date).total_seconds() / 3600
        if late <= 0:
            on_time_count += 1
        else:
            lateness_total += late

    solve_ms = (time.perf_counter() - t0) * 1000
    n = len(orders)
    on_time_rate = round(on_time_count / n * 100, 1) if n else 0.0
    avg_lateness = round(lateness_total / n, 2) if n else 0.0

    latest = max(completion_times) if completion_times else start
    makespan = round((latest - start).total_seconds() / 3600, 2)

    total_proc_h = sum(
        (o.quantity / THROUGHPUT.get(o.material.lower(), 3.0)) * o.complexity
        for o in orders
    )
    utilization = round(total_proc_h / (MACHINE_COUNT * makespan) * 100, 1) if makespan > 0 else 0.0

    return on_time_rate, avg_lateness, makespan, utilization, on_time_count, round(solve_ms, 1)


@router.get(
    "/schedule/benchmark",
    response_model=BenchmarkResponse,
    summary="FIFO vs EDD vs SA — the MillForge improvement delta",
)
async def benchmark_schedule(
    pressure: float = Query(
        0.5,
        ge=0.0,
        le=1.0,
        description=(
            "Schedule pressure: 0.0 = relaxed (1.5× due-date slack), "
            "0.5 = default, 1.0 = extreme (0.5× due-date slack). "
            "Higher pressure amplifies the FIFO penalty."
        ),
    ),
    rush: bool = Query(
        False,
        description="Inject an extra priority-1 steel rush order with a 4-hour deadline to show real-time impact.",
    ),
) -> BenchmarkResponse:
    """
    Run three scheduling strategies on the synthetic 28-order benchmark dataset
    and return a side-by-side comparison. This is the core MillForge demo:

    | Strategy | Description |
    |----------|-------------|
    | **fifo** | Naive baseline — process jobs in arrival order, no optimisation |
    | **edd**  | MillForge EDD — greedy earliest-due-date with setup-time awareness |
    | **sa**   | MillForge SA — simulated annealing, minimises weighted tardiness |

    The `on_time_improvement_pp` field shows the percentage-point lift SA delivers
    over the FIFO baseline — e.g. a shop at 55% on-time becomes 90%+ with the same
    machines, staff, and suppliers.

    The `pressure` query parameter scales due dates to simulate different shop
    conditions (0.0 = relaxed, 0.5 = realistic, 1.0 = extreme peak demand).

    Set `rush=true` to inject an additional priority-1 steel order with a 4-hour
    deadline — useful for demonstrating how each algorithm handles a surprise urgent job.
    """
    from agents.scheduler import Order as _Order
    from datetime import timedelta
    # Single reference time for both order due dates and optimizer start — ensures
    # fully deterministic results regardless of when the endpoint is called.
    ref = datetime.now(timezone.utc).replace(tzinfo=None)
    orders = get_benchmark_orders(reference_time=ref, pressure=pressure)
    if rush:
        orders = orders + [
            _Order(
                order_id="RUSH-INJECT",
                material="steel",
                quantity=4,
                dimensions="100x50x6mm",
                due_date=ref + timedelta(hours=4),
                priority=1,
                complexity=1.0,
            )
        ]

    # FIFO baseline
    fifo_on_time, fifo_avg_late, fifo_makespan, fifo_util, fifo_ot_count, fifo_ms = (
        _fifo_schedule(orders)
    )

    t0 = time.perf_counter()
    edd_sched = _edd.optimize(orders, start_time=ref)
    edd_ms = round((time.perf_counter() - t0) * 1000, 1)

    # Fixed seed for the benchmark so SA results are deterministic across runs.
    # seed=123 → SA = 96.4 % on-time on the 28-order dataset at p=0.5.
    _bench_sa = SAScheduler(seed=123)
    t0 = time.perf_counter()
    sa_sched = _bench_sa.optimize(orders, start_time=ref)
    sa_ms = round((time.perf_counter() - t0) * 1000, 1)

    def _entry(sched, algo, ms) -> BenchmarkEntry:
        return BenchmarkEntry(
            algorithm=algo,
            on_time_rate_percent=sched.on_time_rate,
            avg_lateness_hours=_avg_lateness(sched),
            makespan_hours=round(sched.makespan_hours, 2),
            utilization_percent=round(sched.utilization_percent, 1),
            on_time_count=sched.on_time_count,
            total_orders=sched.total_orders,
            solve_ms=ms,
        )

    fifo_entry = BenchmarkEntry(
        algorithm="fifo",
        on_time_rate_percent=fifo_on_time,
        avg_lateness_hours=fifo_avg_late,
        makespan_hours=fifo_makespan,
        utilization_percent=fifo_util,
        on_time_count=fifo_ot_count,
        total_orders=len(orders),
        solve_ms=fifo_ms,
    )
    edd_entry = _entry(edd_sched, "edd", edd_ms)
    sa_entry  = _entry(sa_sched,  "sa",  sa_ms)

    improvement = round(sa_entry.on_time_rate_percent - fifo_entry.on_time_rate_percent, 1)

    return BenchmarkResponse(
        fifo=fifo_entry,
        edd=edd_entry,
        sa=sa_entry,
        on_time_improvement_pp=improvement,
        winner="sa" if sa_entry.on_time_rate_percent >= edd_entry.on_time_rate_percent else "edd",
        order_count=ORDER_COUNT,
        machine_count=MACHINE_COUNT,
        dataset_description=DATASET_DESCRIPTION,
        pressure=pressure,
    )


@router.get("/schedule/export-pdf", summary="Export a saved schedule run as a PDF")
async def export_schedule_pdf(
    schedule_id: int = Query(..., description="ScheduleRun ID from a previous /api/orders/schedule call"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """
    Render a saved ScheduleRun as a production-ready PDF.

    Returns a PDF file with:
    - Header (run ID, algorithm, timestamp)
    - KPI summary table (on-time rate, makespan, utilization)
    - Gantt chart with material-coded bars per machine
    - Order details table
    """
    run = (
        db.query(ScheduleRun)
        .filter(ScheduleRun.id == schedule_id, ScheduleRun.created_by_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=f"ScheduleRun {schedule_id} not found")

    pdf_bytes = build_schedule_pdf(
        schedule_run_id=run.id,
        algorithm=run.algorithm,
        summary=run.summary,
        orders=run.scheduled_orders,
        generated_at=run.created_at,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=schedule_{run.id}.pdf"},
    )


def _order_input_to_domain(o: OrderInput) -> Order:
    """Convert API OrderInput to internal Order domain object."""
    # Normalise to naive UTC so the scheduler's naive start_time can compare
    due = o.due_date.replace(tzinfo=None) if o.due_date.tzinfo is not None else o.due_date
    return Order(
        order_id=o.order_id,
        material=o.material.value,
        quantity=o.quantity,
        dimensions=o.dimensions,
        due_date=due,
        priority=o.priority,
        complexity=o.complexity,
    )
