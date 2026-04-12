"""
/api/jobs/from-aria   — receive ARIA-OS job submissions
/api/bridge/status/   — ARIA polls job status
/api/bridge/feedback  — MillForge pushes completion feedback back to ARIA

This is the core connection in Jonathan's thesis: autonomous geometry
generation (ARIA) feeds directly into autonomous production scheduling
(MillForge) — no human translates the CAM output into a job ticket.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from db_models import Job, Operation, FirstArticleInspection, QCResult, User
from auth.dependencies import get_current_user_optional
from services.pipeline_events import emit as _emit_event

logger = logging.getLogger(__name__)

router = APIRouter(tags=["ARIA Bridge"])

# Optional static API key — set ARIA_BRIDGE_KEY env var to require auth.
# Leave unset in dev to allow unauthenticated submissions.
_BRIDGE_KEY = os.getenv("ARIA_BRIDGE_KEY", "").strip()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

def _verify_bridge_key(x_api_key: Optional[str] = Header(None)) -> None:
    if not _BRIDGE_KEY:
        return  # key not configured → open
    if x_api_key != _BRIDGE_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


# ---------------------------------------------------------------------------
# Pydantic schemas (mirror ARIAToMillForgeJob — no external package dep)
# ---------------------------------------------------------------------------

class _MaterialSpec(BaseModel):
    material_name: str
    material_family: str
    hardness_hrc: Optional[float] = None
    tensile_strength_mpa: Optional[float] = None
    notes: Optional[str] = None


class _SimulationResults(BaseModel):
    estimated_cycle_time_minutes: float
    estimated_material_removal_cm3: Optional[float] = None
    max_chip_load_mm: Optional[float] = None
    tool_wear_index: Optional[float] = None
    collision_detected: bool = False
    simulation_confidence: float = Field(default=1.0, ge=0.0, le=1.0)


_SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)
_VALID_MATERIALS = {"steel", "aluminum", "titanium", "copper"}


class ARIAJobSubmission(BaseModel):
    """Pydantic mirror of ARIAToMillForgeJob (schema_version 1.0)."""
    schema_version: str = "1.0"
    aria_job_id: str
    part_name: str
    geometry_hash: str
    geometry_file: str
    toolpath_file: str
    material: str
    material_spec: _MaterialSpec
    required_operations: list[str] = []
    tolerance_class: str = "medium"
    simulation_results: _SimulationResults
    validation_passed: bool
    estimated_cycle_time_minutes: float
    quantity: int = Field(default=1, ge=1, le=100_000)
    priority: int = Field(default=5, ge=1, le=10)
    due_date: Optional[datetime] = None
    generated_at: Optional[datetime] = None
    structsight_context: Optional[dict[str, Any]] = None  # StructSight bridge (Step 4)
    extra: dict[str, Any] = {}


class _FeedbackRequest(BaseModel):
    aria_job_id: str
    actual_cycle_time_minutes: Optional[float] = None
    qc_passed: Optional[bool] = None
    defects_found: list[str] = []
    defect_confidence_scores: list[float] = []
    feedback_notes: Optional[str] = None


class ARIABundleSubmission(BaseModel):
    """Lightweight ARIA run bundle — submitted before CAM toolpath is available.

    Maps to a Job in stage 'pending_cam'.  Once CAM generation completes,
    ARIA upgrades the job via POST /api/jobs/from-aria using the same run_id
    in the extra field.
    """
    schema_version: str = "1.0"
    run_id: str                                         # ARIA run_id (timestamp + UUID)
    goal: str                                           # original natural-language goal
    part_name: str                                      # part_id / session_id from DesignState
    step_path: Optional[str] = None                    # absolute path on ARIA host
    stl_path: Optional[str] = None                     # absolute path on ARIA host
    geometry_hash: Optional[str] = None               # SHA-256 of STEP if computed
    material: Optional[str] = None                     # inferred from DFM; may be absent
    validation: Optional[dict[str, Any]] = None        # run_manifest.json validation block
    priority: int = Field(default=5, ge=1, le=10)
    notes: Optional[str] = None
    structsight_context: Optional[dict[str, Any]] = None  # StructSight bridge (Step 4)
    extra: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# V2 schemas — process-agnostic multi-operation handoff (schema_version 2.0)
# ---------------------------------------------------------------------------

class _BridgeMaterial(BaseModel):
    """Extended material spec for V2 — supports any manufacturing material."""
    material_name: str
    material_family: str  # aluminum | steel | titanium | copper | plastic | composite | other
    form: str = "bar"     # bar | sheet | tube | plate | casting | powder | other
    dimensions_mm: Optional[dict[str, float]] = None  # {"length": 100, "width": 50, "thickness": 6}
    hardness_hrc: Optional[float] = None
    tensile_strength_mpa: Optional[float] = None
    notes: Optional[str] = None


class _BridgeOperation(BaseModel):
    """Single manufacturing operation in a V2 multi-process job."""
    sequence: int = Field(..., ge=10)               # 10, 20, 30 … (multiples of 10)
    operation_name: str
    work_center_category: str                        # WorkCenter.category value (process-agnostic)
    estimated_setup_min: float = Field(default=30.0, ge=0)
    estimated_run_min: float = Field(default=60.0, ge=0)
    depends_on_sequence: Optional[int] = None        # parent sequence number
    inspection_required: bool = False
    is_subcontracted: bool = False
    subcontractor_name: Optional[str] = None
    subcontractor_lead_days: Optional[int] = None
    ai_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    detected_features: list[str] = []
    notes: Optional[str] = None


class _Manufacturability(BaseModel):
    """DFM analysis output from ARIA-OS."""
    overall_score: float = Field(default=1.0, ge=0.0, le=1.0)
    issues: list[str] = []
    recommendations: list[str] = []
    process_family: Optional[str] = None  # e.g. "cnc_milling", "sheet_metal"


class _QualityRequirements(BaseModel):
    """Quality and inspection requirements for a V2 job."""
    tolerance_class: str = "medium"          # tight | medium | loose
    surface_finish_ra: Optional[float] = None  # Ra in μm
    first_article_required: bool = False
    quality_standards: list[str] = []       # e.g. ["AS9100", "ISO 9001"]
    inspection_operations: list[int] = []   # sequence numbers that require inspection


class ARIAJobSubmissionV2(BaseModel):
    """ARIA-OS → MillForge handoff schema v2.0 — process-agnostic, multi-operation.

    Accepts any manufacturing process type via work_center_category on each
    operation, not just CNC ops.  Material spec is a full _BridgeMaterial
    object (not restricted to the V1 four-material allowlist).
    """
    schema_version: str = "2.0"
    aria_job_id: str
    part_name: str
    geometry_hash: str
    geometry_file: str
    toolpath_file: Optional[str] = None       # optional pre-CAM submissions
    material: _BridgeMaterial
    operations: list[_BridgeOperation] = Field(default_factory=list, min_length=1)
    manufacturability: Optional[_Manufacturability] = None
    quality: _QualityRequirements = Field(default_factory=_QualityRequirements)
    quantity: int = Field(default=1, ge=1, le=100_000)
    priority: int = Field(default=5, ge=1, le=10)
    due_date: Optional[datetime] = None
    generated_at: Optional[datetime] = None
    structsight_context: Optional[dict[str, Any]] = None
    extra: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_submission(payload: ARIAJobSubmission) -> list[str]:
    """Validate V1 submission. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not payload.aria_job_id.strip():
        errors.append("aria_job_id must not be empty")

    if not _SHA256_RE.match(payload.geometry_hash):
        errors.append("geometry_hash must be a 64-char hex SHA-256")

    if payload.material not in _VALID_MATERIALS:
        errors.append(
            f"material '{payload.material}' not supported. "
            f"Valid: {sorted(_VALID_MATERIALS)}"
        )

    if payload.simulation_results.collision_detected:
        errors.append(
            "simulation_results.collision_detected is True — fix toolpath before submitting"
        )

    if not payload.validation_passed:
        errors.append("validation_passed is False — ARIA pre-flight checks must pass before submission")

    if payload.estimated_cycle_time_minutes <= 0:
        errors.append("estimated_cycle_time_minutes must be > 0")

    return errors


def _validate_submission_v2(payload: ARIAJobSubmissionV2) -> list[str]:
    """Validate V2 submission. Returns list of error strings (empty = valid)."""
    errors: list[str] = []

    if not payload.aria_job_id.strip():
        errors.append("aria_job_id must not be empty")

    if not _SHA256_RE.match(payload.geometry_hash):
        errors.append("geometry_hash must be a 64-char hex SHA-256")

    if not payload.operations:
        errors.append("operations list must not be empty")

    # Detect circular / missing dependency references
    sequences = {op.sequence for op in payload.operations}
    for op in payload.operations:
        if op.depends_on_sequence is not None and op.depends_on_sequence not in sequences:
            errors.append(
                f"operation seq={op.sequence} depends_on_sequence={op.depends_on_sequence} "
                f"does not match any operation in this submission"
            )

    # Subcontract sanity
    for op in payload.operations:
        if op.is_subcontracted and not op.subcontractor_name:
            errors.append(
                f"operation seq={op.sequence} is_subcontracted=true but subcontractor_name is missing"
            )

    return errors


def _cam_metadata_v1(payload: ARIAJobSubmission) -> dict:
    """Build cam_metadata JSON for a V1 submission."""
    meta = {
        "source": "aria_bridge",
        "schema_version": payload.schema_version,
        "aria_job_id": payload.aria_job_id,
        "geometry_file": payload.geometry_file,
        "toolpath_file": payload.toolpath_file,
        "geometry_hash": payload.geometry_hash,
        "material_spec": payload.material_spec.model_dump(),
        "required_operations": payload.required_operations,
        "tolerance_class": payload.tolerance_class,
        "simulation_results": payload.simulation_results.model_dump(),
        "validation_passed": payload.validation_passed,
        "generated_at": payload.generated_at.isoformat() if payload.generated_at else None,
        "extra": payload.extra,
    }
    if payload.structsight_context:
        meta["structsight_context"] = payload.structsight_context
    return meta


def _cam_metadata_v2(payload: ARIAJobSubmissionV2) -> dict:
    """Build cam_metadata JSON for a V2 submission."""
    meta = {
        "source": "aria_bridge_v2",
        "schema_version": "2.0",
        "aria_job_id": payload.aria_job_id,
        "geometry_file": payload.geometry_file,
        "toolpath_file": payload.toolpath_file,
        "geometry_hash": payload.geometry_hash,
        "material": payload.material.model_dump(),
        "operations": [op.model_dump() for op in payload.operations],
        "manufacturability": payload.manufacturability.model_dump() if payload.manufacturability else None,
        "quality": payload.quality.model_dump(),
        "generated_at": payload.generated_at.isoformat() if payload.generated_at else None,
        "extra": payload.extra,
    }
    if payload.structsight_context:
        meta["structsight_context"] = payload.structsight_context
    return meta


_MATERIAL_FAMILY_MAP: dict[str, str] = {
    "aluminum": "aluminum", "aluminium": "aluminum",
    "steel": "steel", "stainless": "steel", "stainless_steel": "steel",
    "titanium": "titanium",
    "copper": "copper", "brass": "copper", "bronze": "copper",
}


def _material_family_to_code(family: str) -> Optional[str]:
    """Map V2 material_family to a V1-compatible scheduler material code."""
    return _MATERIAL_FAMILY_MAP.get(family.lower().strip())


# ---------------------------------------------------------------------------
# POST /api/jobs/from-aria  (versioned dispatcher)
# ---------------------------------------------------------------------------

@router.post(
    "/api/jobs/from-aria",
    summary="Receive ARIA-OS job submission (v1.0 and v2.0)",
    description=(
        "Called by ARIA-OS after successful CAM generation. Dispatches to the "
        "V1 or V2 handler based on schema_version in the request body. "
        "V2 supports multi-process operations and any work center type. "
        "Returns an acknowledgement with the MillForge job ID."
    ),
)
async def submit_from_aria(
    request: Request,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_bridge_key),
    user: Optional[User] = Depends(get_current_user_optional),
):
    try:
        raw = await request.json()
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid JSON body")

    version = raw.get("schema_version", "1.0")

    if version == "2.0":
        try:
            payload_v2 = ARIAJobSubmissionV2(**raw)
        except Exception as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        errors = _validate_submission_v2(payload_v2)
        if errors:
            raise HTTPException(status_code=422, detail={"validation_errors": errors})
        return _handle_v2(payload_v2, db, user)

    # Default: V1
    try:
        payload_v1 = ARIAJobSubmission(**raw)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if version not in {"1.0"}:
        raise HTTPException(
            status_code=422,
            detail={"validation_errors": [f"Unsupported schema_version '{version}'"]}
        )
    errors = _validate_submission(payload_v1)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    return _handle_v1(payload_v1, db, user)


def _handle_v1(
    payload: ARIAJobSubmission,
    db: Session,
    user: Optional[User],
) -> dict:
    """Create a Job from a V1 submission (backward-compatible path)."""
    # Idempotent: return existing job if aria_job_id already registered
    existing = (
        db.query(Job)
        .filter(func.json_extract(Job.cam_metadata, "$.aria_job_id") == payload.aria_job_id)
        .first()
    )
    if existing:
        if user and existing.created_by_id is None:
            existing.created_by_id = user.id
            db.commit()
            db.refresh(existing)
        logger.info(
            "Duplicate aria_job_id='%s' — returning existing Job #%d",
            payload.aria_job_id, existing.id,
        )
        return _ack_response(existing, payload.aria_job_id, duplicate=True)

    if payload.due_date:
        due = payload.due_date
    else:
        buffer_hours = max(payload.estimated_cycle_time_minutes / 60 * 1.5, 48)
        due = datetime.now(timezone.utc) + timedelta(hours=buffer_hours)

    job = Job(
        title=payload.part_name,
        stage="queued",
        source="aria_cam",
        material=payload.material,
        required_machine_type=_infer_machine_type(payload.required_operations, payload.extra),
        estimated_duration_minutes=payload.estimated_cycle_time_minutes,
        notes=(
            f"ARIA bridge | tol={payload.tolerance_class} | "
            f"ops={','.join(payload.required_operations)}"
        ),
        cam_metadata=_cam_metadata_v1(payload),
        created_by_id=user.id if user else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "ARIA bridge v1: queued Job #%d part='%s' aria_job_id='%s' material=%s est_min=%.1f",
        job.id, payload.part_name, payload.aria_job_id, payload.material,
        payload.estimated_cycle_time_minutes,
    )
    _emit_event(
        "aria→millforge", "job_received",
        job_id=str(job.id),
        trace_id=payload.extra.get("trace_id") if payload.extra else None,
        status_code=200,
        extra={"aria_job_id": payload.aria_job_id, "part_name": payload.part_name},
    )
    return _ack_response(job, payload.aria_job_id)


def _handle_v2(
    payload: ARIAJobSubmissionV2,
    db: Session,
    user: Optional[User],
) -> dict:
    """Create a Job + Operations from a V2 multi-process submission."""
    # Idempotent: return existing job if aria_job_id already registered
    existing = (
        db.query(Job)
        .filter(func.json_extract(Job.cam_metadata, "$.aria_job_id") == payload.aria_job_id)
        .first()
    )
    if existing:
        if user and existing.created_by_id is None:
            existing.created_by_id = user.id
            db.commit()
            db.refresh(existing)
        logger.info(
            "Duplicate aria_job_id='%s' (v2) — returning existing Job #%d",
            payload.aria_job_id, existing.id,
        )
        return _ack_response(existing, payload.aria_job_id, duplicate=True)

    material_code = _material_family_to_code(payload.material.material_family)
    total_min = sum(op.estimated_setup_min + op.estimated_run_min for op in payload.operations)

    if payload.due_date:
        due = payload.due_date
    else:
        buffer_hours = max(total_min / 60 * 1.5, 48)
        due = datetime.now(timezone.utc) + timedelta(hours=buffer_hours)

    # Primary operation (lowest sequence) drives the required_machine_type field
    primary_op = min(payload.operations, key=lambda o: o.sequence)
    machine_type = _infer_machine_type([], {"process_recommendation": primary_op.work_center_category})

    op_summary = ", ".join(
        f"seq{op.sequence}:{op.work_center_category}" for op in sorted(payload.operations, key=lambda o: o.sequence)
    )
    job = Job(
        title=payload.part_name,
        stage="queued",
        source="aria_cam",
        material=material_code,
        required_machine_type=machine_type,
        estimated_duration_minutes=total_min,
        notes=(
            f"ARIA bridge v2 | tol={payload.quality.tolerance_class} | "
            f"ops={len(payload.operations)} | {op_summary}"
        ),
        cam_metadata=_cam_metadata_v2(payload),
        created_by_id=user.id if user else None,
    )
    db.add(job)
    db.flush()  # assigns job.id without committing

    # Pass 1: create all Operation records, keyed by sequence number
    uid = (user.id if user else None) or 1  # bridge calls have no user — fall back to system
    op_by_seq: dict[int, Operation] = {}
    for op_data in sorted(payload.operations, key=lambda o: o.sequence):
        op_rec = Operation(
            user_id=uid,
            job_id=job.id,
            sequence_number=op_data.sequence,
            operation_name=op_data.operation_name,
            work_center_category=op_data.work_center_category,
            estimated_setup_min=op_data.estimated_setup_min,
            estimated_run_min=op_data.estimated_run_min,
            quantity=payload.quantity,
            status="pending",
            inspection_required=op_data.inspection_required,
            is_subcontracted=op_data.is_subcontracted,
            subcontractor_name=op_data.subcontractor_name,
            subcontractor_lead_days=op_data.subcontractor_lead_days,
            ai_confidence=op_data.ai_confidence,
            detected_features_json=json.dumps(op_data.detected_features),
            notes=op_data.notes,
        )
        db.add(op_rec)
        op_by_seq[op_data.sequence] = op_rec

    db.flush()  # assigns operation IDs

    # Pass 2: wire up depends_on_id now that all IDs are known
    for op_data in payload.operations:
        if op_data.depends_on_sequence is not None:
            dep = op_by_seq.get(op_data.depends_on_sequence)
            if dep:
                op_by_seq[op_data.sequence].depends_on_id = dep.id

    # Create First Article Inspection record if required
    if payload.quality.first_article_required:
        fai = FirstArticleInspection(
            user_id=uid,
            order_ref=None,
            part_name=payload.part_name,
            result="pass",   # placeholder — inspector fills in actuals
            measurements_json="[]",
            notes=f"FAI required — ARIA job {payload.aria_job_id}",
        )
        db.add(fai)

    db.commit()
    db.refresh(job)

    logger.info(
        "ARIA bridge v2: queued Job #%d part='%s' aria_job_id='%s' material=%s "
        "ops=%d total_min=%.1f fai=%s",
        job.id, payload.part_name, payload.aria_job_id, material_code,
        len(payload.operations), total_min, payload.quality.first_article_required,
    )
    _emit_event(
        "aria→millforge", "job_received_v2",
        job_id=str(job.id),
        trace_id=payload.extra.get("trace_id") if payload.extra else None,
        status_code=200,
        extra={
            "aria_job_id": payload.aria_job_id,
            "part_name": payload.part_name,
            "operation_count": len(payload.operations),
            "schema_version": "2.0",
        },
    )
    return _ack_response(job, payload.aria_job_id)


def _infer_machine_type(operations: list[str], extra: dict | None = None) -> Optional[str]:
    """Map ARIA operation list + DFM process recommendation to a MillForge machine type.

    Uses the DFM agent's process_recommendation from extra.process_recommendation
    when available, falling back to operation-based heuristics.
    """
    # Check for DFM process recommendation first
    if extra:
        process_rec = (extra.get("process_recommendation") or "").lower()
        _PROCESS_TO_MACHINE = {
            "cnc_milling": "cnc_mill", "milling": "cnc_mill",
            "turning": "lathe", "cnc_turning": "lathe",
            "grinding": "grinder",
            "sheet_metal": "press_brake", "bending": "press_brake",
            "welding": "welding_cell", "welding_arc": "welding_cell",
            "cutting_laser": "laser_cutter", "laser": "laser_cutter",
            "cutting_plasma": "plasma_cutter",
            "cutting_waterjet": "waterjet",
            "stamping": "stamping_press",
            "edm": "edm", "wire_edm": "edm",
            "injection_molding": "injection_molder",
            "inspection": "cmm",
        }
        if process_rec in _PROCESS_TO_MACHINE:
            return _PROCESS_TO_MACHINE[process_rec]

    ops_lower = {op.lower() for op in operations}
    if ops_lower & {"turning", "boring", "reaming"}:
        return "lathe"
    if ops_lower & {"grinding"}:
        return "grinder"
    if ops_lower & {"inspection"}:
        return "cmm"
    if ops_lower:  # milling, drilling, tapping, etc.
        return "cnc_mill"
    return None


def _ack_response(job: Job, aria_job_id: str, *, duplicate: bool = False) -> dict:
    trace_id = (job.cam_metadata or {}).get("extra", {}).get("trace_id", aria_job_id)
    return {
        "aria_job_id": aria_job_id,
        "trace_id": trace_id,
        "millforge_job_id": job.id,
        "status": "queued",
        "queue_position": None,   # scheduler determines position at run time
        "estimated_start_time": None,
        "rejection_reason": None,
        "duplicate": duplicate,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


def _bundle_ack(job: Job, aria_run_id: str, *, duplicate: bool = False) -> dict:
    return {
        "aria_run_id": aria_run_id,
        "millforge_job_id": job.id,
        "status": job.stage,
        "duplicate": duplicate,
        "received_at": datetime.now(timezone.utc).isoformat(),
        "next_step": f"POST /api/jobs/from-aria with extra.aria_run_id={aria_run_id} when CAM is ready",
    }


# ---------------------------------------------------------------------------
# POST /api/aria/bundle
# ---------------------------------------------------------------------------

@router.post(
    "/api/aria/bundle",
    summary="Ingest an ARIA run bundle (pre-CAM)",
    description=(
        "Called by ARIA-OS after a successful geometry + DFM run, before CAM "
        "toolpath generation. Creates a Job in stage 'pending_cam' so MillForge "
        "can track the part immediately. Idempotent on run_id — re-submitting "
        "returns the existing job. Accepts optional structsight_context for "
        "structural engineering handoff context."
    ),
)
def submit_aria_bundle(
    payload: ARIABundleSubmission,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_bridge_key),
    user: Optional[User] = Depends(get_current_user_optional),
):
    if not payload.run_id.strip():
        raise HTTPException(status_code=422, detail="run_id must not be empty")
    if not payload.part_name.strip():
        raise HTTPException(status_code=422, detail="part_name must not be empty")

    # Idempotent: return existing job if run_id already registered
    existing = (
        db.query(Job)
        .filter(func.json_extract(Job.cam_metadata, "$.aria_run_id") == payload.run_id)
        .first()
    )
    if existing:
        if user and existing.created_by_id is None:
            existing.created_by_id = user.id
            db.commit()
            db.refresh(existing)
        logger.info(
            "Duplicate aria_run_id='%s' — returning existing Job #%d",
            payload.run_id,
            existing.id,
        )
        return _bundle_ack(existing, payload.run_id, duplicate=True)

    # Infer machine type from DFM process recommendation in validation block
    validation = payload.validation or {}
    dfm_process = (validation.get("dfm_process") or "").lower().strip()
    machine_type = _infer_machine_type(
        [],
        {"process_recommendation": dfm_process} if dfm_process else None,
    )

    material = (payload.material or "").strip() or None

    cam_meta: dict[str, Any] = {
        "source": "aria_bundle",
        "schema_version": payload.schema_version,
        "aria_run_id": payload.run_id,
        "goal": payload.goal,
        "step_path": payload.step_path,
        "stl_path": payload.stl_path,
        "geometry_hash": payload.geometry_hash,
        "validation": validation,
        "extra": payload.extra,
    }
    if payload.structsight_context:
        cam_meta["structsight_context"] = payload.structsight_context

    notes_parts = [payload.notes or "", f"ARIA bundle run_id={payload.run_id}",
                   f"dfm={dfm_process or 'unknown'}"]
    job = Job(
        title=payload.part_name,
        stage="pending_cam",
        source="aria_bundle",
        material=material,
        required_machine_type=machine_type,
        notes=" | ".join(p for p in notes_parts if p),
        cam_metadata=cam_meta,
        created_by_id=user.id if user else None,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "ARIA bundle: pending_cam Job #%d part='%s' run_id='%s' dfm=%s machine=%s",
        job.id,
        payload.part_name,
        payload.run_id,
        dfm_process or "unknown",
        machine_type,
    )
    _emit_event(
        "aria->millforge",
        "bundle_received",
        job_id=str(job.id),
        trace_id=payload.run_id,
        status_code=200,
        extra={"aria_run_id": payload.run_id, "part_name": payload.part_name},
    )

    return _bundle_ack(job, payload.run_id)


# ---------------------------------------------------------------------------
# GET /api/bridge/status/{aria_job_id}
# ---------------------------------------------------------------------------

@router.get(
    "/api/bridge/status/{aria_job_id}",
    summary="Poll job status by ARIA job ID",
    description=(
        "ARIA polls this endpoint after submission to track job progress "
        "through MillForge's pipeline: queued → in_progress → qc_pending → complete."
    ),
)
def get_bridge_status(
    aria_job_id: str,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_bridge_key),
):
    job = (
        db.query(Job)
        .filter(
            func.json_extract(Job.cam_metadata, "$.aria_job_id") == aria_job_id
        )
        .first()
    )
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"No MillForge job found for aria_job_id='{aria_job_id}'",
        )

    # Derive QC result summary if available
    qc_summary = _qc_summary(db, job)

    return {
        "aria_job_id": aria_job_id,
        "millforge_job_id": job.id,
        "part_name": job.title,
        "stage": job.stage,
        "material": job.material,
        "estimated_duration_minutes": job.estimated_duration_minutes,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "qc": qc_summary,
    }


def _qc_summary(db: Session, job: Job) -> Optional[dict]:
    result = db.query(QCResult).filter(QCResult.job_id == job.id).first()
    if not result:
        return None
    try:
        defects = json.loads(result.defects_found_json)
        scores = json.loads(result.confidence_scores_json)
    except (json.JSONDecodeError, AttributeError):
        defects, scores = [], []
    return {
        "passed": result.passed if hasattr(result, "passed") else len(defects) == 0,
        "defects_found": defects,
        "confidence_scores": scores,
        "inspected_at": result.created_at.isoformat() if hasattr(result, "created_at") else None,
    }


# ---------------------------------------------------------------------------
# POST /api/bridge/feedback
# ---------------------------------------------------------------------------

@router.post(
    "/api/bridge/feedback",
    summary="Receive post-completion feedback for ARIA learning loop",
    description=(
        "MillForge pushes actual cycle times and QC results back to ARIA "
        "after a job completes. ARIA uses this to calibrate future simulations. "
        "Can also be called by ARIA to retrieve feedback by aria_job_id."
    ),
)
def push_feedback(
    payload: _FeedbackRequest,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_bridge_key),
):
    """
    Store feedback on the Job's cam_metadata and return a summary.

    This endpoint is symmetric — it can be called by MillForge internally
    when a job completes, or polled by ARIA to get its own feedback record.
    """
    job = (
        db.query(Job)
        .filter(
            func.json_extract(Job.cam_metadata, "$.aria_job_id") == payload.aria_job_id
        )
        .first()
    )
    if not job:
        raise HTTPException(
            status_code=404,
            detail=f"No MillForge job for aria_job_id='{payload.aria_job_id}'",
        )

    # Compute delta vs ARIA's estimate
    estimated = (job.cam_metadata or {}).get("simulation_results", {}).get(
        "estimated_cycle_time_minutes"
    )
    delta: Optional[float] = None
    accuracy_pct: Optional[float] = None
    if estimated and payload.actual_cycle_time_minutes:
        delta = estimated - payload.actual_cycle_time_minutes
        accuracy_pct = round(
            payload.actual_cycle_time_minutes / estimated * 100, 1
        )

    feedback_record = {
        "actual_cycle_time_minutes": payload.actual_cycle_time_minutes,
        "cycle_time_delta_minutes": delta,
        "cycle_time_accuracy_pct": accuracy_pct,
        "qc_passed": payload.qc_passed,
        "defects_found": payload.defects_found,
        "defect_confidence_scores": payload.defect_confidence_scores,
        "feedback_notes": payload.feedback_notes,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    # Merge into cam_metadata without losing existing fields
    meta = dict(job.cam_metadata or {})
    meta["aria_feedback"] = feedback_record
    job.cam_metadata = meta
    db.commit()

    logger.info(
        "ARIA feedback stored: job #%d aria_job_id='%s' "
        "actual_min=%s delta=%s accuracy_pct=%s qc_passed=%s",
        job.id,
        payload.aria_job_id,
        payload.actual_cycle_time_minutes,
        delta,
        accuracy_pct,
        payload.qc_passed,
    )
    _emit_event(
        "millforge→aria",
        "feedback_stored",
        job_id=str(job.id),
        trace_id=(job.cam_metadata or {}).get("extra", {}).get("trace_id"),
        extra={
            "aria_job_id": payload.aria_job_id,
            "qc_passed": payload.qc_passed,
            "accuracy_pct": accuracy_pct,
        },
    )

    return {
        "aria_job_id": payload.aria_job_id,
        "millforge_job_id": job.id,
        "feedback_stored": True,
        "cycle_time_delta_minutes": delta,
        "cycle_time_accuracy_pct": accuracy_pct,
        "estimated_cycle_time_minutes": estimated,
    }


# ---------------------------------------------------------------------------
# GET /api/bridge/progress/{aria_job_id}  — Server-Sent Events
# ---------------------------------------------------------------------------

@router.get(
    "/api/bridge/progress/{aria_job_id}",
    summary="Stream live job progress as Server-Sent Events",
    description=(
        "Subscribe to job stage transitions for a specific ARIA job. "
        "Emits an event on each stage change (queued→in_progress→qc_pending→complete/qc_failed). "
        "Closes automatically on terminal stage or after 5-minute timeout."
    ),
)
async def stream_job_progress(
    aria_job_id: str,
    _auth: None = Depends(_verify_bridge_key),
):
    import asyncio as _asyncio

    async def _generator():
        from database import SessionLocal as _SessionLocal
        last_stage: str | None = None
        elapsed = 0
        not_found_ticks = 0
        POLL_S = 2
        TIMEOUT_S = 300

        while elapsed < TIMEOUT_S:
            db = _SessionLocal()
            try:
                job = (
                    db.query(Job)
                    .filter(func.json_extract(Job.cam_metadata, "$.aria_job_id") == aria_job_id)
                    .first()
                )
                if not job:
                    not_found_ticks += 1
                    if not_found_ticks > 5:  # 10 seconds of not found
                        yield f'data: {json.dumps({"stage": "not_found", "aria_job_id": aria_job_id})}\n\n'
                        return
                else:
                    if job.stage != last_stage:
                        last_stage = job.stage
                        event: dict = {
                            "stage": job.stage,
                            "aria_job_id": aria_job_id,
                            "millforge_job_id": job.id,
                            "part_name": job.title,
                            "elapsed_s": elapsed,
                        }
                        if job.stage in ("complete", "qc_failed"):
                            qc = _qc_summary(db, job)
                            if qc:
                                event["qc"] = qc
                            yield f'data: {json.dumps(event)}\n\n'
                            return  # terminal — close stream
                        yield f'data: {json.dumps(event)}\n\n'
            finally:
                db.close()

            await _asyncio.sleep(POLL_S)
            elapsed += POLL_S

        yield f'data: {json.dumps({"stage": "timeout", "aria_job_id": aria_job_id, "elapsed_s": elapsed})}\n\n'

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# GET /api/bridge/feedback/{aria_job_id}
# ---------------------------------------------------------------------------

@router.get(
    "/api/bridge/feedback/{aria_job_id}",
    summary="Retrieve feedback record for a completed ARIA job",
    description=(
        "ARIA calls this to read back the feedback MillForge stored after "
        "job completion. Returns 404 if the job hasn't completed yet."
    ),
)
def get_feedback(
    aria_job_id: str,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_bridge_key),
):
    job = (
        db.query(Job)
        .filter(
            func.json_extract(Job.cam_metadata, "$.aria_job_id") == aria_job_id
        )
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail=f"aria_job_id='{aria_job_id}' not found")

    feedback = (job.cam_metadata or {}).get("aria_feedback")
    if not feedback:
        raise HTTPException(
            status_code=404,
            detail=f"No feedback yet for aria_job_id='{aria_job_id}' (stage={job.stage})",
        )

    return {
        "aria_job_id": aria_job_id,
        "millforge_job_id": job.id,
        "part_name": job.title,
        "stage": job.stage,
        "feedback": feedback,
    }
