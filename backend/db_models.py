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
    # Stripe subscription (optional — set via billing webhooks)
    stripe_customer_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    stripe_subscription_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    subscription_tier: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    subscription_status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

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
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    po_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    part_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    process_type: Mapped[Optional[str]] = mapped_column(String(50), default="cnc_milling", nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    quoted_price_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
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
    # ARIA-sourced fields — populated automatically from cam_metadata when available
    simulation_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    tolerance_class: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
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
    operations: Mapped[List["Operation"]] = relationship(
        "Operation", foreign_keys="Operation.job_id", back_populates="job"
    )

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
    lead_time_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # pmpa | msci | manual | user_submitted
    data_source: Mapped[str] = mapped_column(String(50), default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<Supplier id={self.id} name={self.name} state={self.state}>"


class MarketplaceRFQ(Base):
    """Buyer-posted material request visible on the RFQ board."""

    __tablename__ = "marketplace_rfqs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rfq_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    material: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    deadline: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)   # ISO date string
    location: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    certs: Mapped[list] = mapped_column(JSON, default=list)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    response_count: Mapped[int] = mapped_column(Integer, default=0)
    posted_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    responses: Mapped[list["MarketplaceRFQResponse"]] = relationship(
        "MarketplaceRFQResponse", back_populates="rfq", cascade="all, delete-orphan"
    )


class MarketplaceRFQResponse(Base):
    """Supplier response to a marketplace RFQ."""

    __tablename__ = "marketplace_rfq_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rfq_id: Mapped[int] = mapped_column(Integer, ForeignKey("marketplace_rfqs.id"), nullable=False)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price_indication: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    lead_time_indication: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    responded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    rfq: Mapped["MarketplaceRFQ"] = relationship("MarketplaceRFQ", back_populates="responses")


class ToolRecord(Base):
    """Registered CNC tool — tracks identity and expected life."""

    __tablename__ = "tool_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tool_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    machine_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    tool_type: Mapped[str] = mapped_column(String(50), default="end_mill")
    material: Mapped[str] = mapped_column(String(50), default="steel")
    expected_life_minutes: Mapped[float] = mapped_column(Float, default=480.0)
    # latest wear state (denormalized for quick queries)
    wear_score: Mapped[float] = mapped_column(Float, default=0.0)
    alert_level: Mapped[str] = mapped_column(String(20), default="GREEN")
    rul_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    registered_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    readings: Mapped[List["SensorReading"]] = relationship(
        "SensorReading", back_populates="tool", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ToolRecord tool_id={self.tool_id} alert={self.alert_level}>"


class SensorReading(Base):
    """Raw spectral sensor snapshot for a tool at a point in time."""

    __tablename__ = "sensor_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tool_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("tool_records.tool_id"), nullable=False, index=True
    )
    # Raw feature values stored as JSON for forward compatibility
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    wear_score: Mapped[float] = mapped_column(Float, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    tool: Mapped["ToolRecord"] = relationship("ToolRecord", back_populates="readings")

    def __repr__(self) -> str:
        return f"<SensorReading tool_id={self.tool_id} wear={self.wear_score:.1f}>"


# ---------------------------------------------------------------------------
# Quality & Compliance modules
# ---------------------------------------------------------------------------


class MaterialCert(Base):
    """Mill Test Report (MTR) — OCR-extracted material certification."""

    __tablename__ = "material_certs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id"), nullable=True, index=True
    )
    order_id_str: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    heat_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    material_spec: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    spec_standard: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    spec_grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    chemistry_json: Mapped[str] = mapped_column(Text, default="{}")
    mechanicals_json: Mapped[str] = mapped_column(Text, default="{}")
    # pending | pass | fail | review
    verification_status: Mapped[str] = mapped_column(String(20), default="pending")
    verification_details_json: Mapped[str] = mapped_column(Text, default="[]")
    uploaded_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    @property
    def chemistry(self) -> dict:
        return json.loads(self.chemistry_json)

    @property
    def mechanicals(self) -> dict:
        return json.loads(self.mechanicals_json)

    @property
    def verification_details(self) -> list:
        return json.loads(self.verification_details_json)

    def __repr__(self) -> str:
        return f"<MaterialCert id={self.id} spec={self.material_spec} status={self.verification_status}>"


class DrawingInspection(Base):
    """Engineering drawing with extracted GD&T callouts and inspection plan."""

    __tablename__ = "drawing_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id"), nullable=True, index=True
    )
    order_id_str: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    callouts_json: Mapped[str] = mapped_column(Text, default="[]")
    inspection_plan_json: Mapped[str] = mapped_column(Text, default="[]")
    instruments_json: Mapped[str] = mapped_column(Text, default="[]")
    # draft | approved | in_progress | complete
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    @property
    def callouts(self) -> list:
        return json.loads(self.callouts_json)

    @property
    def inspection_plan(self) -> list:
        return json.loads(self.inspection_plan_json)

    def __repr__(self) -> str:
        return f"<DrawingInspection id={self.id} status={self.status}>"


class LogbookEntry(Base):
    """Shop floor shift logbook entry."""

    __tablename__ = "logbook_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    author_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    machine_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("machines.id"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id"), nullable=True, index=True
    )
    shift_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    # note | issue | observation | handover
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    # info | warning | critical (for issues)
    severity: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    photos_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    @property
    def photos(self) -> list:
        return json.loads(self.photos_json)

    @property
    def tags(self) -> list:
        return json.loads(self.tags_json)

    def __repr__(self) -> str:
        return f"<LogbookEntry id={self.id} category={self.category} title={self.title!r}>"


class LogbookAISummary(Base):
    """AI-generated shift summary / morning briefing."""

    __tablename__ = "logbook_ai_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    shift_date: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    shift_number: Mapped[int] = mapped_column(Integer, nullable=False)
    summary_text: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")
    generated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<LogbookAISummary date={self.shift_date} shift={self.shift_number}>"


class AS9100Clause(Base):
    """AS9100D clause definition — seeded on first use."""

    __tablename__ = "as9100_clauses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    clause_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    clause_title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_documents_json: Mapped[str] = mapped_column(Text, default="[]")

    @property
    def required_documents(self) -> list:
        return json.loads(self.required_documents_json)

    def __repr__(self) -> str:
        return f"<AS9100Clause {self.clause_number}: {self.clause_title}>"


class AS9100ComplianceStatus(Base):
    """Per-user compliance tracking for each AS9100D clause."""

    __tablename__ = "as9100_compliance_status"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    clause_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("as9100_clauses.id"), nullable=False, index=True
    )
    # not_started | in_progress | documented | verified | non_conforming
    status: Mapped[str] = mapped_column(String(20), default="not_started")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text, default="[]")
    last_reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    @property
    def evidence(self) -> list:
        return json.loads(self.evidence_json)

    def __repr__(self) -> str:
        return f"<AS9100ComplianceStatus user={self.user_id} clause={self.clause_id} status={self.status}>"


class AS9100Procedure(Base):
    """AI-generated QMS procedure for an AS9100D clause."""

    __tablename__ = "as9100_procedures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    clause_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("as9100_clauses.id"), nullable=False, index=True
    )
    procedure_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    # draft | review | approved
    status: Mapped[str] = mapped_column(String(20), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    def __repr__(self) -> str:
        return f"<AS9100Procedure id={self.id} clause={self.clause_id} status={self.status}>"


class AS9100AuditTrail(Base):
    """Polymorphic event log linking quality records to AS9100 clauses."""

    __tablename__ = "as9100_audit_trail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=False, index=True
    )
    # mtr_uploaded | inspection_created | logbook_entry | procedure_approved | ...
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # material_certs | drawing_inspections | logbook_entries | as9100_procedures | ...
    source_table: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    def __repr__(self) -> str:
        return f"<AS9100AuditTrail {self.event_type} source={self.source_table}:{self.source_id}>"


class ToolingInsert(Base):
    """Tooling insert with ISO/ANSI designation and cross-manufacturer equivalents."""

    __tablename__ = "tooling_inserts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    manufacturer: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    part_number: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    iso_designation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, index=True)
    ansi_designation: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    insert_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    grade: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    coating: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    geometry_json: Mapped[str] = mapped_column(Text, default="{}")
    unit_cost_usd: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    equivalents_json: Mapped[str] = mapped_column(Text, default="[]")
    wear_data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    @property
    def geometry(self) -> dict:
        return json.loads(self.geometry_json)

    @property
    def equivalents(self) -> list:
        return json.loads(self.equivalents_json)

    def __repr__(self) -> str:
        return f"<ToolingInsert {self.manufacturer} {self.part_number}>"


class ToolPresetMeasurement(Base):
    """CV tool presetter measurement record."""

    __tablename__ = "tool_preset_measurements"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    tool_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("tool_records.tool_id"), nullable=False, index=True
    )
    measured_length_mm: Mapped[float] = mapped_column(Float, nullable=False)
    measured_diameter_mm: Mapped[float] = mapped_column(Float, nullable=False)
    image_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<ToolPresetMeasurement tool={self.tool_id} L={self.measured_length_mm} D={self.measured_diameter_mm}>"


class ExceptionResolution(Base):
    """Persisted exception resolutions — survives server restart."""

    __tablename__ = "exception_resolutions"

    exc_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    resolved_at: Mapped[str] = mapped_column(String(50), nullable=False)

    def __repr__(self) -> str:
        return f"<ExceptionResolution {self.exc_id}>"


class WorkOrderRecord(Base):
    """Persisted manufacturing work orders."""

    __tablename__ = "work_order_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    work_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    part_id: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="draft")
    priority: Mapped[int] = mapped_column(Integer, default=5)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    def __repr__(self) -> str:
        return f"<WorkOrderRecord {self.work_order_id} status={self.status}>"


# =============================================================================
# WORK CENTER SCHEMA — generalized manufacturing abstraction (0004 migration)
# =============================================================================

class WorkCenter(Base):
    """Universal machine / work station. Category covers all fab process types."""

    __tablename__ = "work_centers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    # cnc_mill | cnc_lathe | cnc_router | cnc_grinder | laser_cutter | waterjet |
    # plasma_cutter | press_brake | punch_press | shear | mig_welder | tig_welder |
    # spot_welder | manual_mill | manual_lathe | drill_press | band_saw |
    # surface_grinder | heat_treat_oven | powder_coat_booth | paint_booth |
    # anodizing_line | plating_line | blast_cabinet | assembly_bench |
    # inspection_station | cmm | fdm_printer | sla_printer | packaging_station | other
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # available | in_use | setup | maintenance | breakdown | offline
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available", index=True)
    hourly_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    setup_time_default_min: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    # {"mon":[7,17],"tue":[7,17],...}
    available_hours_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    capabilities_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    operations: Mapped[List["Operation"]] = relationship("Operation", back_populates="work_center")
    floor_events: Mapped[List["ShopFloorEvent"]] = relationship("ShopFloorEvent", back_populates="work_center")

    @property
    def capabilities(self) -> dict:
        return json.loads(self.capabilities_json) if self.capabilities_json else {}

    def __repr__(self) -> str:
        return f"<WorkCenter id={self.id} name={self.name} category={self.category}>"


class Operator(Base):
    """Shop floor operator with PIN tablet login and work center qualifications."""

    __tablename__ = "operators"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    initials: Mapped[str] = mapped_column(String(6), nullable=False)
    pin_code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    qualifications_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    operations: Mapped[List["Operation"]] = relationship("Operation", back_populates="operator")
    floor_events: Mapped[List["ShopFloorEvent"]] = relationship("ShopFloorEvent", back_populates="operator")

    @property
    def qualifications(self) -> list:
        return json.loads(self.qualifications_json) if self.qualifications_json else []

    def __repr__(self) -> str:
        return f"<Operator id={self.id} name={self.name}>"


class ShopQuote(Base):
    """DB-persisted shop quote with full cost breakdown."""

    __tablename__ = "shop_quotes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    quote_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    customer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    part_name: Mapped[str] = mapped_column(String(255), nullable=False)
    part_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    revision: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    material: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    routing_template_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("routing_templates.id"), nullable=True)
    material_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    labor_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    overhead_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    subcontract_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    markup_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    total_price: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    price_per_part: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # draft | sent | accepted | rejected | expired
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    valid_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    routing_template: Mapped[Optional["RoutingTemplate"]] = relationship("RoutingTemplate", back_populates="shop_quotes")
    operations: Mapped[List["Operation"]] = relationship("Operation", back_populates="shop_quote")

    @property
    def subtotal(self) -> float:
        return self.material_cost + self.labor_cost + self.overhead_cost + self.subcontract_cost

    def __repr__(self) -> str:
        return f"<ShopQuote {self.quote_number} status={self.status} total={self.total_price}>"


class RoutingTemplate(Base):
    """Reusable sequence of operations for a known part family."""

    __tablename__ = "routing_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    steps: Mapped[List["RoutingStep"]] = relationship(
        "RoutingStep", back_populates="template",
        order_by="RoutingStep.sequence_number", cascade="all, delete-orphan"
    )
    shop_quotes: Mapped[List["ShopQuote"]] = relationship("ShopQuote", back_populates="routing_template")

    def __repr__(self) -> str:
        return f"<RoutingTemplate id={self.id} name={self.name}>"


class RoutingStep(Base):
    """One step within a routing template."""

    __tablename__ = "routing_steps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    template_id: Mapped[int] = mapped_column(Integer, ForeignKey("routing_templates.id"), nullable=False, index=True)
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_center_category: Mapped[str] = mapped_column(String(50), nullable=False)
    estimated_setup_min: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    estimated_run_min_per_part: Mapped[float] = mapped_column(Float, nullable=False, default=5.0)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    template: Mapped["RoutingTemplate"] = relationship("RoutingTemplate", back_populates="steps")

    def __repr__(self) -> str:
        return f"<RoutingStep seq={self.sequence_number} op={self.operation_name}>"


class Operation(Base):
    """Process-agnostic unit of work. One operation = one run at one work center."""

    __tablename__ = "operations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_ref: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("jobs.id"), nullable=True, index=True)
    shop_quote_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("shop_quotes.id"), nullable=True)
    work_center_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("work_centers.id"), nullable=True, index=True)
    operator_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("operators.id"), nullable=True)
    depends_on_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("operations.id"), nullable=True)
    # ARIA bridge V2 — process-agnostic fields
    inspection_required: Mapped[bool] = mapped_column(Boolean, default=False)
    is_subcontracted: Mapped[bool] = mapped_column(Boolean, default=False)
    subcontractor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    subcontractor_lead_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ai_confidence: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    detected_features_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    operation_name: Mapped[str] = mapped_column(String(255), nullable=False)
    work_center_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # pending | queued | in_progress | paused | complete | on_hold | cancelled | rework
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)

    estimated_setup_min: Mapped[float] = mapped_column(Float, nullable=False, default=30.0)
    estimated_run_min: Mapped[float] = mapped_column(Float, nullable=False, default=60.0)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    actual_setup_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    actual_run_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity_complete: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    quantity_scrapped: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    scrap_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    setup_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    run_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    work_center: Mapped[Optional["WorkCenter"]] = relationship("WorkCenter", back_populates="operations")
    operator: Mapped[Optional["Operator"]] = relationship("Operator", back_populates="operations")
    shop_quote: Mapped[Optional["ShopQuote"]] = relationship("ShopQuote", back_populates="operations")
    job: Mapped[Optional["Job"]] = relationship("Job", foreign_keys=[job_id], back_populates="operations")
    floor_events: Mapped[List["ShopFloorEvent"]] = relationship("ShopFloorEvent", back_populates="operation")
    ncrs: Mapped[List["NonConformanceReport"]] = relationship("NonConformanceReport", back_populates="operation")

    def __repr__(self) -> str:
        return f"<Operation id={self.id} op={self.operation_name} status={self.status}>"


class ShopFloorEvent(Base):
    """Append-only event log. Every status change, clock-in/out, material issue, quality hold."""

    __tablename__ = "shop_floor_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    operation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("operations.id"), nullable=True, index=True)
    work_center_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("work_centers.id"), nullable=True, index=True)
    operator_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("operators.id"), nullable=True)
    # op_started | setup_complete | op_completed | op_paused | quality_hold |
    # material_issued | status_change | operator_login
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    operation: Mapped[Optional["Operation"]] = relationship("Operation", back_populates="floor_events")
    work_center: Mapped[Optional["WorkCenter"]] = relationship("WorkCenter", back_populates="floor_events")
    operator: Mapped[Optional["Operator"]] = relationship("Operator", back_populates="floor_events")

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json) if self.payload_json else {}

    def __repr__(self) -> str:
        return f"<ShopFloorEvent type={self.event_type} at={self.occurred_at}>"


class NonConformanceReport(Base):
    """NCR: a specific quality failure tied to an operation."""

    __tablename__ = "non_conformance_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    operation_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("operations.id"), nullable=True)
    order_ref: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    # critical | major | minor
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="minor")
    # open | in_rework | resolved | closed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    resolution: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    operation: Mapped[Optional["Operation"]] = relationship("Operation", back_populates="ncrs")

    def __repr__(self) -> str:
        return f"<NCR id={self.id} sev={self.severity} status={self.status}>"


class FirstArticleInspection(Base):
    """FAI record: dimensional measurements against a print/spec."""

    __tablename__ = "first_article_inspections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_ref: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, index=True)
    part_name: Mapped[str] = mapped_column(String(255), nullable=False)
    part_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    revision: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    inspector: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # pass | fail | conditional
    result: Mapped[str] = mapped_column(String(20), nullable=False, default="pass")
    # [{"dim_id":"1","nominal":25.0,"tolerance":0.025,"actual":25.012,"pass":true}, ...]
    measurements_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    @property
    def measurements(self) -> list:
        return json.loads(self.measurements_json)

    @property
    def dims_total(self) -> int:
        return len(self.measurements)

    @property
    def dims_passed(self) -> int:
        return sum(1 for m in self.measurements if m.get("pass", False))

    def __repr__(self) -> str:
        return f"<FAI id={self.id} part={self.part_name} result={self.result}>"


class ProductEvent(Base):
    """
    Self-hosted product analytics event log.

    Records every meaningful user action for health scoring and founder
    dashboards without sending data to third-party analytics services.

    event_category: scheduling | quality | supplier | energy | onboarding | billing
    event_type:     schedule_run | nl_override | benchmark_viewed | qc_inspected |
                    supplier_searched | energy_analysis | order_created | quote_generated |
                    template_applied | operator_login | shift_completed | ...
    """

    __tablename__ = "product_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    event_category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # Optional FK to the source record (job_id, operation_id, schedule_run_id, etc.)
    source_table: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Arbitrary event payload (e.g. algorithm used, on_time_rate, material)
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json) if self.payload_json else {}

    def __repr__(self) -> str:
        return f"<ProductEvent cat={self.event_category} type={self.event_type} at={self.occurred_at}>"


class Notification(Base):
    """
    User-scoped notification / alert record.

    Emitted by background jobs, routers, and agents when the system wants
    to surface something for a human to see (critical QC fail, supplier
    below reorder point, maintenance due, shift report ready, etc.).

    severity:  critical | warning | info
    category:  quality | scheduling | maintenance | inventory | supplier |
               energy | billing | system

    Marking read is idempotent — ``read_at`` is set once and never cleared.
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True, index=True
    )
    severity: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Optional link-out: source table + id (e.g. ("jobs", 42))
    source_table: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # Arbitrary extra context — JSON blob
    payload_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    read_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    @property
    def payload(self) -> dict:
        return json.loads(self.payload_json) if self.payload_json else {}

    def __repr__(self) -> str:
        return (
            f"<Notification id={self.id} sev={self.severity} "
            f"cat={self.category} read={self.is_read}>"
        )
