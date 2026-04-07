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
    JobResponse,
    JobPatch,
    JobListResponse,
    QCResultResponse,
)
from services.aria_schema import normalize, UnsupportedAriaSchemaVersion

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])

VALID_STAGES = {"queued", "in_progress", "qc_pending", "complete", "qc_failed"}

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
