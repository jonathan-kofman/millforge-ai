"""
/api/orders CRUD endpoints – persistent order management.

All endpoints require authentication.
"""

import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import User, OrderRecord, ScheduleRun
from auth.dependencies import get_current_user
from agents.scheduler import Scheduler, Order
from agents.sa_scheduler import SAScheduler
from models.schemas import (
    OrderCreateRequest, OrderResponse, OrderUpdateRequest,
    OrderListResponse, OrderScheduleResponse, ScheduleSummary, ScheduledOrderOutput,
    ScheduleHistoryItem, ScheduleHistoryResponse,
)

# Instantiated once at module level — stateless between calls
_edd = Scheduler()
_sa = SAScheduler()

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/orders", tags=["Orders"])


def _record_to_domain(rec: OrderRecord) -> Order:
    """Convert an OrderRecord ORM object to a scheduler domain Order."""
    return Order(
        order_id=rec.order_id,
        material=rec.material,
        quantity=rec.quantity,
        dimensions=rec.dimensions,
        due_date=rec.due_date,
        priority=rec.priority,
        complexity=rec.complexity,
    )


def _to_response(rec: OrderRecord) -> OrderResponse:
    return OrderResponse(
        id=rec.id,
        order_id=rec.order_id,
        material=rec.material,
        dimensions=rec.dimensions,
        quantity=rec.quantity,
        priority=rec.priority,
        complexity=rec.complexity,
        due_date=rec.due_date,
        status=rec.status,
        notes=rec.notes,
        created_by_id=rec.created_by_id,
        created_at=rec.created_at,
        updated_at=rec.updated_at,
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order(
    req: OrderCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderResponse:
    """Create a new order. Generates a unique order_id automatically."""
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    due_date = req.due_date or datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=14)

    rec = OrderRecord(
        order_id=order_id,
        material=req.material.value,
        dimensions=req.dimensions,
        quantity=req.quantity,
        priority=req.priority,
        complexity=req.complexity,
        due_date=due_date,
        notes=req.notes,
        created_by_id=user.id,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    logger.info(f"Order created: {order_id} by user={user.email}")
    return _to_response(rec)


@router.get("", response_model=OrderListResponse)
async def list_orders(
    status_filter: Optional[str] = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderListResponse:
    """List all orders belonging to the authenticated user."""
    q = db.query(OrderRecord).filter(OrderRecord.created_by_id == user.id)
    if status_filter:
        q = q.filter(OrderRecord.status == status_filter)
    total = q.count()
    records = q.order_by(OrderRecord.created_at.desc()).offset(offset).limit(limit).all()
    return OrderListResponse(
        total=total,
        orders=[_to_response(r) for r in records],
    )


@router.get("/schedule-history", response_model=ScheduleHistoryResponse, summary="List past schedule runs")
async def list_schedule_history(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ScheduleHistoryResponse:
    """Return the authenticated user's past ScheduleRun records, newest first."""
    q = db.query(ScheduleRun).filter(ScheduleRun.created_by_id == user.id)
    total = q.count()
    runs = q.order_by(ScheduleRun.created_at.desc()).offset(offset).limit(limit).all()
    items = [
        ScheduleHistoryItem(
            id=r.id,
            algorithm=r.algorithm,
            order_ids=r.order_ids,
            summary=r.summary,
            on_time_rate=r.on_time_rate,
            makespan_hours=r.makespan_hours,
            created_at=r.created_at,
        )
        for r in runs
    ]
    return ScheduleHistoryResponse(total=total, runs=items)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderResponse:
    """Fetch a single order by its string order_id (e.g. ORD-XXXX)."""
    rec = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == order_id, OrderRecord.created_by_id == user.id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    return _to_response(rec)


@router.patch("/{order_id}", response_model=OrderResponse)
async def update_order(
    order_id: str,
    req: OrderUpdateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderResponse:
    """Partially update an order's fields (priority, due_date, status, notes)."""
    rec = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == order_id, OrderRecord.created_by_id == user.id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    update_data = req.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(rec, field, value)

    db.commit()
    db.refresh(rec)
    logger.info(f"Order updated: {order_id}")
    return _to_response(rec)


@router.delete("/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """Delete an order. Only the owner can delete their own orders."""
    rec = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == order_id, OrderRecord.created_by_id == user.id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
    db.delete(rec)
    db.commit()
    logger.info(f"Order deleted: {order_id}")


@router.post("/schedule", response_model=OrderScheduleResponse, summary="Schedule all pending orders")
async def schedule_pending_orders(
    algorithm: str = Query("sa", enum=["edd", "sa"], description="Scheduling algorithm"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OrderScheduleResponse:
    """
    Fetch all pending orders for the authenticated user, run the production
    scheduler, persist the ScheduleRun result, and mark orders as 'scheduled'.

    - **edd**: Greedy Earliest Due Date (fast)
    - **sa**: Simulated Annealing — minimizes weighted tardiness (default)
    """
    records = (
        db.query(OrderRecord)
        .filter(OrderRecord.created_by_id == user.id, OrderRecord.status == "pending")
        .all()
    )
    if not records:
        raise HTTPException(status_code=400, detail="No pending orders to schedule")

    orders = [_record_to_domain(r) for r in records]
    engine = _sa if algorithm == "sa" else _edd
    start_time = datetime.now(timezone.utc).replace(tzinfo=None)

    try:
        schedule = engine.optimize(orders, start_time=start_time)
    except Exception as e:
        logger.error(f"Scheduler error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    summary_data = {
        "total_orders": schedule.total_orders,
        "on_time_count": schedule.on_time_count,
        "on_time_rate_percent": round(schedule.on_time_rate, 2),
        "makespan_hours": round(schedule.makespan_hours, 2),
        "utilization_percent": round(schedule.utilization_percent, 1),
    }

    run = ScheduleRun(
        algorithm=algorithm,
        order_ids_json=json.dumps([r.order_id for r in records]),
        summary_json=json.dumps(summary_data),
        on_time_rate=schedule.on_time_rate,
        makespan_hours=schedule.makespan_hours,
        created_by_id=user.id,
    )
    db.add(run)

    for rec in records:
        rec.status = "scheduled"

    db.commit()
    db.refresh(run)
    logger.info(
        f"ScheduleRun id={run.id} algorithm={algorithm} orders={len(records)} "
        f"on_time_rate={schedule.on_time_rate:.1f}% user={user.email}"
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
        algorithm=algorithm,
        generated_at=schedule.generated_at,
        summary=ScheduleSummary(**summary_data),
        schedule=outputs,
    )
