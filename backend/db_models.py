"""
MillForge SQLAlchemy ORM models.

These are the database-layer representations. They are separate from
the Pydantic schemas in models/schemas.py (which are the API layer).
"""

import json
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey,
    Integer, JSON, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    orders: Mapped[List["OrderRecord"]] = relationship("OrderRecord", back_populates="owner")

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


class OrderRecord(Base):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    material: Mapped[str] = mapped_column(String(50), nullable=False)
    dimensions: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=5)
    complexity: Mapped[float] = mapped_column(Float, default=1.0)
    due_date: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    # pending | scheduled | in_progress | completed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="pending")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    owner: Mapped[Optional["User"]] = relationship("User", back_populates="orders")
    inspections: Mapped[List["InspectionRecord"]] = relationship(
        "InspectionRecord", back_populates="order_ref", foreign_keys="InspectionRecord.order_record_id"
    )

    def __repr__(self) -> str:
        return f"<OrderRecord order_id={self.order_id} status={self.status}>"


class ScheduleRun(Base):
    __tablename__ = "schedule_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    algorithm: Mapped[str] = mapped_column(String(20), nullable=False)
    # JSON-serialised list of order_ids included in this run
    order_ids_json: Mapped[str] = mapped_column(Text, nullable=False)
    # JSON-serialised ScheduleSummary dict
    summary_json: Mapped[str] = mapped_column(Text, nullable=False)
    on_time_rate: Mapped[float] = mapped_column(Float, nullable=False)
    makespan_hours: Mapped[float] = mapped_column(Float, nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    @property
    def order_ids(self) -> List[str]:
        return json.loads(self.order_ids_json)

    @property
    def summary(self) -> dict:
        return json.loads(self.summary_json)


class InspectionRecord(Base):
    __tablename__ = "inspection_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_record_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("orders.id"), nullable=True
    )
    order_id_str: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    image_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    defects_json: Mapped[str] = mapped_column(Text, default="[]")
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    inspector_version: Mapped[str] = mapped_column(String(50), default="mock-v0.1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    order_ref: Mapped[Optional["OrderRecord"]] = relationship(
        "OrderRecord", back_populates="inspections", foreign_keys=[order_record_id]
    )

    @property
    def defects(self) -> List[str]:
        return json.loads(self.defects_json)


class ContactSubmission(Base):
    __tablename__ = "contact_submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    company: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    pilot_interest: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MachineStateLog(Base):
    """Timestamped record of every CNC machine state transition."""

    __tablename__ = "machine_state_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    machine_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    job_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    from_state: Mapped[str] = mapped_column(String(20), nullable=False)
    to_state: Mapped[str] = mapped_column(String(20), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<MachineStateLog machine={self.machine_id} {self.from_state}→{self.to_state}>"


class JobFeedbackRecord(Base):
    """Actual vs predicted job metrics — feeds SetupTimePredictor and SchedulingTwin."""

    __tablename__ = "job_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    canonical_id: Mapped[str] = mapped_column(String(200), unique=True, nullable=False, index=True)
    order_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    material: Mapped[str] = mapped_column(String(50), nullable=False)
    machine_id: Mapped[int] = mapped_column(Integer, nullable=False)
    predicted_setup_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    actual_setup_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    predicted_processing_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    actual_processing_minutes: Mapped[float] = mapped_column(Float, nullable=False)
    # operator_logged | mtconnect_auto | estimated
    data_provenance: Mapped[str] = mapped_column(String(30), nullable=False, default="operator_logged")
    logged_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<JobFeedbackRecord {self.canonical_id} provenance={self.data_provenance}>"


class Supplier(Base):
    """US metal/materials supplier record."""

    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    country: Mapped[str] = mapped_column(String(50), default="US")
    lat: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    lng: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # JSON list of material strings (e.g. ["steel", "aluminum"])
    materials: Mapped[list] = mapped_column(JSON, default=list)
    # JSON list of category strings (e.g. ["metals", "raw_materials"])
    categories: Mapped[list] = mapped_column(JSON, default=list)
    phone: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    website: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # pmpa | msci | manual | user_submitted
    data_source: Mapped[str] = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<Supplier id={self.id} name={self.name} state={self.state}>"
