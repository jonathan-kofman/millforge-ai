"""
Marketplace RFQ board — buyers post material requests, suppliers respond.
"""

from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from db_models import MarketplaceRFQ, MarketplaceRFQResponse
from models.schemas import RFQCreate, RFQResponseCreate, RFQOut, RFQResponseOut

router = APIRouter(prefix="/api/rfqs", tags=["Marketplace"])

_rfq_counter = 0


def _next_rfq_id() -> str:
    """Generate sequential RFQ-NNN IDs. Resets on restart — fine for pilot."""
    global _rfq_counter
    _rfq_counter += 1
    return f"RFQ-{_rfq_counter:03d}"


def _init_counter(db: Session) -> None:
    """Sync in-memory counter to DB on first use."""
    global _rfq_counter
    if _rfq_counter == 0:
        count = db.query(MarketplaceRFQ).count()
        _rfq_counter = count


@router.post("", response_model=RFQOut, status_code=201)
def create_rfq(body: RFQCreate, db: Session = Depends(get_db)):
    _init_counter(db)
    rfq = MarketplaceRFQ(
        rfq_id=_next_rfq_id(),
        material=body.material,
        quantity=body.quantity,
        deadline=body.deadline,
        location=body.location,
        certs=body.certs,
        notes=body.notes,
        email=body.email,
    )
    db.add(rfq)
    db.commit()
    db.refresh(rfq)
    return rfq


@router.get("", response_model=List[RFQOut])
def list_rfqs(limit: int = 20, db: Session = Depends(get_db)):
    return (
        db.query(MarketplaceRFQ)
        .order_by(MarketplaceRFQ.posted_at.desc())
        .limit(limit)
        .all()
    )


@router.post("/{rfq_id}/respond", response_model=RFQResponseOut, status_code=201)
def respond_to_rfq(rfq_id: str, body: RFQResponseCreate, db: Session = Depends(get_db)):
    rfq = db.query(MarketplaceRFQ).filter(MarketplaceRFQ.rfq_id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail=f"RFQ {rfq_id} not found")

    resp = MarketplaceRFQResponse(
        rfq_id=rfq.id,
        supplier_name=body.supplier_name,
        email=body.email,
        message=body.message,
        price_indication=body.price_indication,
        lead_time_indication=body.lead_time_indication,
    )
    rfq.response_count += 1
    db.add(resp)
    db.commit()
    db.refresh(resp)
    return resp
