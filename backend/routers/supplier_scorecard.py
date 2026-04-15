"""
/api/supplier-scorecard — auto-graded supplier performance.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import User
from agents.supplier_scorecard import SupplierScorecardAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/supplier-scorecard", tags=["Supplier Scorecard"])

_agent = SupplierScorecardAgent()


@router.get("", summary="Score every supplier the shop has used in the window")
def list_scorecards(
    window_days: int = Query(365, ge=7, le=1095),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    cards = _agent.score_all(db, user_id=user.id, window_days=window_days)
    return {
        "user_id": user.id,
        "window_days": window_days,
        "supplier_count": len(cards),
        "scorecards": [c.to_dict() for c in cards],
    }


@router.get("/{supplier_name}", summary="Score a single supplier by name")
def get_scorecard(
    supplier_name: str,
    window_days: int = Query(365, ge=7, le=1095),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    card = _agent.score_one(db, supplier_name=supplier_name, user_id=user.id, window_days=window_days)
    if card is None:
        raise HTTPException(
            status_code=404,
            detail=f"No operation history for supplier '{supplier_name}' in the last {window_days} days",
        )
    return card.to_dict()
