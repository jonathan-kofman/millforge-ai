"""
MillForge Business Router

Exposes BusinessAgent as HTTP endpoints:
  GET  /api/business/pricing-tiers
  GET  /api/business/recommend-tier
  POST /api/business/roi-calculator
  POST /api/business/revenue-projection
  GET  /api/business/metrics
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from agents.business_agent import BusinessAgent
from auth.dependencies import get_current_user
from database import get_db
from db_models import User
from models.schemas import (
    ROICalculatorRequest,
    RevenueProjectionRequest,
    RevenueProjectionResponse,
    TierRecommendRequest,
)

router = APIRouter(prefix="/api/business", tags=["Business"])
_agent = BusinessAgent()


@router.get("/pricing-tiers")
def get_pricing_tiers():
    """Return all MillForge subscription tiers and features."""
    return {"tiers": _agent.get_pricing_tiers()}


@router.get("/recommend-tier")
def recommend_tier(
    machine_count: int = Query(..., ge=1, le=500),
    orders_per_month: int = Query(..., ge=1),
):
    """Recommend the best-fit tier for a shop based on size and volume."""
    return _agent.recommend_tier(machine_count, orders_per_month)


@router.post("/roi-calculator")
def calculate_roi(req: ROICalculatorRequest):
    """
    Calculate annual ROI of deploying MillForge for a specific shop.
    Returns penalty savings, labor savings, throughput gains, and payback months.
    """
    return _agent.calculate_roi(
        machine_count=req.machine_count,
        orders_per_month=req.orders_per_month,
        avg_order_value_usd=req.avg_order_value_usd,
        current_otd_percent=req.current_otd_percent,
        shifts_per_day=req.shifts_per_day,
    )


@router.post("/revenue-projection")
def project_revenue(req: RevenueProjectionRequest):
    """
    Project MRR, ARR, and cumulative revenue over N months using a cohort model.
    """
    return _agent.project_revenue(
        months=req.months,
        starting_customers=req.starting_customers,
        monthly_new_customers=req.monthly_new_customers,
        avg_monthly_revenue_per_customer_usd=req.avg_monthly_revenue_per_customer_usd,
        churn_rate_monthly_percent=req.churn_rate_monthly_percent,
    )


@router.get("/metrics")
def get_business_metrics(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Return live business KPIs: user count, job stats, inspection pass rate."""
    return _agent.get_business_metrics(db)
