"""
/api/orders/.../tracking — customer order tracking portal endpoints.

Three layers:
  - POST /api/orders/{order_id}/tracking-link  (auth) — shop creates a share link
  - GET  /api/orders/{order_id}/tracking-link  (auth) — shop lists active links
  - GET  /api/track/{token}                    (public) — customer view, no auth

The public endpoint deliberately exposes only:
  customer_name, part_number, status, due_date, last_updated, progress_percent
It does NOT expose: pricing, schedules, internal job_id, profitability, or
any sibling orders. Each successful view increments view_count + sets
last_viewed_at so the shop can see customer engagement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import OrderRecord, User
from models.tracking import CustomerTrackingLink

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Customer Tracking"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class TrackingLinkCreateRequest(BaseModel):
    label: Optional[str] = Field(None, max_length=255, description="Internal label for the link (customer name, PO, etc.)")
    expires_in_days: Optional[int] = Field(60, ge=1, le=365, description="Link expiration window")


class TrackingLinkResponse(BaseModel):
    id: int
    token: str
    order_id: str
    label: Optional[str]
    public_url_path: str
    created_at: datetime
    expires_at: Optional[datetime]
    view_count: int
    last_viewed_at: Optional[datetime]
    revoked: bool


class CustomerOrderView(BaseModel):
    """The minimal set of fields that's safe to expose to a customer."""
    order_id: str
    customer_name: Optional[str]
    part_number: Optional[str]
    status: str
    due_date: datetime
    progress_percent: int
    last_updated: datetime
    powered_by: str = "MillForge"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _status_to_progress(status_str: str) -> int:
    """Convert order.status to a 0-100 progress estimate the customer sees."""
    return {
        "pending":      10,
        "scheduled":    25,
        "in_progress":  60,
        "completed":    100,
        "cancelled":    0,
    }.get((status_str or "").lower(), 0)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Authenticated: shop-side link management
# ---------------------------------------------------------------------------


@router.post(
    "/api/orders/{order_id}/tracking-link",
    response_model=TrackingLinkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a customer-facing tracking link for an order",
)
def create_tracking_link(
    order_id: str,
    req: TrackingLinkCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Generates an unguessable token-based URL the shop can send to its
    customer. The customer can then check order status without an account.
    """
    order = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == order_id, OrderRecord.created_by_id == user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found or not yours")

    expires_at = None
    if req.expires_in_days:
        expires_at = _now() + timedelta(days=req.expires_in_days)

    link = CustomerTrackingLink(
        order_id=order_id,
        label=req.label,
        created_by_id=user.id,
        expires_at=expires_at,
    )
    db.add(link)
    db.commit()
    db.refresh(link)

    logger.info("Tracking link created: order=%s token=%s by user=%s", order_id, link.token[:8], user.email)

    return TrackingLinkResponse(
        id=link.id,
        token=link.token,
        order_id=link.order_id,
        label=link.label,
        public_url_path=f"/track/{link.token}",
        created_at=link.created_at,
        expires_at=link.expires_at,
        view_count=link.view_count,
        last_viewed_at=link.last_viewed_at,
        revoked=link.revoked,
    )


@router.get(
    "/api/orders/{order_id}/tracking-link",
    response_model=list[TrackingLinkResponse],
    summary="List active tracking links for an order",
)
def list_tracking_links(
    order_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    order = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == order_id, OrderRecord.created_by_id == user.id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail=f"Order {order_id} not found or not yours")

    links = (
        db.query(CustomerTrackingLink)
        .filter(CustomerTrackingLink.order_id == order_id)
        .order_by(CustomerTrackingLink.created_at.desc())
        .all()
    )
    return [
        TrackingLinkResponse(
            id=l.id,
            token=l.token,
            order_id=l.order_id,
            label=l.label,
            public_url_path=f"/track/{l.token}",
            created_at=l.created_at,
            expires_at=l.expires_at,
            view_count=l.view_count,
            last_viewed_at=l.last_viewed_at,
            revoked=l.revoked,
        )
        for l in links
    ]


@router.post(
    "/api/orders/tracking-link/{link_id}/revoke",
    summary="Revoke a tracking link (soft-disable, doesn't delete)",
)
def revoke_tracking_link(
    link_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    link = (
        db.query(CustomerTrackingLink)
        .filter(CustomerTrackingLink.id == link_id, CustomerTrackingLink.created_by_id == user.id)
        .first()
    )
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    link.revoked = True
    db.commit()
    return {"id": link.id, "revoked": True}


# ---------------------------------------------------------------------------
# Public: customer view (no auth)
# ---------------------------------------------------------------------------


@router.get(
    "/api/track/{token}",
    response_model=CustomerOrderView,
    summary="Public customer-facing order status (no auth required)",
)
def public_order_view(token: str, db: Session = Depends(get_db)):
    """
    Customer-facing order view. Increments view_count + last_viewed_at on
    each successful read. Returns 404 for unknown / expired / revoked
    tokens (deliberately doesn't distinguish — leaks less info).
    """
    link = (
        db.query(CustomerTrackingLink)
        .filter(CustomerTrackingLink.token == token)
        .first()
    )
    if not link or not link.is_active():
        raise HTTPException(status_code=404, detail="Tracking link not found or expired")

    order = (
        db.query(OrderRecord)
        .filter(OrderRecord.order_id == link.order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Telemetry update — never block the response if it fails
    try:
        link.view_count = (link.view_count or 0) + 1
        link.last_viewed_at = _now()
        db.commit()
    except Exception:
        db.rollback()

    return CustomerOrderView(
        order_id=order.order_id,
        customer_name=order.customer_name,
        part_number=order.part_number,
        status=order.status,
        due_date=order.due_date,
        progress_percent=_status_to_progress(order.status),
        last_updated=order.updated_at,
    )
