"""
/api/jobs — ARIA CAM import, job lifecycle management, QC inspection stage.

Schema versioning: SUPPORTED_CAM_SCHEMA_VERSIONS gates import-from-cam.
Deploy MillForge first when bumping versions (ARIA old output still accepted).
"""

import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import Job, QCResult, User
from auth.dependencies import get_current_user
from models.schemas import (
    CAMImport,
    JobCreate,
    JobResponse,
    JobPatch,
    JobListResponse,
    QCResultResponse,
)
from services.aria_schema import normalize, UnsupportedAriaSchemaVersion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

VALID_STAGES = {"queued", "in_progress", "qc_pending", "complete", "qc_failed"}


def _push_aria_feedback_if_applicable(
    db: Session, job: Job, qc_result: dict | None = None
) -> None:
    """Auto-post feedback to ARIA bridge for ARIA-sourced jobs on completion.

    Called from QC submission and manual stage transitions. Non-fatal — logs
    warnings on failure so normal job flow is never interrupted.
    """
    meta = job.cam_metadata or {}
    aria_job_id = meta.get("aria_job_id")
    if not aria_job_id:
        return  # not an ARIA-sourced job

    # Avoid duplicate feedback
    if meta.get("aria_feedback"):
        return

    try:
        from sqlalchemy import func

        feedback_record = {
            "actual_cycle_time_minutes": job.estimated_duration_minutes,
            "qc_passed": job.stage == "complete",
            "defects_found": [],
            "defect_confidence_scores": [],
            "feedback_notes": f"Auto-feedback: job reached stage '{job.stage}'",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }

        # Enrich with QC data if available
        if qc_result:
            feedback_record["qc_passed"] = qc_result.get("passed", False)
            feedback_record["defects_found"] = qc_result.get("defects_found", [])
            feedback_record["defect_confidence_scores"] = qc_result.get(
                "confidence_scores", []
            )
        else:
            qr = db.query(QCResult).filter(QCResult.job_id == job.id).first()
            if qr:
                try:
                    feedback_record["defects_found"] = json.loads(
                        qr.defects_found_json or "[]"
                    )
                    feedback_record["defect_confidence_scores"] = json.loads(
                        qr.confidence_scores_json or "[]"
                    )
                    feedback_record["qc_passed"] = getattr(qr, "passed", True)
                except Exception:
                    pass

        # Compute accuracy vs estimate
        estimated = meta.get("simulation_results", {}).get(
            "estimated_cycle_time_minutes"
        )
        if estimated and feedback_record["actual_cycle_time_minutes"]:
            feedback_record["cycle_time_delta_minutes"] = (
                estimated - feedback_record["actual_cycle_time_minutes"]
            )
            feedback_record["cycle_time_accuracy_pct"] = round(
                feedback_record["actual_cycle_time_minutes"] / estimated * 100, 1
            )

        # Store on job's cam_metadata
        updated_meta = dict(meta)
        updated_meta["aria_feedback"] = feedback_record
        job.cam_metadata = updated_meta
        db.commit()

        logger.info(
            "ARIA auto-feedback stored: job #%d aria_job_id='%s' stage=%s qc_passed=%s",
            job.id, aria_job_id, job.stage, feedback_record.get("qc_passed"),
        )

        # Auto-triage QC failures on ARIA jobs
        if not feedback_record.get("qc_passed", True):
            _auto_triage_qc_failure(
                db, job, aria_job_id,
                feedback_record.get("defects_found", []),
                meta,
            )

        # Auto-populate a JobFeedbackRecord so ARIA jobs feed the ML predictor
        _auto_log_feedback_record(db, job, meta, feedback_record)

        # Fire-and-forget: push QC feedback to ARIA's memory endpoint
        _push_to_aria_memory(
            aria_job_id=aria_job_id,
            part_type=meta.get("extra", {}).get("part_type", "") if isinstance(meta.get("extra"), dict) else "",
            material=job.material or "",
            defects=feedback_record.get("defects_found", []),
            qc_passed=feedback_record.get("qc_passed", True),
        )

        try:
            from services.pipeline_events import emit as _emit_pipeline
            _emit_pipeline(
                "millforge→aria",
                "auto_feedback_stored",
                job_id=str(job.id),
                trace_id=meta.get("extra", {}).get("trace_id") if isinstance(meta.get("extra"), dict) else None,
                extra={
                    "aria_job_id": aria_job_id,
                    "stage": job.stage,
                    "qc_passed": feedback_record.get("qc_passed"),
                    "accuracy_pct": feedback_record.get("cycle_time_accuracy_pct"),
                },
            )
        except Exception:
            pass
    except Exception as exc:
        logger.warning("ARIA auto-feedback failed for job #%d: %s", job.id, exc)

def _auto_log_feedback_record(
    db: Session, job: "Job", meta: dict, feedback_record: dict
) -> None:
    """Auto-create a JobFeedbackRecord from a completed ARIA job.

    Called after ARIA feedback is stored so every completed ARIA job
    generates a training row for the ML predictor without operator input.
    Non-fatal — any failure is logged and swallowed.
    """
    try:
        from agents.feedback_logger import FeedbackLogger
        from agents.scheduler import SETUP_MATRIX, BASE_SETUP_MINUTES

        cycle = feedback_record.get("actual_cycle_time_minutes") or job.estimated_duration_minutes or 0.0
        material = job.material or "steel"

        # Predicted setup from SETUP_MATRIX (same-material changeover)
        predicted_setup = float(
            SETUP_MATRIX.get((material.lower(), material.lower()), BASE_SETUP_MINUTES)
        )
        actual_setup = round(cycle * 0.2, 2)
        predicted_processing = round((job.estimated_duration_minutes or cycle) * 0.8, 2)
        actual_processing = round(cycle * 0.8, 2)

        sim_conf = None
        sim_results = meta.get("simulation_results") or {}
        if isinstance(sim_results, dict):
            sim_conf = sim_results.get("simulation_confidence")

        tolerance = meta.get("tolerance_class") or "standard"

        FeedbackLogger().log(
            db,
            order_id=str(job.id),
            material=material,
            machine_id=job.machine_id or 1,
            predicted_setup_minutes=predicted_setup,
            actual_setup_minutes=actual_setup,
            predicted_processing_minutes=predicted_processing,
            actual_processing_minutes=actual_processing,
            provenance="mtconnect_auto",
            simulation_confidence=sim_conf,
            tolerance_class=tolerance,
        )
    except Exception as exc:
        logger.warning("_auto_log_feedback_record failed for job #%d: %s", job.id, exc)


# Surface defect class names from NEU-DET — trigger rework on the part.
# Anything not in this set is treated as a geometry/dimensional failure → regen.
_SURFACE_DEFECTS = {
    "scratches", "patches", "inclusions", "pitted_surface", "crazing", "rolled-in_scale",
}


def _auto_triage_qc_failure(
    db: Session, job: Job, aria_job_id: str, defects: list[str], meta: dict
) -> None:
    """Classify QC failure and respond automatically.

    Surface defects → create a rework Job at priority 1.
    Geometry/dimensional failures → mark regen_needed on cam_metadata so
    the operator (or a future automation) knows to re-run ARIA.
    """
    defects_lc = {d.lower() for d in defects}
    surface_hits = defects_lc & _SURFACE_DEFECTS
    geo_hits = defects_lc - _SURFACE_DEFECTS

    if surface_hits:
        # Create a rework job automatically
        try:
            rework_job = Job(
                title=f"[Rework] {job.title}",
                stage="queued",
                source="aria_rework",
                material=job.material,
                required_machine_type=job.required_machine_type,
                estimated_duration_minutes=(job.estimated_duration_minutes or 30) * 1.3,
                notes=(
                    f"Auto-rework from ARIA job #{job.id} aria_job_id={aria_job_id}. "
                    f"Surface defects: {', '.join(sorted(surface_hits))}"
                ),
                cam_metadata={
                    "source": "aria_rework",
                    "original_job_id": job.id,
                    "aria_job_id": aria_job_id,
                    "defects_found": list(defects),
                    "rework_reason": "surface_defects",
                },
            )
            db.add(rework_job)
            db.commit()
            logger.info(
                "Auto-rework job #%d created for ARIA job #%d defects=%s",
                rework_job.id, job.id, sorted(surface_hits),
            )
        except Exception as exc:
            logger.warning("Failed to create rework job for ARIA job #%d: %s", job.id, exc)

    if geo_hits or not defects:
        # Flag for geometry regen
        try:
            updated_meta = dict(meta)
            updated_meta["regen_needed"] = True
            updated_meta["regen_reason"] = (
                f"geometry_defects: {', '.join(sorted(geo_hits))}" if geo_hits
                else "qc_failed_no_defect_detail"
            )
            job.cam_metadata = updated_meta
            db.commit()
            logger.info(
                "ARIA regen flagged for job #%d aria_job_id=%s reason=%s",
                job.id, aria_job_id, updated_meta["regen_reason"],
            )
        except Exception as exc:
            logger.warning("Failed to flag regen for job #%d: %s", job.id, exc)


def _push_to_aria_memory(
    aria_job_id: str, part_type: str, material: str,
    defects: list[str], qc_passed: bool,
) -> None:
    """Fire-and-forget HTTP POST to ARIA's /api/memory/qc-feedback endpoint.

    Non-blocking — runs in a thread. Silently skips if ARIA_API_BASE not set.
    """
    aria_base = os.getenv("ARIA_API_BASE", "").rstrip("/")
    if not aria_base:
        return

    import threading, urllib.request

    def _post():
        try:
            payload = json.dumps({
                "aria_job_id": aria_job_id,
                "part_type": part_type,
                "material": material,
                "defects_found": defects,
                "qc_passed": qc_passed,
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{aria_base}/api/memory/qc-feedback",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as exc:
            logger.debug("ARIA memory push failed (non-fatal): %s", exc)

    threading.Thread(target=_post, daemon=True).start()


# Max upload size for QC images: 10 MB
_MAX_IMAGE_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _to_response(job: Job) -> JobResponse:
    return JobResponse(
        id=job.id,
        title=job.title,
        stage=job.stage,
        source=job.source,
        material=job.material,
        required_machine_type=job.required_machine_type,
        estimated_duration_minutes=job.estimated_duration_minutes,
        notes=job.notes,
        cam_metadata=job.cam_metadata,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _qc_to_response(qr: QCResult) -> QCResultResponse:
    return QCResultResponse(
        id=qr.id,
        job_id=qr.job_id,
        defects_found=qr.defects_found,
        confidence_scores=qr.confidence_scores,
        passed=qr.passed,
        image_path=qr.image_path,
        created_at=qr.created_at,
    )


# ---------------------------------------------------------------------------
# POST /api/jobs — manual job creation
# ---------------------------------------------------------------------------

@router.post("", response_model=JobResponse, status_code=201)
def create_job(
    req: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> JobResponse:
    """Create a manually-entered job (not from CAM)."""
    job = Job(
        title=req.title,
        stage="queued",
        source="manual",
        material=req.material,
        required_machine_type=req.required_machine_type,
        estimated_duration_minutes=req.estimated_duration_minutes,
        notes=req.notes,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(f"Manual job created: {job.id} '{job.title}' by user={user.email}")
    return _to_response(job)


# ---------------------------------------------------------------------------
# POST /api/jobs/import-from-cam
# ---------------------------------------------------------------------------

@router.post("/import-from-cam", response_model=JobResponse, status_code=201)
async def import_from_cam(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Consume an ARIA-OS CAM setup sheet and create a Job record.

    Dispatches through the ARIA schema normalizer registry in
    services/aria_schema.py — no hardcoded version list here.
    To support a new ARIA schema version, add a normalizer there and
    deploy MillForge before rolling out the new ARIA version.
    """
    raw = await request.json()

    try:
        normalized = normalize(raw)
    except UnsupportedAriaSchemaVersion as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        payload = CAMImport(**normalized)
    except Exception as exc:
        raise HTTPException(
            status_code=422,
            detail=f"ARIA payload failed validation after normalisation: {exc}",
        )

    title = f"{payload.part_id} — {payload.machine_name}"
    job = Job(
        title=title,
        stage="queued",
        source="aria_cam",
        material=payload.material,
        required_machine_type=payload.machine_name,
        estimated_duration_minutes=payload.cycle_time_min_estimate,
        notes=payload.notes,
        cam_metadata=normalized,
        created_by_id=user.id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    logger.info(
        "CAM import: job_id=%d part_id=%s version=%s user=%d",
        job.id, payload.part_id, raw.get("schema_version"), user.id,
    )
    return _to_response(job)


# ---------------------------------------------------------------------------
# GET /api/jobs
# ---------------------------------------------------------------------------

@router.get("", response_model=JobListResponse)
def list_jobs(
    stage: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    q = db.query(Job).filter(Job.created_by_id == user.id)
    if stage:
        q = q.filter(Job.stage == stage)
    if source:
        q = q.filter(Job.source == source)
    total = q.count()
    jobs = q.order_by(Job.created_at.desc()).offset(skip).limit(limit).all()
    return JobListResponse(total=total, jobs=[_to_response(j) for j in jobs])


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.get("/{job_id}", response_model=JobResponse)
def get_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return _to_response(job)


# ---------------------------------------------------------------------------
# PATCH /api/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.patch("/{job_id}", response_model=JobResponse)
def patch_job(
    job_id: int,
    patch: JobPatch,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    old_stage = job.stage
    if patch.stage is not None:
        if patch.stage not in VALID_STAGES:
            raise HTTPException(400, f"Invalid stage. Valid: {sorted(VALID_STAGES)}")
        job.stage = patch.stage
    if patch.notes is not None:
        job.notes = patch.notes
    if patch.required_machine_type is not None:
        job.required_machine_type = patch.required_machine_type
    db.commit()
    db.refresh(job)

    # Auto-push feedback on terminal stage transitions from ARIA jobs
    if patch.stage is not None and patch.stage in ("complete", "qc_failed") and patch.stage != old_stage:
        _push_aria_feedback_if_applicable(db, job)

    return _to_response(job)


# ---------------------------------------------------------------------------
# DELETE /api/jobs/{job_id}
# ---------------------------------------------------------------------------

@router.delete("/{job_id}", status_code=204)
def delete_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    db.delete(job)
    db.commit()


# ---------------------------------------------------------------------------
# POST /api/jobs/{job_id}/qc-submit
# ---------------------------------------------------------------------------

@router.post("/{job_id}/qc-submit", response_model=QCResultResponse, status_code=201)
async def qc_submit(
    job_id: int,
    image: UploadFile = File(..., description="Surface image for defect detection"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Submit a surface image for ONNX defect detection.
    Job must be in 'qc_pending' stage (or 'in_progress').
    Updates job stage to 'complete' or 'qc_failed' based on result.
    """
    job = db.query(Job).filter(Job.id == job_id, Job.created_by_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    if job.stage not in ("qc_pending", "in_progress"):
        raise HTTPException(400, f"Job is in stage '{job.stage}'. QC submit requires qc_pending or in_progress.")

    image_bytes = await image.read()
    if len(image_bytes) == 0:
        raise HTTPException(400, "Empty image file")
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(413, "Image exceeds 10 MB limit")

    from services.qc_inference import run_inference
    result = run_inference(image_bytes)

    # Save image to disk alongside the model directory (optional path)
    image_path: Optional[str] = None
    try:
        upload_dir = os.path.join(os.path.dirname(__file__), "..", "uploads", "qc")
        os.makedirs(upload_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        fname = f"job{job_id}_{ts}_{image.filename or 'image'}"
        full_path = os.path.join(upload_dir, fname)
        with open(full_path, "wb") as f:
            f.write(image_bytes)
        image_path = f"uploads/qc/{fname}"
    except Exception as exc:
        logger.warning("Failed to save QC image: %s", exc)

    qr = QCResult(
        job_id=job_id,
        defects_found_json=json.dumps(result["defects_found"]),
        confidence_scores_json=json.dumps(result["confidence_scores"]),
        passed=result["passed"],
        image_path=image_path,
    )
    db.add(qr)

    # Advance job stage
    job.stage = "complete" if result["passed"] else "qc_failed"
    db.commit()
    db.refresh(qr)
    logger.info(
        "QC submit: job_id=%d passed=%s defects=%s model_status=%s",
        job_id, result["passed"], result["defects_found"], result["status"],
    )

    # Auto-push feedback to ARIA bridge if this is an ARIA-sourced job
    _push_aria_feedback_if_applicable(db, job, result)

    return _qc_to_response(qr)


# ---------------------------------------------------------------------------
# GET /api/jobs/{job_id}/qc-results
# ---------------------------------------------------------------------------

@router.get("/{job_id}/qc-results", response_model=List[QCResultResponse])
def get_qc_results(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    job = db.query(Job).filter(Job.id == job_id, Job.created_by_id == user.id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    results = db.query(QCResult).filter(QCResult.job_id == job_id).order_by(QCResult.created_at.desc()).all()
    return [_qc_to_response(r) for r in results]
