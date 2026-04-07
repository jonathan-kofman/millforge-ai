"""
Exception queue router — /api/exceptions

GET  /api/exceptions         — list all open exceptions across all sources
GET  /api/exceptions/summary — count by source and severity
PATCH /api/exceptions/{id}/resolve   — mark an exception resolved
PATCH /api/exceptions/{id}/unresolve — reopen a resolved exception
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agents.exception_queue import ExceptionQueueAgent, mark_resolved, mark_unresolved
from database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/exceptions", tags=["Exceptions"])

# ---------------------------------------------------------------------------
# Singleton agent — injected with InventoryAgent at first request
# ---------------------------------------------------------------------------
_agent: Optional[ExceptionQueueAgent] = None


def _get_agent() -> ExceptionQueueAgent:
    global _agent
    if _agent is None:
        try:
            from routers.inventory import _inventory
            _agent = ExceptionQueueAgent(inventory_agent=_inventory)
        except Exception:
            _agent = ExceptionQueueAgent(inventory_agent=None)
    return _agent


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get(
    "",
    summary="List open exceptions",
    response_description="Priority-sorted list of actionable exceptions.",
)
async def list_exceptions(
    db: Session = Depends(get_db),
    include_resolved: bool = Query(False, description="Include already-resolved exceptions"),
    source: Optional[str] = Query(
        None,
        description="Filter by source: machine_fault | held_order | quality_failure | low_inventory",
    ),
    severity: Optional[str] = Query(
        None,
        description="Filter by severity: critical | warning | info",
    ),
    limit: int = Query(200, ge=1, le=1000),
):
    """
    Returns every open exception across all sources, sorted by severity then recency.

    **Sources:**
    - `machine_fault` — CNC machine entered FAULT state; operator must inspect and reset
    - `held_order` — order blocked by anomaly gate (duplicate ID / impossible deadline)
    - `quality_failure` — inspection failed; no rework order dispatched yet
    - `low_inventory` — material below reorder threshold

    **Severity:**
    - `critical` — production is blocked or at risk
    - `warning` — degraded but not yet stopped
    - `info` — informational only
    """
    agent = _get_agent()
    items = agent.gather(
        db,
        include_resolved=include_resolved,
        source_filter=source,
        severity_filter=severity,
        limit=limit,
    )
    return {
        "count": len(items),
        "exceptions": [i.to_dict() for i in items],
    }


@router.get(
    "/summary",
    summary="Exception count by source and severity",
)
async def exception_summary(db: Session = Depends(get_db)):
    """
    Returns a lightweight count breakdown — suitable for dashboard badge counts.

    ```json
    {
      "open_exceptions": 4,
      "critical": 2,
      "warning": 2,
      "info": 0,
      "by_source": {
        "machine_fault": 1,
        "held_order": 1,
        "quality_failure": 2
      }
    }
    ```
    """
    return _get_agent().summary(db)


@router.patch(
    "/{exc_id:path}/resolve",
    summary="Mark an exception resolved",
)
async def resolve_exception(exc_id: str, db: Session = Depends(get_db)):
    """
    Mark an exception as resolved. It will no longer appear in the default
    (unresolved) list. Pass `?include_resolved=true` to see it.

    Idempotent — resolving an already-resolved exception is a no-op.
    """
    mark_resolved(exc_id, db=db)
    return {"id": exc_id, "resolved": True}


@router.patch(
    "/{exc_id:path}/unresolve",
    summary="Reopen a resolved exception",
)
async def unresolve_exception(exc_id: str, db: Session = Depends(get_db)):
    """
    Reopen a previously resolved exception. Useful when a fix didn't hold
    (e.g. a machine faulted again after reset).
    """
    was_resolved = mark_unresolved(exc_id, db=db)
    return {"id": exc_id, "resolved": False, "was_resolved": was_resolved}
