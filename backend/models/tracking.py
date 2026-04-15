"""
Customer order tracking — public, unguessable link layer.

SQLAlchemy model for shop-customer share links. Created in a separate
module so it can be merged into db_models.py later without disturbing
the existing class layout.

Usage in main.py / database.py:
    from models.tracking import CustomerTrackingLink  # noqa: F401
    Base.metadata.create_all(bind=engine)  # picks up the new table
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _generate_token() -> str:
    """Generate an unguessable URL-safe token (32 chars, ~192 bits)."""
    return secrets.token_urlsafe(24)


class CustomerTrackingLink(Base):
    """
    Shareable, public-readable link that exposes a single order's status
    to a customer without requiring them to log in.

    The token is the only credential — losing it == losing access. We
    cap views and expiration to limit blast radius if a link leaks.
    """

    __tablename__ = "customer_tracking_links"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Token used in the public URL: /track/{token}
    token: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False, default=_generate_token)
    # Which order this link points at — string match against OrderRecord.order_id
    order_id: Mapped[str] = mapped_column(String(50), index=True, nullable=False)
    # Optional customer-facing label so the operator can find the link later
    label: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # User who created the link (the shop, not the customer)
    created_by_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Telemetry — gives the shop visibility into whether the customer is checking
    view_count: Mapped[int] = mapped_column(Integer, default=0)
    last_viewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    # Soft-disable without deleting (e.g. order delivered)
    revoked: Mapped[bool] = mapped_column(default=False)

    def __repr__(self) -> str:
        return f"<TrackingLink token={self.token[:8]}... order={self.order_id} views={self.view_count}>"

    def is_active(self) -> bool:
        if self.revoked:
            return False
        if self.expires_at and self.expires_at < _now():
            return False
        return True
