"""
Live factory dashboard router — /api/dashboard

GET /api/dashboard/live — authenticated; returns single-snapshot factory health.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from agents.dashboard import DashboardAgent
from auth.dependencies import get_current_user
from database import get_db
from db_models import User

router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_agent: DashboardAgent | None = None


def _get_agent() -> DashboardAgent:
    global _agent
    if _agent is None:
        try:
            from routers.inventory import _inventory
            _agent = DashboardAgent(inventory_agent=_inventory)
        except Exception:
            _agent = DashboardAgent(inventory_agent=None)
    return _agent


@router.get(
    "/live",
    summary="Live factory dashboard",
    description=(
        "Single-snapshot aggregation of all lights-out metrics: open exceptions, "
        "latest schedule health, machine states, maintenance risk, inventory status, "
        "and energy cost. Returns a composite lights_out_score (0–100)."
    ),
)
async def live_dashboard(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return _get_agent().live(db)
