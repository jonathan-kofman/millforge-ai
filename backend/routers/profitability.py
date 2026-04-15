"""
/api/profitability — quote-vs-actual margin analysis.

Two endpoints:
  GET /api/profitability/quote/{shop_quote_id}  — single-quote autopsy
  GET /api/profitability/summary                 — last 50 jobs roll-up
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import User
from agents.profitability_analyzer import ProfitabilityAnalyzer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/profitability", tags=["Profitability"])

_analyzer = ProfitabilityAnalyzer()


@router.get("/quote/{shop_quote_id}", summary="Quote vs actual autopsy for a single ShopQuote")
def autopsy_single_quote(
    shop_quote_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    report = _analyzer.autopsy_quote(db, shop_quote_id=shop_quote_id)
    if report is None:
        raise HTTPException(
            status_code=404,
            detail=f"ShopQuote {shop_quote_id} not found or has no completed operations",
        )
    return report.to_dict()


@router.get("/summary", summary="Last 50 quotes — aggregate margin drift + top leaks")
def shop_summary(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return _analyzer.shop_summary(db, user_id=user.id)
