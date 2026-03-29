"""
/api/machines — CNC machine registry and machine-aware scheduling support.

Machine types are matched against Job.required_machine_type to surface
conflicts before scheduling. No human checks machine availability.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import Machine, Job
from auth.dependencies import get_current_user
from db_models import User
from models.schemas import MachineCreate, MachineResponse, MachineConflictResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/machines", tags=["Machines"])

# Separate router so the /check-conflict route can be registered before
# ws_machines_router's GET /api/machines/{machine_id} path parameter.
conflict_router = APIRouter(prefix="/api/machines", tags=["Machines"])


def _to_response(m: Machine) -> MachineResponse:
    return MachineResponse(
        id=m.id,
        name=m.name,
        machine_type=m.machine_type,
        is_available=m.is_available,
        notes=m.notes,
        created_at=m.created_at,
    )


# ---------------------------------------------------------------------------
# GET /api/machines
# ---------------------------------------------------------------------------

@router.get("", response_model=list[MachineResponse])
def list_machines(
    machine_type: Optional[str] = Query(None),
    available_only: bool = Query(False),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Machine)
    if machine_type:
        q = q.filter(Machine.machine_type == machine_type)
    if available_only:
        q = q.filter(Machine.is_available == True)  # noqa: E712
    machines = q.order_by(Machine.name).all()
    return [_to_response(m) for m in machines]


# ---------------------------------------------------------------------------
# POST /api/machines
# ---------------------------------------------------------------------------

@router.post("", response_model=MachineResponse, status_code=201)
def create_machine(
    payload: MachineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = Machine(
        name=payload.name,
        machine_type=payload.machine_type,
        is_available=payload.is_available,
        notes=payload.notes,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    logger.info("Machine created: id=%d name=%r type=%s", m.id, m.name, m.machine_type)
    return _to_response(m)


# ---------------------------------------------------------------------------
# GET /api/machines/check-conflict?required_machine_type=VMC
# NOTE: must be defined BEFORE /{machine_id} routes or FastAPI will try to
# coerce "check-conflict" as an integer and return 422.
# ---------------------------------------------------------------------------

@conflict_router.get("/check-conflict", response_model=MachineConflictResponse)
def check_conflict(
    required_machine_type: str = Query(..., description="Machine type required by the job"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Check whether at least one available machine matches the required type.
    Returns conflict=True with a message if no match exists.
    """
    available = (
        db.query(Machine)
        .filter(Machine.machine_type == required_machine_type, Machine.is_available == True)  # noqa: E712
        .all()
    )
    if not available:
        all_of_type = db.query(Machine).filter(Machine.machine_type == required_machine_type).all()
        if all_of_type:
            msg = (
                f"All {required_machine_type} machines are currently unavailable. "
                "Mark one as available or reassign the job."
            )
        else:
            msg = (
                f"No {required_machine_type} machines registered. "
                "Add one via POST /api/machines before scheduling this job."
            )
        return MachineConflictResponse(
            conflict=True,
            message=msg,
            required_machine_type=required_machine_type,
            available_machines=[],
        )

    return MachineConflictResponse(
        conflict=False,
        message=f"{len(available)} {required_machine_type} machine(s) available.",
        required_machine_type=required_machine_type,
        available_machines=[_to_response(m) for m in available],
    )


# ---------------------------------------------------------------------------
# PATCH /api/machines/{machine_id}
# ---------------------------------------------------------------------------

@router.patch("/{machine_id}", response_model=MachineResponse)
def update_machine(
    machine_id: int,
    payload: MachineCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = db.query(Machine).filter(Machine.id == machine_id).first()
    if not m:
        raise HTTPException(404, "Machine not found")
    m.name = payload.name
    m.machine_type = payload.machine_type
    m.is_available = payload.is_available
    if payload.notes is not None:
        m.notes = payload.notes
    db.commit()
    db.refresh(m)
    return _to_response(m)


# ---------------------------------------------------------------------------
# DELETE /api/machines/{machine_id}
# ---------------------------------------------------------------------------

@router.delete("/{machine_id}", status_code=204)
def delete_machine(
    machine_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = db.query(Machine).filter(Machine.id == machine_id).first()
    if not m:
        raise HTTPException(404, "Machine not found")
    db.delete(m)
    db.commit()
