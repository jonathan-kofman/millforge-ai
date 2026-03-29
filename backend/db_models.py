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
    # JSON-serialised list of ScheduledOrderOutput dicts — used for PDF export
    schedule_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
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

    @property
    def scheduled_orders(self) -> List[dict]:
        if self.schedule_json:
            return json.loads(self.schedule_json)
        return []


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


class ShopConfig(Base):
    """Per-user shop configuration collected during onboarding wizard."""

    __tablename__ = "shop_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), unique=True, nullable=False, index=True
    )
    shop_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    machine_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # JSON list of material strings e.g. ["steel", "aluminum"]
    materials_json: Mapped[str] = mapped_column(Text, default="[]")
    setup_times_json: Mapped[str] = mapped_column(Text, default="{}")
    baseline_otd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    scheduling_method: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    weekly_order_volume: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Shift calendar — how many production hours per day the shop runs
    shifts_per_day: Mapped[int] = mapped_column(Integer, default=2)
    hours_per_shift: Mapped[int] = mapped_column(Integer, default=8)
    # wizard_step: 0 = not started, 1/2/3 = partial, 3 = complete
    wizard_step: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    @property
    def materials(self) -> List[str]:
        return json.loads(self.materials_json)

    @property
    def setup_times(self) -> dict:
        return json.loads(self.setup_times_json)

    @property
    def is_complete(self) -> bool:
        return bool(self.shop_name and self.machine_count and self.wizard_step >= 3)

    def __repr__(self) -> str:
        return f"<ShopConfig user_id={self.user_id} step={self.wizard_step}>"


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


class InventoryStock(Base):
    """Current stock level for each material — source of truth persisted to DB."""

    __tablename__ = "inventory_stock"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    material: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    quantity_kg: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<InventoryStock material={self.material} qty={self.quantity_kg} kg>"


class Job(Base):
    """ARIA-imported manufacturing job — the unit of work in the lights-out pipeline."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    # queued | in_progress | qc_pending | complete | qc_failed
    stage: Mapped[str] = mapped_column(String(20), default="queued")
    # aria_cam | manual
    source: Mapped[str] = mapped_column(String(30), default="manual")
    material: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    required_machine_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    estimated_duration_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Full ARIA setup sheet JSON stored here
    cam_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    qc_results: Mapped[List["QCResult"]] = relationship("QCResult", back_populates="job")

    def __repr__(self) -> str:
        return f"<Job id={self.id} title={self.title!r} stage={self.stage}>"


class Machine(Base):
    """Physical CNC machine registered in the shop floor."""

    __tablename__ = "machines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    machine_type: Mapped[str] = mapped_column(String(100), nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<Machine id={self.id} name={self.name!r} type={self.machine_type}>"


class QCResult(Base):
    """YOLOv8n defect-detection result attached to a Job."""

    __tablename__ = "qc_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    # JSON-serialised lists
    defects_found_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence_scores_json: Mapped[str] = mapped_column(Text, default="[]")
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    job: Mapped["Job"] = relationship("Job", back_populates="qc_results")

    @property
    def defects_found(self) -> List[str]:
        return json.loads(self.defects_found_json)

    @property
    def confidence_scores(self) -> List[float]:
        return json.loads(self.confidence_scores_json)

    def __repr__(self) -> str:
        return f"<QCResult job_id={self.job_id} passed={self.passed}>"


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
