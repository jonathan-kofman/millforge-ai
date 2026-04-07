"""
Pydantic request/response schemas for Quality & Compliance modules.

Covers: MTR Reader (#32), Drawing Reader (#6), Logbook (#23),
AS9100 (#5), Insert Cross-Reference (#21), Tool Presetter (#8).
"""

from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


# ---------------------------------------------------------------------------
# MTR Reader (#32)
# ---------------------------------------------------------------------------

class MTRUploadResponse(BaseModel):
    id: int
    filename: str
    file_hash: str
    heat_number: Optional[str] = None
    material_spec: Optional[str] = None
    spec_standard: Optional[str] = None
    spec_grade: Optional[str] = None
    chemistry: Dict[str, float] = Field(default_factory=dict)
    mechanicals: Dict[str, float] = Field(default_factory=dict)
    verification_status: str = "pending"
    matched_job_id: Optional[int] = None
    extraction_method: str = "pdfplumber"


class PropertyCheck(BaseModel):
    property_name: str
    actual_value: float
    spec_min: Optional[float] = None
    spec_max: Optional[float] = None
    unit: str = ""
    passed: bool = True


class MTRVerifyRequest(BaseModel):
    spec_key: Optional[str] = Field(None, description="Spec key (e.g. 'A276_316L'). Auto-detected if omitted.")


class MTRVerifyResponse(BaseModel):
    id: int
    verification_status: str
    overall_pass: bool
    spec_used: str
    details: List[PropertyCheck]


class MTRListItem(BaseModel):
    id: int
    filename: str
    heat_number: Optional[str] = None
    material_spec: Optional[str] = None
    verification_status: str
    job_id: Optional[int] = None
    uploaded_at: str


class MTRLinkJobRequest(BaseModel):
    job_id: int


# ---------------------------------------------------------------------------
# Drawing Reader (#6)
# ---------------------------------------------------------------------------

class GDTCallout(BaseModel):
    feature_id: str = Field(..., description="Feature identifier (e.g. 'F1', 'BORE-A')")
    dimension_type: str = Field(..., description="diameter | length | depth | flatness | position | ...")
    nominal: float
    tolerance_plus: float
    tolerance_minus: float
    datum_refs: List[str] = Field(default_factory=list)
    surface_finish: Optional[str] = None
    gdt_symbol: Optional[str] = None
    units: str = "mm"


class InspectionStep(BaseModel):
    sequence: int
    feature_id: str
    measurement_method: str = Field(..., description="E.g. 'bore gauge', 'CMM', 'caliper'")
    instrument: str = Field(..., description="Specific instrument recommendation")
    acceptance_criteria: str
    notes: Optional[str] = None


class DrawingUploadResponse(BaseModel):
    id: int
    filename: str
    callouts: List[GDTCallout]
    callout_count: int
    status: str


class InspectionPlanResponse(BaseModel):
    id: int
    steps: List[InspectionStep]
    total_estimated_time_minutes: float
    instruments_required: List[str]
    status: str


class DrawingListItem(BaseModel):
    id: int
    filename: str
    callout_count: int
    status: str
    job_id: Optional[int] = None
    created_at: str


# ---------------------------------------------------------------------------
# Shop Floor Logbook (#23)
# ---------------------------------------------------------------------------

class LogbookCategory(str, Enum):
    NOTE = "note"
    ISSUE = "issue"
    OBSERVATION = "observation"
    HANDOVER = "handover"


class LogbookSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class LogbookEntryCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=255)
    body: str = Field(..., min_length=1)
    category: LogbookCategory
    severity: Optional[LogbookSeverity] = None
    machine_id: Optional[int] = None
    job_id: Optional[int] = None
    shift_date: Optional[datetime] = Field(None, description="Defaults to now if omitted")
    tags: List[str] = Field(default_factory=list)


class LogbookEntryResponse(BaseModel):
    id: int
    author_id: int
    author_name: Optional[str] = None
    machine_id: Optional[int] = None
    machine_name: Optional[str] = None
    job_id: Optional[int] = None
    shift_date: str
    category: str
    severity: Optional[str] = None
    title: str
    body: str
    photos: List[str]
    tags: List[str]
    created_at: str


class LogbookEntryUpdate(BaseModel):
    title: Optional[str] = None
    body: Optional[str] = None
    category: Optional[LogbookCategory] = None
    severity: Optional[LogbookSeverity] = None
    tags: Optional[List[str]] = None


class ShiftSummaryResponse(BaseModel):
    shift_date: str
    shift_number: int
    summary_text: str
    entries_count: int
    generated_at: str


# ---------------------------------------------------------------------------
# AS9100 Certification (#5)
# ---------------------------------------------------------------------------

class ClauseStatus(BaseModel):
    clause_id: int
    clause_number: str
    clause_title: str
    status: str
    evidence_count: int
    last_reviewed_at: Optional[str] = None


class ComplianceDashboard(BaseModel):
    clauses: List[ClauseStatus]
    overall_percent: float = Field(..., description="Percentage of clauses documented or verified")
    total_clauses: int
    documented_count: int
    verified_count: int
    next_actions: List[str]


class ProcedureGenerateRequest(BaseModel):
    clause_id: int


class ProcedureResponse(BaseModel):
    id: int
    clause_number: str
    clause_title: str
    procedure_type: str
    title: str
    content: str
    version: int
    status: str
    created_at: str


class ProcedureUpdateRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None


class ClauseStatusUpdate(BaseModel):
    status: str = Field(..., description="not_started | in_progress | documented | verified | non_conforming")
    notes: Optional[str] = None


class AuditTrailItem(BaseModel):
    id: int
    event_type: str
    source_table: str
    source_id: int
    description: str
    occurred_at: str


class AuditReadiness(BaseModel):
    overall_score: float = Field(..., description="0-100 readiness percentage")
    clause_scores: Dict[str, float]
    gaps: List[str]


# ---------------------------------------------------------------------------
# Insert Cross-Reference (#21)
# ---------------------------------------------------------------------------

class InsertSpec(BaseModel):
    """Parsed ISO 1832 / ANSI designation."""
    shape: Optional[str] = None
    clearance_angle: Optional[str] = None
    tolerance_class: Optional[str] = None
    insert_type: Optional[str] = None
    ic_mm: Optional[float] = None
    thickness_mm: Optional[float] = None
    nose_radius_mm: Optional[float] = None
    chipbreaker: Optional[str] = None
    grade: Optional[str] = None
    raw_designation: str = ""


class InsertCreateRequest(BaseModel):
    manufacturer: str = Field(..., min_length=1)
    part_number: str = Field(..., min_length=1)
    iso_designation: Optional[str] = None
    ansi_designation: Optional[str] = None
    insert_type: Optional[str] = None
    grade: Optional[str] = None
    coating: Optional[str] = None
    geometry: Dict[str, Any] = Field(default_factory=dict)
    unit_cost_usd: Optional[float] = Field(None, ge=0)


class InsertResponse(BaseModel):
    id: int
    manufacturer: str
    part_number: str
    iso_designation: Optional[str] = None
    ansi_designation: Optional[str] = None
    insert_type: Optional[str] = None
    grade: Optional[str] = None
    coating: Optional[str] = None
    geometry: Dict[str, Any]
    unit_cost_usd: Optional[float] = None
    equivalents: List[int]
    created_at: str


class EquivalentInsert(BaseModel):
    id: int
    manufacturer: str
    part_number: str
    iso_designation: Optional[str] = None
    unit_cost_usd: Optional[float] = None
    cost_savings_pct: Optional[float] = None
    wear_validated: bool = False


class CostReport(BaseModel):
    current_monthly_spend: float
    optimized_monthly_spend: float
    savings_usd: float
    savings_pct: float
    recommendations: List[Dict[str, Any]]


class WearComparison(BaseModel):
    original_insert_id: int
    candidate_insert_id: int
    original_avg_wear_rate: Optional[float] = None
    candidate_avg_wear_rate: Optional[float] = None
    equivalent: Optional[bool] = None
    confidence: float = 0.0
    data_points: int = 0


# ---------------------------------------------------------------------------
# Tool Presetter (#8)
# ---------------------------------------------------------------------------

class PresetMeasurementRequest(BaseModel):
    tool_id: str = Field(..., description="MillForge tool_id to link measurement to")
    measured_length_mm: float = Field(..., gt=0)
    measured_diameter_mm: float = Field(..., gt=0)
    image_path: Optional[str] = None


class PresetMeasurementResponse(BaseModel):
    id: int
    tool_id: str
    measured_length_mm: float
    measured_diameter_mm: float
    measured_at: str
    tool_record_updated: bool = False


class PresetCalibrationRequest(BaseModel):
    standard_length_mm: float = Field(..., gt=0)
    standard_diameter_mm: float = Field(..., gt=0)
    measured_length_mm: float = Field(..., gt=0)
    measured_diameter_mm: float = Field(..., gt=0)
    camera_serial: Optional[str] = None
