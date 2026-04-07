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

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from db_models import Job, QCResult

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
    extra: dict[str, Any] = {}


class _FeedbackRequest(BaseModel):
    aria_job_id: str
    actual_cycle_time_minutes: Optional[float] = None
    qc_passed: Optional[bool] = None
    defects_found: list[str] = []
    defect_confidence_scores: list[float] = []
    feedback_notes: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_submission(payload: ARIAJobSubmission) -> list[str]:
    """Return a list of validation error strings (empty = valid)."""
    errors: list[str] = []

    if payload.schema_version not in {"1.0"}:
        errors.append(f"Unsupported schema_version '{payload.schema_version}'")

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


def _cam_metadata(payload: ARIAJobSubmission) -> dict:
    """Build the cam_metadata JSON blob stored on the Job row."""
    return {
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


# ---------------------------------------------------------------------------
# POST /api/jobs/from-aria
# ---------------------------------------------------------------------------

@router.post(
    "/api/jobs/from-aria",
    summary="Receive ARIA-OS job submission",
    description=(
        "Called by ARIA-OS after successful CAM generation + toolpath simulation. "
        "Validates the payload, creates a Job record in state 'queued', and "
        "returns an acknowledgement with the MillForge job ID so ARIA can poll status."
    ),
)
def submit_from_aria(
    payload: ARIAJobSubmission,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_bridge_key),
):
    errors = _validate_submission(payload)
    if errors:
        raise HTTPException(
            status_code=422,
            detail={"validation_errors": errors},
        )

    # Check for duplicate aria_job_id (idempotent — return existing job)
    existing = (
        db.query(Job)
        .filter(
            func.json_extract(Job.cam_metadata, "$.aria_job_id") == payload.aria_job_id
        )
        .first()
    )
    if existing:
        logger.info(
            "Duplicate aria_job_id='%s' — returning existing Job #%d",
            payload.aria_job_id,
            existing.id,
        )
        return _ack_response(existing, payload.aria_job_id, duplicate=True)

    # Default due date: estimated cycle time + 2-day buffer
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
        required_machine_type=_infer_machine_type(payload.required_operations),
        estimated_duration_minutes=payload.estimated_cycle_time_minutes,
        notes=(
            f"ARIA bridge | tol={payload.tolerance_class} | "
            f"ops={','.join(payload.required_operations)}"
        ),
        cam_metadata=_cam_metadata(payload),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    logger.info(
        "ARIA bridge: queued Job #%d for part='%s' aria_job_id='%s' material=%s est_min=%.1f",
        job.id,
        payload.part_name,
        payload.aria_job_id,
        payload.material,
        payload.estimated_cycle_time_minutes,
    )

    return _ack_response(job, payload.aria_job_id)


def _infer_machine_type(operations: list[str]) -> Optional[str]:
    """Map ARIA operation list to a MillForge machine type hint."""
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
    return {
        "aria_job_id": aria_job_id,
        "millforge_job_id": job.id,
        "status": "queued",
        "queue_position": None,   # scheduler determines position at run time
        "estimated_start_time": None,
        "rejection_reason": None,
        "duplicate": duplicate,
        "received_at": datetime.now(timezone.utc).isoformat(),
    }


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

    return {
        "aria_job_id": payload.aria_job_id,
        "millforge_job_id": job.id,
        "feedback_stored": True,
        "cycle_time_delta_minutes": delta,
        "cycle_time_accuracy_pct": accuracy_pct,
        "estimated_cycle_time_minutes": estimated,
    }


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
