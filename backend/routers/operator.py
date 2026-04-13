"""
Operator Tablet API — shop floor tablet endpoints for operators.

PIN-based login (not JWT cookies) because tablets are shared devices.
Every state transition is logged to shop_floor_events for the data moat.

Management (dashboard-facing, JWT auth):
  POST /api/operator/operators              — create operator
  GET  /api/operator/operators              — list operators for current user
  POST /api/operator/work-centers          — create work center
  GET  /api/operator/work-centers          — list work centers for current user

Tablet (PIN-based, no JWT):
  POST /api/operator/login
  GET  /api/operator/{operator_id}/queue
  POST /api/operator/operations/{operation_id}/start-setup
  POST /api/operator/operations/{operation_id}/setup-complete
  POST /api/operator/operations/{operation_id}/complete
  POST /api/operator/operations/{operation_id}/pause
  POST /api/operator/operations/{operation_id}/flag
  GET  /api/operator/work-centers/{work_center_id}/status
"""

import json
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Body, Depends, HTTPException, Path, status
from sqlalchemy.orm import Session

from database import get_db
from db_models import (
    Operator, Operation, ShopFloorEvent, WorkCenter,
    NonConformanceReport, User,
)
from auth.jwt_utils import verify_password, hash_password
from auth.dependencies import get_current_user
from models.schemas import (
    OperatorLoginResponse, OperatorTabletLoginRequest,
    OperatorCreate, OperatorResponse, OperationResponse,
    OperationCompleteRequest, OperationPauseRequest, OperatorFlagRequest,
    NonConformanceReportResponse, WorkCenterStatusResponse,
    WorkCenterCreate, WorkCenterResponse, ActiveOperationSummary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/operator", tags=["Operator Tablet"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _log_event(
    db: Session,
    *,
    event_type: str,
    operator: Operator,
    operation: Operation | None = None,
    work_center_id: int | None = None,
    payload: dict,
) -> None:
    """Append a shop floor event — never raises, logs on failure."""
    try:
        evt = ShopFloorEvent(
            user_id=operator.user_id,
            operator_id=operator.id,
            operation_id=operation.id if operation else None,
            work_center_id=work_center_id or (operation.work_center_id if operation else None),
            event_type=event_type,
            payload_json=json.dumps(payload),
        )
        db.add(evt)
        # Caller commits — we just add to the session
    except Exception as exc:
        logger.warning("Event log failed (%s): %s", event_type, exc)


def _get_operator_or_404(db: Session, operator_id: int) -> Operator:
    op = db.get(Operator, operator_id)
    if not op or not op.is_active:
        raise HTTPException(status_code=404, detail="Operator not found or inactive")
    return op


def _get_operation_or_404(db: Session, operation_id: int) -> Operation:
    op = db.get(Operation, operation_id)
    if not op:
        raise HTTPException(status_code=404, detail="Operation not found")
    return op


def _check_qualified(operator: Operator, operation: Operation) -> None:
    """Raise 403 if operator isn't qualified for the operation's work center category."""
    quals = operator.qualifications  # list of category strings
    if quals and operation.work_center_category not in quals:
        raise HTTPException(
            status_code=403,
            detail=(
                f"Operator {operator.name!r} is not qualified for "
                f"work center category {operation.work_center_category!r}. "
                f"Qualified: {quals}"
            ),
        )


def _work_center_response(wc: WorkCenter) -> WorkCenterResponse:
    return WorkCenterResponse(
        id=wc.id,
        user_id=wc.user_id,
        name=wc.name,
        category=wc.category,
        status=wc.status,
        hourly_rate=wc.hourly_rate,
        setup_time_default_min=wc.setup_time_default_min,
        capabilities=wc.capabilities,
        notes=wc.notes,
        created_at=wc.created_at,
    )


# ---------------------------------------------------------------------------
# POST /api/operator/login
# ---------------------------------------------------------------------------

@router.post("/login", response_model=OperatorLoginResponse)
def operator_login(req: OperatorTabletLoginRequest, db: Session = Depends(get_db)):
    """
    Tablet PIN login. Scoped to a shop (user_id) so PIN collisions across
    different shops don't matter.

    Returns the operator record + their qualified work centers.
    """
    operators = (
        db.query(Operator)
        .filter(Operator.user_id == req.user_id, Operator.is_active == True)  # noqa: E712
        .all()
    )
    if not operators:
        raise HTTPException(status_code=401, detail="Invalid PIN")

    matched: Operator | None = None
    for candidate in operators:
        if verify_password(req.pin_code, candidate.pin_code_hash):
            matched = candidate
            break

    if matched is None:
        raise HTTPException(status_code=401, detail="Invalid PIN")

    # Fetch qualified work centers (categories stored as strings in qualifications_json)
    quals = matched.qualifications  # list[str] of categories
    if quals:
        wcs = (
            db.query(WorkCenter)
            .filter(
                WorkCenter.user_id == req.user_id,
                WorkCenter.category.in_(quals),
            )
            .all()
        )
    else:
        # No restrictions — return all active work centers for the shop
        wcs = (
            db.query(WorkCenter)
            .filter(WorkCenter.user_id == req.user_id)
            .all()
        )

    _log_event(
        db,
        event_type="operator_login",
        operator=matched,
        payload={"name": matched.name, "qualified_categories": quals},
    )
    db.commit()

    return OperatorLoginResponse(
        operator_id=matched.id,
        name=matched.name,
        initials=matched.initials,
        qualified_work_centers=[_work_center_response(wc) for wc in wcs],
    )


# ---------------------------------------------------------------------------
# GET /api/operator/{operator_id}/queue
# ---------------------------------------------------------------------------

@router.get("/{operator_id}/queue", response_model=List[OperationResponse])
def get_operator_queue(
    operator_id: int = Path(...),
    db: Session = Depends(get_db),
):
    """
    Operations available to this operator — either directly assigned to them
    or in a work center they're qualified for, with actionable statuses.
    """
    operator = _get_operator_or_404(db, operator_id)
    quals = operator.qualifications

    query = db.query(Operation).filter(
        Operation.user_id == operator.user_id,
        Operation.status.in_(["pending", "queued", "in_progress", "paused"]),
    )

    if quals:
        # Operations either assigned to this operator OR in a qualified category
        from sqlalchemy import or_
        query = query.filter(
            or_(
                Operation.operator_id == operator_id,
                Operation.work_center_category.in_(quals),
            )
        )
    else:
        # No category restriction — return everything for the shop
        pass

    ops = query.order_by(Operation.sequence_number, Operation.created_at).all()
    return [OperationResponse.model_validate(o) for o in ops]


# ---------------------------------------------------------------------------
# POST /api/operator/operations/{operation_id}/start-setup
# ---------------------------------------------------------------------------

@router.post("/operations/{operation_id}/start-setup", response_model=OperationResponse)
def start_setup(
    operation_id: int = Path(...),
    operator_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    Begin setup for an operation. Sets status → in_progress, records
    setup_started_at, assigns operator, logs op_started event.
    """
    operator = _get_operator_or_404(db, operator_id)
    operation = _get_operation_or_404(db, operation_id)
    _check_qualified(operator, operation)

    if operation.status not in ("pending", "queued", "paused"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot start setup on operation with status {operation.status!r}",
        )

    operation.status = "in_progress"
    operation.operator_id = operator_id
    if not operation.setup_started_at:
        operation.setup_started_at = _now()

    _log_event(
        db,
        event_type="op_started",
        operator=operator,
        operation=operation,
        payload={
            "operation_name": operation.operation_name,
            "work_center_category": operation.work_center_category,
            "order_ref": operation.order_ref,
        },
    )
    db.commit()
    db.refresh(operation)
    return OperationResponse.model_validate(operation)


# ---------------------------------------------------------------------------
# POST /api/operator/operations/{operation_id}/setup-complete
# ---------------------------------------------------------------------------

@router.post("/operations/{operation_id}/setup-complete", response_model=OperationResponse)
def setup_complete(
    operation_id: int = Path(...),
    operator_id: int = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """
    Mark setup done and begin the run. Records run_started_at and
    computes actual_setup_min from setup_started_at.
    """
    operator = _get_operator_or_404(db, operator_id)
    operation = _get_operation_or_404(db, operation_id)
    _check_qualified(operator, operation)

    if operation.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail=f"Operation must be in_progress to complete setup (currently {operation.status!r})",
        )
    if operation.run_started_at is not None:
        raise HTTPException(status_code=409, detail="Setup already completed for this operation")

    now = _now()
    operation.run_started_at = now
    if operation.setup_started_at:
        delta = (now - operation.setup_started_at).total_seconds() / 60.0
        operation.actual_setup_min = round(delta, 2)

    _log_event(
        db,
        event_type="setup_complete",
        operator=operator,
        operation=operation,
        payload={
            "actual_setup_min": operation.actual_setup_min,
            "estimated_setup_min": operation.estimated_setup_min,
        },
    )
    db.commit()
    db.refresh(operation)
    return OperationResponse.model_validate(operation)


# ---------------------------------------------------------------------------
# POST /api/operator/operations/{operation_id}/complete
# ---------------------------------------------------------------------------

@router.post("/operations/{operation_id}/complete", response_model=OperationResponse)
def complete_operation(
    operation_id: int = Path(...),
    operator_id: int = Body(..., embed=True),
    quantity_complete: int = Body(...),
    quantity_scrapped: int = Body(default=0),
    scrap_reason: str | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """
    Mark operation complete. Captures qty/scrap, computes actual_run_min,
    logs op_completed event.
    """
    operator = _get_operator_or_404(db, operator_id)
    operation = _get_operation_or_404(db, operation_id)
    _check_qualified(operator, operation)

    if operation.status not in ("in_progress", "paused"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot complete operation with status {operation.status!r}",
        )

    now = _now()
    operation.status = "complete"
    operation.completed_at = now
    operation.quantity_complete = quantity_complete
    operation.quantity_scrapped = quantity_scrapped
    if scrap_reason:
        operation.scrap_reason = scrap_reason

    if operation.run_started_at:
        delta = (now - operation.run_started_at).total_seconds() / 60.0
        operation.actual_run_min = round(delta, 2)

    _log_event(
        db,
        event_type="op_completed",
        operator=operator,
        operation=operation,
        payload={
            "quantity_complete": quantity_complete,
            "quantity_scrapped": quantity_scrapped,
            "scrap_reason": scrap_reason,
            "actual_run_min": operation.actual_run_min,
            "estimated_run_min": operation.estimated_run_min,
        },
    )
    db.commit()
    db.refresh(operation)
    return OperationResponse.model_validate(operation)


# ---------------------------------------------------------------------------
# POST /api/operator/operations/{operation_id}/pause
# ---------------------------------------------------------------------------

@router.post("/operations/{operation_id}/pause", response_model=OperationResponse)
def pause_operation(
    operation_id: int = Path(...),
    operator_id: int = Body(..., embed=True),
    reason: str | None = Body(default=None),
    db: Session = Depends(get_db),
):
    """Pause an in-progress operation. Logs op_paused with reason."""
    operator = _get_operator_or_404(db, operator_id)
    operation = _get_operation_or_404(db, operation_id)
    _check_qualified(operator, operation)

    if operation.status != "in_progress":
        raise HTTPException(
            status_code=409,
            detail=f"Can only pause an in_progress operation (currently {operation.status!r})",
        )

    operation.status = "paused"

    _log_event(
        db,
        event_type="op_paused",
        operator=operator,
        operation=operation,
        payload={"reason": reason, "operation_name": operation.operation_name},
    )
    db.commit()
    db.refresh(operation)
    return OperationResponse.model_validate(operation)


# ---------------------------------------------------------------------------
# POST /api/operator/operations/{operation_id}/flag
# ---------------------------------------------------------------------------

@router.post(
    "/operations/{operation_id}/flag",
    response_model=NonConformanceReportResponse,
    status_code=status.HTTP_201_CREATED,
)
def flag_operation(
    operation_id: int = Path(...),
    req: OperatorFlagRequest = Body(...),
    db: Session = Depends(get_db),
):
    """
    Raise a quality flag on an operation. Creates an NCR, sets the operation
    to on_hold, and logs a quality_hold event. Removes the part from the
    active queue until the NCR is resolved.
    """
    operator = _get_operator_or_404(db, req.operator_id)
    operation = _get_operation_or_404(db, operation_id)
    _check_qualified(operator, operation)

    if operation.status in ("complete", "cancelled"):
        raise HTTPException(
            status_code=409,
            detail=f"Cannot flag a {operation.status!r} operation",
        )

    # Create NCR
    ncr = NonConformanceReport(
        user_id=operator.user_id,
        operation_id=operation.id,
        order_ref=operation.order_ref,
        severity=req.severity,
        description=req.description,
        status="open",
    )
    db.add(ncr)

    # Hold the operation
    operation.status = "on_hold"

    _log_event(
        db,
        event_type="quality_hold",
        operator=operator,
        operation=operation,
        payload={
            "severity": req.severity,
            "description": req.description,
            "order_ref": operation.order_ref,
        },
    )
    db.commit()
    db.refresh(ncr)
    return NonConformanceReportResponse.model_validate(ncr)


# ---------------------------------------------------------------------------
# GET /api/operator/work-centers/{work_center_id}/status
# ---------------------------------------------------------------------------

@router.get("/work-centers/{work_center_id}/status", response_model=WorkCenterStatusResponse)
def work_center_status(
    work_center_id: int = Path(...),
    db: Session = Depends(get_db),
):
    """
    Current status of a work center: active operation, queue depth,
    and estimated hours remaining for all queued work.
    """
    wc = db.get(WorkCenter, work_center_id)
    if not wc:
        raise HTTPException(status_code=404, detail="Work center not found")

    active_op = (
        db.query(Operation)
        .filter(
            Operation.work_center_id == work_center_id,
            Operation.status == "in_progress",
        )
        .first()
    )

    queued_ops = (
        db.query(Operation)
        .filter(
            Operation.work_center_id == work_center_id,
            Operation.status.in_(["pending", "queued", "paused"]),
        )
        .all()
    )

    # Estimated hours remaining = sum of estimated_run_min + estimated_setup_min for queue
    # Plus remaining time on the active op (if any)
    total_min = sum(
        (o.estimated_setup_min + o.estimated_run_min) for o in queued_ops
    )
    if active_op:
        # Rough remaining: full estimated_run_min (we don't know how far in they are)
        total_min += active_op.estimated_run_min

    return WorkCenterStatusResponse(
        work_center_id=wc.id,
        name=wc.name,
        category=wc.category,
        status=wc.status,
        active_operation=(
            ActiveOperationSummary.model_validate(active_op) if active_op else None
        ),
        queue_depth=len(queued_ops),
        estimated_hours_remaining=round(total_min / 60.0, 2),
    )


# ===========================================================================
# MANAGEMENT ENDPOINTS — JWT auth, dashboard-facing
# ===========================================================================

# ---------------------------------------------------------------------------
# POST /api/operator/operators — create operator
# ---------------------------------------------------------------------------

@router.post(
    "/operators",
    response_model=OperatorResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Operator Management"],
)
def create_operator(
    req: OperatorCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a shop floor operator. PIN is hashed with Argon2id."""
    import json as _json
    op = Operator(
        user_id=current_user.id,
        name=req.name,
        initials=req.initials[:6],
        pin_code_hash=hash_password(req.pin_code),
        is_active=True,
        qualifications_json=_json.dumps(req.qualifications),
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return OperatorResponse(
        id=op.id,
        name=op.name,
        initials=op.initials,
        is_active=op.is_active,
        qualifications=op.qualifications,
        created_at=op.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/operator/operators — list operators
# ---------------------------------------------------------------------------

@router.get(
    "/operators",
    response_model=List[OperatorResponse],
    tags=["Operator Management"],
)
def list_operators(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all operators belonging to the current user's shop."""
    ops = (
        db.query(Operator)
        .filter(Operator.user_id == current_user.id)
        .order_by(Operator.name)
        .all()
    )
    return [
        OperatorResponse(
            id=o.id,
            name=o.name,
            initials=o.initials,
            is_active=o.is_active,
            qualifications=o.qualifications,
            created_at=o.created_at,
        )
        for o in ops
    ]


# ---------------------------------------------------------------------------
# POST /api/operator/work-centers — create work center
# ---------------------------------------------------------------------------

@router.post(
    "/work-centers",
    response_model=WorkCenterResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Operator Management"],
)
def create_work_center(
    req: WorkCenterCreate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create a work center / machine station for the shop."""
    import json as _json
    wc = WorkCenter(
        user_id=current_user.id,
        name=req.name,
        category=req.category,
        status="available",
        hourly_rate=req.hourly_rate,
        setup_time_default_min=req.setup_time_default_min,
        available_hours_json=_json.dumps(req.available_hours) if req.available_hours else None,
        capabilities_json=_json.dumps(req.capabilities) if req.capabilities else None,
        notes=req.notes,
    )
    db.add(wc)
    db.commit()
    db.refresh(wc)
    return _work_center_response(wc)


# ---------------------------------------------------------------------------
# GET /api/operator/work-centers — list work centers
# ---------------------------------------------------------------------------

@router.get(
    "/work-centers",
    response_model=List[WorkCenterResponse],
    tags=["Operator Management"],
)
def list_work_centers(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all work centers for the current user's shop."""
    wcs = (
        db.query(WorkCenter)
        .filter(WorkCenter.user_id == current_user.id)
        .order_by(WorkCenter.name)
        .all()
    )
    return [_work_center_response(wc) for wc in wcs]
