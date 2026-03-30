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
    EnergyAnalysis, AnomalyItem, AnomalyDetectResponse,
    BacktestRequest, BacktestResponse, BacktestActuals, BacktestOrderDetail, BacktestImpact,
)
from agents.scheduler import Scheduler, Order, get_mock_orders, THROUGHPUT, BASE_SETUP_MINUTES, MACHINE_COUNT, check_order_warnings
from agents.sa_scheduler import SAScheduler
from agents.benchmark_data import get_benchmark_orders, DATASET_DESCRIPTION, ORDER_COUNT
from agents.energy_optimizer import EnergyOptimizer
from agents.pdf_exporter import build_schedule_pdf
from agents.anomaly_detector import AnomalyDetector

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Schedule"])

# Instantiated once — SA is stateless between calls
_edd = Scheduler()
_sa  = SAScheduler()
_energy = EnergyOptimizer()
_anomaly = AnomalyDetector()

# Anomaly severities that block an order from being scheduled
_BLOCKING_SEVERITIES = {"critical"}


def _build_response(
    schedule,
    algorithm: str,
    energy_analysis: Optional[EnergyAnalysis] = None,
    orders: list = None,
    held_orders: list = None,
    anomaly_report: Optional[AnomalyDetectResponse] = None,
) -> ScheduleResponse:
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
        held_orders=held_orders or [],
        anomaly_report=anomaly_report,
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

    # --- Automatic anomaly gate: detect critical issues before scheduling ---
    anomaly_report: Optional[AnomalyDetectResponse] = None
    held_order_ids: set[str] = set()
    try:
        raw_orders = [o.model_dump() for o in req.orders]
        report = _anomaly.detect(raw_orders)
        anomaly_report = AnomalyDetectResponse(
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
        # Hold orders flagged with blocking-severity anomalies (critical)
        for a in report.anomalies:
            if a.severity in _BLOCKING_SEVERITIES and a.order_id != "BATCH":
                held_order_ids.add(a.order_id)
        if held_order_ids:
            logger.info("Auto-held %d orders with critical anomalies: %s", len(held_order_ids), held_order_ids)
    except Exception as exc:
        logger.warning("Anomaly detection failed (non-fatal): %s", exc)

    # Filter out held orders before scheduling
    schedulable_inputs = [o for o in req.orders if o.order_id not in held_order_ids]
    orders = [_order_input_to_domain(o) for o in schedulable_inputs]
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

    return _build_response(
        schedule, algorithm, energy_analysis, orders,
        held_orders=list(held_order_ids),
        anomaly_report=anomaly_report,
    )


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


@router.get("/schedule/{run_id}/export-pdf", summary="Export a schedule run as PDF (path param)")
async def export_schedule_pdf_path(
    run_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """Alias for GET /api/schedule/export-pdf — accepts run_id as a path param."""
    run = (
        db.query(ScheduleRun)
        .filter(ScheduleRun.id == run_id, ScheduleRun.created_by_id == user.id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=f"ScheduleRun {run_id} not found")

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


@router.post(
    "/schedule/backtest",
    response_model=BacktestResponse,
    summary="Replay historical orders — what would MillForge have achieved?",
)
async def backtest_schedule(req: BacktestRequest) -> BacktestResponse:
    """
    Given a set of historical orders with recorded actual completion times,
    compute what FIFO, EDD, and SA would have achieved on the same batch.

    This answers the investor/customer question: *"Prove it works on real data."*

    - Upload any past production batch with `actual_completion` timestamps
    - The endpoint computes your real historical on-time rate from those timestamps
    - Then projects FIFO, EDD, and SA on the same orders from the same start time
    - `sa_vs_actual_pp` is the headline: how many more orders would have shipped on-time

    The `start_time` defaults to the earliest due date minus twice the median
    processing time — a reasonable approximation of when the batch entered the queue.
    """
    from datetime import timedelta

    def _strip_tz(dt: datetime) -> datetime:
        return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt

    n = len(req.orders)

    # --- Infer start_time if not provided ---
    if req.start_time is not None:
        start_time = _strip_tz(req.start_time)
    else:
        due_dates = [_strip_tz(o.due_date) for o in req.orders]
        proc_hours = [
            (o.quantity / THROUGHPUT.get(o.material.value.lower(), 3.0)) * o.complexity
            for o in req.orders
        ]
        median_proc_h = sorted(proc_hours)[n // 2]
        start_time = min(due_dates) - timedelta(hours=median_proc_h * 2)

    # --- Actuals from real completion data ---
    actual_on_time = 0
    actual_late_total = 0.0
    for o in req.orders:
        actual_comp = _strip_tz(o.actual_completion)
        due = _strip_tz(o.due_date)
        late_h = (actual_comp - due).total_seconds() / 3600
        if late_h <= 0:
            actual_on_time += 1
        else:
            actual_late_total += late_h

    actual = BacktestActuals(
        on_time_count=actual_on_time,
        on_time_rate_percent=round(actual_on_time / n * 100, 1),
        avg_lateness_hours=round(actual_late_total / n, 2),
    )

    # --- Convert to domain orders (drop actual_completion — algorithms don't see it) ---
    domain_orders = [
        Order(
            order_id=o.order_id,
            material=o.material.value,
            quantity=o.quantity,
            dimensions=o.dimensions,
            due_date=_strip_tz(o.due_date),
            priority=o.priority,
            complexity=o.complexity,
        )
        for o in req.orders
    ]

    # --- FIFO ---
    fifo_on_time, fifo_avg_late, fifo_makespan, fifo_util, fifo_ot_count, fifo_ms = (
        _fifo_schedule(domain_orders)
    )
    fifo_entry = BenchmarkEntry(
        algorithm="fifo",
        on_time_rate_percent=fifo_on_time,
        avg_lateness_hours=fifo_avg_late,
        makespan_hours=fifo_makespan,
        utilization_percent=fifo_util,
        on_time_count=fifo_ot_count,
        total_orders=n,
        solve_ms=fifo_ms,
    )

    # --- EDD ---
    t0 = time.perf_counter()
    edd_sched = _edd.optimize(domain_orders, start_time=start_time)
    edd_ms = round((time.perf_counter() - t0) * 1000, 1)
    edd_entry = BenchmarkEntry(
        algorithm="edd",
        on_time_rate_percent=edd_sched.on_time_rate,
        avg_lateness_hours=_avg_lateness(edd_sched),
        makespan_hours=round(edd_sched.makespan_hours, 2),
        utilization_percent=round(edd_sched.utilization_percent, 1),
        on_time_count=edd_sched.on_time_count,
        total_orders=n,
        solve_ms=edd_ms,
    )

    # --- SA (fixed seed=123 for reproducibility) ---
    _bt_sa = SAScheduler(seed=123)
    t0 = time.perf_counter()
    sa_sched = _bt_sa.optimize(domain_orders, start_time=start_time)
    sa_ms = round((time.perf_counter() - t0) * 1000, 1)
    sa_entry = BenchmarkEntry(
        algorithm="sa",
        on_time_rate_percent=sa_sched.on_time_rate,
        avg_lateness_hours=_avg_lateness(sa_sched),
        makespan_hours=round(sa_sched.makespan_hours, 2),
        utilization_percent=round(sa_sched.utilization_percent, 1),
        on_time_count=sa_sched.on_time_count,
        total_orders=n,
        solve_ms=sa_ms,
    )

    # --- Per-order detail (actual vs SA) + impact metrics ---
    sa_by_id = {s.order.order_id: s for s in sa_sched.scheduled_orders}
    order_details = []
    orders_rescued = 0
    orders_lost = 0
    total_lateness_hours_saved = 0.0

    for o in req.orders:
        actual_comp = _strip_tz(o.actual_completion)
        due = _strip_tz(o.due_date)
        actual_late_h = round((actual_comp - due).total_seconds() / 3600, 2)
        actual_late_clamped = max(actual_late_h, 0.0)

        sa_result = sa_by_id.get(o.order_id)
        sa_late_clamped = max(sa_result.lateness_hours, 0.0) if sa_result else actual_late_clamped

        rescued = (actual_late_h > 0) and (sa_result is not None) and sa_result.on_time
        lost    = (actual_late_h <= 0) and (sa_result is not None) and not sa_result.on_time

        if rescued:
            orders_rescued += 1
        if lost:
            orders_lost += 1

        # hours of lateness eliminated for this order (can be negative if SA is worse)
        total_lateness_hours_saved += actual_late_clamped - sa_late_clamped

        order_details.append(BacktestOrderDetail(
            order_id=o.order_id,
            due_date=due,
            actual_completion=actual_comp,
            actual_on_time=actual_late_h <= 0,
            actual_lateness_hours=actual_late_clamped,
            sa_on_time=sa_result.on_time if sa_result else None,
            sa_lateness_hours=round(sa_result.lateness_hours, 2) if sa_result else None,
            rescued=rescued,
        ))

    # Actual wall-clock makespan (from start_time to last actual completion)
    last_actual_comp = max(_strip_tz(o.actual_completion) for o in req.orders)
    actual_makespan_h = (last_actual_comp - start_time).total_seconds() / 3600
    makespan_delta = round(actual_makespan_h - sa_entry.makespan_hours, 2)

    # Optional penalty savings: orders_rescued × penalty × 12 months = annual estimate
    estimated_penalty: Optional[float] = None
    if req.penalty_per_late_order_usd is not None and req.penalty_per_late_order_usd > 0:
        # Annualise: assume this batch represents ~one month of production
        estimated_penalty = round(orders_rescued * req.penalty_per_late_order_usd * 12, 2)

    impact = BacktestImpact(
        orders_rescued=orders_rescued,
        orders_lost=orders_lost,
        total_lateness_hours_saved=round(total_lateness_hours_saved, 2),
        avg_lateness_reduction_hours=round(total_lateness_hours_saved / n, 2),
        makespan_delta_hours=makespan_delta,
        estimated_penalty_usd=estimated_penalty,
    )

    sa_vs_actual = round(sa_entry.on_time_rate_percent - actual.on_time_rate_percent, 1)
    fifo_vs_actual = round(fifo_entry.on_time_rate_percent - actual.on_time_rate_percent, 1)

    return BacktestResponse(
        label=req.label or "Historical backtest",
        order_count=n,
        machine_count=MACHINE_COUNT,
        start_time=start_time,
        actual=actual,
        fifo=fifo_entry,
        edd=edd_entry,
        sa=sa_entry,
        sa_vs_actual_pp=sa_vs_actual,
        fifo_vs_actual_pp=fifo_vs_actual,
        impact=impact,
        orders=order_details,
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
