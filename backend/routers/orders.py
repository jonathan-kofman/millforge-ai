"""
/api/orders CRUD endpoints – persistent order management.

All endpoints require authentication.
"""

import json
import uuid
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_db
from db_models import User, OrderRecord, ScheduleRun, InspectionRecord
from auth.dependencies import get_current_user
from agents.scheduler import Scheduler, Order
from agents.sa_scheduler import SAScheduler
from agents.csv_importer import parse_csv, create_preview, consume_preview, CSV_TEMPLATE
from models.schemas import (
    OrderCreateRequest, OrderResponse, OrderUpdateRequest,
    OrderListResponse, OrderScheduleResponse, ScheduleSummary, ScheduledOrderOutput,
    ScheduleHistoryItem, ScheduleHistoryResponse,
    CsvRowPreview, CsvRowError, CsvImportPreviewResponse,
    CsvImportConfirmRequest, CsvImportConfirmResponse,
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
        customer_name=getattr(rec, "customer_name", None),
        po_number=getattr(rec, "po_number", None),
        part_number=getattr(rec, "part_number", None),
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
        customer_name=req.customer_name,
        po_number=req.po_number,
        part_number=req.part_number,
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


@router.get("/import-csv/template", summary="Download CSV template for bulk order import")
async def import_csv_template() -> Response:
    """Return a ready-to-fill CSV template with all supported columns."""
    return Response(
        content=CSV_TEMPLATE,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=millforge_orders_template.csv"},
    )


@router.post(
    "/import-csv",
    response_model=CsvImportPreviewResponse,
    summary="Preview a CSV bulk order upload",
)
async def import_csv_preview(
    file: UploadFile = File(..., description="CSV file with order data"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CsvImportPreviewResponse:
    """
    Parse and validate a CSV file.  Returns a preview with valid rows and any
    error rows.  Use the returned ``preview_token`` with
    ``POST /api/orders/import-csv/confirm`` to commit the valid rows.

    Required CSV columns (or recognised aliases):
    - **material** — steel | aluminum | titanium | copper
    - **quantity** — positive integer
    - **due_date** — YYYY-MM-DD or MM/DD/YYYY

    Optional: order_id, dimensions, priority (1–10), complexity (0.1–5.0)
    """
    content = await file.read()
    try:
        column_mapping, valid_rows, error_rows = parse_csv(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    token = create_preview(column_mapping, valid_rows, error_rows)
    logger.info(
        f"CSV preview: user={user.email} valid={len(valid_rows)} errors={len(error_rows)} token={token}"
    )
    return CsvImportPreviewResponse(
        preview_token=token,
        total_rows=len(valid_rows) + len(error_rows),
        valid_count=len(valid_rows),
        error_count=len(error_rows),
        column_mapping=column_mapping,
        valid_rows=[CsvRowPreview(**r) for r in valid_rows],
        error_rows=[CsvRowError(**r) for r in error_rows],
    )


@router.post(
    "/import-csv/confirm",
    response_model=CsvImportConfirmResponse,
    status_code=status.HTTP_200_OK,
    summary="Commit a previewed CSV import",
)
async def import_csv_confirm(
    req: CsvImportConfirmRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CsvImportConfirmResponse:
    """
    Commit the valid rows from a previous ``POST /api/orders/import-csv`` call.
    The ``preview_token`` is single-use — it is consumed on success.
    Error rows from the preview are skipped automatically.
    """
    preview = consume_preview(req.preview_token)
    if preview is None:
        raise HTTPException(status_code=404, detail="Preview token not found or already used")

    order_ids = []
    for row in preview["valid_rows"]:
        oid = row["order_id"] or f"ORD-{uuid.uuid4().hex[:8].upper()}"
        rec = OrderRecord(
            order_id=oid,
            material=row["material"],
            dimensions=row["dimensions"],
            quantity=row["quantity"],
            priority=row["priority"],
            complexity=row["complexity"],
            due_date=row["due_date"],
            created_by_id=user.id,
        )
        db.add(rec)
        order_ids.append(oid)

    db.commit()
    logger.info(
        f"CSV import confirmed: user={user.email} imported={len(order_ids)} "
        f"skipped={len(preview['error_rows'])}"
    )
    return CsvImportConfirmResponse(
        imported_count=len(order_ids),
        order_ids=order_ids,
        skipped_count=len(preview["error_rows"]),
    )


@router.get(
    "/{order_id}/status",
    summary="Public order status check (no auth required)",
    tags=["Order Status"],
)
async def get_order_status(
    order_id: str,
    db: Session = Depends(get_db),
) -> dict:
    """
    Public endpoint — no authentication required.

    Returns a minimal status view of an order suitable for customer-facing
    portals or tracking integrations. Exposes only: status, material,
    quantity, due_date, scheduled completion time, and on-time flag.

    Internal fields (machine_id, setup_minutes, priority, notes) are never
    returned here.
    """
    rec = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == order_id)
        .first()
    )
    if not rec:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found")

    # Find the most recent ScheduleRun that includes this order
    scheduled_completion: Optional[str] = None
    on_time: Optional[bool] = None
    schedule_run_id: Optional[int] = None

    runs = (
        db.query(ScheduleRun)
        .order_by(ScheduleRun.created_at.desc())
        .limit(20)
        .all()
    )
    for run in runs:
        if order_id in run.order_ids:
            for slot in run.scheduled_orders:
                if slot.get("order_id") == order_id:
                    scheduled_completion = slot.get("completion_time")
                    on_time = slot.get("on_time")
                    schedule_run_id = run.id
                    break
            if scheduled_completion is not None:
                break

    # Check most recent inspection
    inspection = (
        db.query(InspectionRecord)
        .filter(InspectionRecord.order_id_str == order_id)
        .order_by(InspectionRecord.created_at.desc())
        .first()
    )

    return {
        "order_id": rec.order_id,
        "status": rec.status,
        "material": rec.material,
        "quantity": rec.quantity,
        "due_date": rec.due_date.isoformat(),
        "scheduled_completion": scheduled_completion,
        "on_time": on_time,
        "schedule_run_id": schedule_run_id,
        "quality_passed": inspection.passed if inspection else None,
        "quality_checked_at": inspection.created_at.isoformat() if inspection else None,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }


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
        algorithm=algorithm,
        order_ids_json=json.dumps([r.order_id for r in records]),
        summary_json=json.dumps(summary_data),
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
