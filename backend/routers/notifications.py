"""
/api/notifications — user-scoped notifications and alerts.

Surfaces the Notification table to the frontend. All endpoints are
authenticated and scoped to the current user.

Endpoints:
    GET  /api/notifications                — list (optionally unread-only)
    POST /api/notifications                — create a new notification
    PUT  /api/notifications/{id}/read      — mark a single notification read
    POST /api/notifications/dismiss-all    — mark every notification read
    GET  /api/notifications/unread-count   — badge counter
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import Notification, User


router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


_VALID_SEVERITIES = {"critical", "warning", "info"}
_VALID_CATEGORIES = {
    "quality", "scheduling", "maintenance", "inventory",
    "supplier", "energy", "billing", "system",
}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NotificationCreate(BaseModel):
    severity: str = Field(..., description="critical | warning | info")
    category: str = Field(..., description="quality | scheduling | maintenance | inventory | supplier | energy | billing | system")
    title: str = Field(..., max_length=255)
    body: Optional[str] = None
    source_table: Optional[str] = Field(None, max_length=100)
    source_id: Optional[int] = None
    payload: Optional[dict] = None


class NotificationOut(BaseModel):
    id: int
    severity: str
    category: str
    title: str
    body: Optional[str]
    source_table: Optional[str]
    source_id: Optional[int]
    payload: dict
    read_at: Optional[datetime]
    is_read: bool
    created_at: datetime


class NotificationList(BaseModel):
    notifications: list[NotificationOut]
    total: int
    unread: int


class DismissAllResponse(BaseModel):
    dismissed: int


class UnreadCountResponse(BaseModel):
    unread: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        severity=n.severity,
        category=n.category,
        title=n.title,
        body=n.body,
        source_table=n.source_table,
        source_id=n.source_id,
        payload=n.payload,
        read_at=n.read_at,
        is_read=n.is_read,
        created_at=n.created_at,
    )


def create_notification(
    db: Session,
    *,
    user_id: Optional[int],
    severity: str,
    category: str,
    title: str,
    body: Optional[str] = None,
    source_table: Optional[str] = None,
    source_id: Optional[int] = None,
    payload: Optional[dict] = None,
) -> Notification:
    """Programmatic helper — agents/routers can create notifications directly.

    Importable from other modules without triggering FastAPI auth.
    """
    if severity not in _VALID_SEVERITIES:
        raise ValueError(f"invalid severity {severity!r}; must be one of {_VALID_SEVERITIES}")
    if category not in _VALID_CATEGORIES:
        raise ValueError(f"invalid category {category!r}; must be one of {_VALID_CATEGORIES}")

    n = Notification(
        user_id=user_id,
        severity=severity,
        category=category,
        title=title[:255],
        body=body,
        source_table=source_table,
        source_id=source_id,
        payload_json=json.dumps(payload) if payload else None,
    )
    db.add(n)
    db.commit()
    db.refresh(n)
    return n


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("", response_model=NotificationList, summary="List notifications")
def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=500),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationList:
    q = db.query(Notification).filter(Notification.user_id == user.id)

    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    if category:
        if category not in _VALID_CATEGORIES:
            raise HTTPException(400, f"invalid category {category!r}")
        q = q.filter(Notification.category == category)
    if severity:
        if severity not in _VALID_SEVERITIES:
            raise HTTPException(400, f"invalid severity {severity!r}")
        q = q.filter(Notification.severity == severity)

    total = q.count()
    unread = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )
    rows = q.order_by(desc(Notification.created_at)).limit(limit).all()
    return NotificationList(
        notifications=[_to_out(n) for n in rows],
        total=total,
        unread=unread,
    )


@router.post("", response_model=NotificationOut, summary="Create a notification")
def create_notification_endpoint(
    payload: NotificationCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationOut:
    if payload.severity not in _VALID_SEVERITIES:
        raise HTTPException(400, f"invalid severity {payload.severity!r}")
    if payload.category not in _VALID_CATEGORIES:
        raise HTTPException(400, f"invalid category {payload.category!r}")

    n = create_notification(
        db,
        user_id=user.id,
        severity=payload.severity,
        category=payload.category,
        title=payload.title,
        body=payload.body,
        source_table=payload.source_table,
        source_id=payload.source_id,
        payload=payload.payload,
    )
    return _to_out(n)


@router.put("/{notification_id}/read", response_model=NotificationOut, summary="Mark a notification as read")
def mark_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> NotificationOut:
    n = (
        db.query(Notification)
        .filter(Notification.id == notification_id, Notification.user_id == user.id)
        .first()
    )
    if n is None:
        raise HTTPException(404, "notification not found")
    if n.read_at is None:
        n.read_at = _now()
        db.commit()
        db.refresh(n)
    return _to_out(n)


@router.post("/dismiss-all", response_model=DismissAllResponse, summary="Dismiss all notifications for the current user")
def dismiss_all(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DismissAllResponse:
    now = _now()
    count = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .update({"read_at": now}, synchronize_session=False)
    )
    db.commit()
    return DismissAllResponse(dismissed=int(count))


@router.get("/unread-count", response_model=UnreadCountResponse, summary="Unread notification count")
def unread_count(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UnreadCountResponse:
    n = (
        db.query(Notification)
        .filter(Notification.user_id == user.id, Notification.read_at.is_(None))
        .count()
    )
    return UnreadCountResponse(unread=int(n))
