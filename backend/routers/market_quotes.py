"""
MillForge Market Quotes Router

Exposes MarketQuoter as HTTP endpoints:
  GET  /api/market-quotes/spot-prices
  POST /api/market-quotes/materials
  POST /api/market-quotes/energy
  POST /api/market-quotes/full-job-cost
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional

from agents.market_quoter import MarketQuoter
from database import get_db
from models.schemas import (
    MaterialsQuoteRequest,
    EnergyQuoteRequest,
    FullJobCostRequest,
)

router = APIRouter(prefix="/api/market-quotes", tags=["Market Quotes"])
_quoter = MarketQuoter()


@router.get("/spot-prices")
def get_spot_prices(
    materials: Optional[str] = Query(
        None,
        description="Comma-separated material names. Omit for all metals.",
    ),
):
    """
    Return current spot prices for metals.
    Sources Yahoo Finance futures API (ALI=F, HG=F, etc.) with 1-hour cache;
    falls back to 2025 market averages when live fetch fails.
    """
    mat_list = [m.strip() for m in materials.split(",")] if materials else None
    return _quoter.get_spot_prices(mat_list)


@router.post("/materials")
def quote_materials(req: MaterialsQuoteRequest, db: Session = Depends(get_db)):
    """
    Find the cheapest suppliers for a material and quantity.
    Ranks options by total landed cost (spot × markup + freight + form surcharge).
    Returns top N options with full cost breakdown.
    """
    return _quoter.quote_materials(
        db=db,
        material=req.material,
        quantity_lbs=req.quantity_lbs,
        delivery_state=req.delivery_state,
        lat=req.lat,
        lng=req.lng,
        mill_form=req.mill_form,
        top_n=req.top_n,
    )


@router.post("/energy")
def quote_energy(req: EnergyQuoteRequest):
    """
    Find the cheapest window to buy grid electricity for a production run.
    Returns cheapest vs peak window and estimated savings.
    """
    return _quoter.quote_energy(
        kwh_needed=req.kwh_needed,
        state=req.state,
        flexible_hours=req.flexible_hours,
    )


@router.post("/full-job-cost")
def quote_full_job(req: FullJobCostRequest, db: Session = Depends(get_db)):
    """
    All-in cost estimate for a job: cheapest materials + energy + 20% overhead.
    Returns cheapest sourcing option with full cost breakdown.
    """
    return _quoter.quote_full_job(
        db=db,
        material=req.material,
        quantity_lbs=req.quantity_lbs,
        estimated_machine_hours=req.estimated_machine_hours,
        machine_power_kw=req.machine_power_kw,
        lat=req.lat,
        lng=req.lng,
        mill_form=req.mill_form,
    )
