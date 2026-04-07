"""
MTR Reader router — upload, extract, verify, and manage Mill Test Reports.

Prefix: /api/quality/mtr
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

from database import get_db
from db_models import MaterialCert, Job, AS9100AuditTrail, AS9100ComplianceStatus
from agents.mtr_reader import MTRReaderAgent
from models.quality_models import (
    MTRUploadResponse, MTRVerifyRequest, MTRVerifyResponse,
    MTRListItem, MTRLinkJobRequest, PropertyCheck,
)

logger = logging.getLogger("millforge.mtr_router")

router = APIRouter(prefix="/api/quality/mtr", tags=["Quality — MTR Reader"])

_agent = MTRReaderAgent()


def _as9100_enabled(db: Session, user_id: int) -> bool:
    """Check if user has AS9100 initialized."""
    return db.query(AS9100ComplianceStatus).filter(
        AS9100ComplianceStatus.user_id == user_id
    ).first() is not None


def _record_audit_trail(db: Session, user_id: int, event_type: str,
                        source_table: str, source_id: int, description: str) -> None:
    """Record AS9100 audit trail entry if AS9100 is enabled."""
    if not _as9100_enabled(db, user_id):
        return
    trail = AS9100AuditTrail(
        user_id=user_id,
        event_type=event_type,
        source_table=source_table,
        source_id=source_id,
        description=description,
    )
    db.add(trail)
    db.commit()


@router.post("/upload", response_model=MTRUploadResponse, status_code=201)
async def upload_mtr(
    file: UploadFile = File(...),
    job_id: Optional[int] = Query(None, description="Link to specific job"),
    db: Session = Depends(get_db),
):
    """Upload an MTR PDF, extract chemistry and mechanical properties."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    # Check for duplicate
    file_hash = _agent.file_hash(pdf_bytes)
    existing = db.query(MaterialCert).filter(MaterialCert.file_hash == file_hash).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Duplicate MTR — already uploaded as ID {existing.id}")

    # Extract data
    extraction = _agent.extract_from_pdf(pdf_bytes)

    # Auto-match job if not explicitly provided
    matched_job_id = job_id
    if matched_job_id is None:
        jobs = [
            {"id": j.id, "material": j.material, "title": j.title}
            for j in db.query(Job).filter(Job.stage != "complete").limit(50).all()
        ]
        matched_job_id = _agent.auto_match_job(extraction, jobs)

    # Persist
    cert = MaterialCert(
        job_id=matched_job_id,
        filename=file.filename,
        file_hash=file_hash,
        heat_number=extraction.heat_number,
        material_spec=extraction.material_spec,
        spec_standard=extraction.spec_standard,
        spec_grade=extraction.spec_grade,
        chemistry_json=json.dumps(extraction.chemistry),
        mechanicals_json=json.dumps(extraction.mechanicals),
    )
    db.add(cert)
    db.commit()
    db.refresh(cert)

    # AS9100 audit trail (opt-in)
    _record_audit_trail(
        db, user_id=0,  # system user for uploads without auth
        event_type="mtr_uploaded",
        source_table="material_certs",
        source_id=cert.id,
        description=f"MTR uploaded: {file.filename}, heat #{extraction.heat_number or 'N/A'}",
    )

    return MTRUploadResponse(
        id=cert.id,
        filename=cert.filename,
        file_hash=cert.file_hash,
        heat_number=extraction.heat_number,
        material_spec=extraction.material_spec,
        spec_standard=extraction.spec_standard,
        spec_grade=extraction.spec_grade,
        chemistry=extraction.chemistry,
        mechanicals=extraction.mechanicals,
        verification_status="pending",
        matched_job_id=matched_job_id,
        extraction_method=extraction.extraction_method,
    )


@router.get("/specs", response_model=list[dict])
def list_supported_specs():
    """List all supported material specifications for verification."""
    return _agent.supported_specs()


@router.get("/{mtr_id}", response_model=MTRUploadResponse)
def get_mtr(mtr_id: int, db: Session = Depends(get_db)):
    """Get a single MTR with all extracted data."""
    cert = db.query(MaterialCert).filter(MaterialCert.id == mtr_id).first()
    if cert is None:
        raise HTTPException(status_code=404, detail=f"MTR {mtr_id} not found")
    return MTRUploadResponse(
        id=cert.id,
        filename=cert.filename,
        file_hash=cert.file_hash,
        heat_number=cert.heat_number,
        material_spec=cert.material_spec,
        spec_standard=cert.spec_standard,
        spec_grade=cert.spec_grade,
        chemistry=cert.chemistry,
        mechanicals=cert.mechanicals,
        verification_status=cert.verification_status,
        matched_job_id=cert.job_id,
        extraction_method="stored",
    )


@router.get("", response_model=list[MTRListItem])
def list_mtrs(
    job_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    spec: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List MTRs with optional filtering."""
    q = db.query(MaterialCert)
    if job_id is not None:
        q = q.filter(MaterialCert.job_id == job_id)
    if status:
        q = q.filter(MaterialCert.verification_status == status)
    if spec:
        q = q.filter(MaterialCert.material_spec.ilike(f"%{spec}%"))
    q = q.order_by(MaterialCert.uploaded_at.desc())
    certs = q.offset(skip).limit(limit).all()
    return [
        MTRListItem(
            id=c.id,
            filename=c.filename,
            heat_number=c.heat_number,
            material_spec=c.material_spec,
            verification_status=c.verification_status,
            job_id=c.job_id,
            uploaded_at=c.uploaded_at.isoformat(),
        )
        for c in certs
    ]


@router.post("/{mtr_id}/verify", response_model=MTRVerifyResponse)
def verify_mtr(mtr_id: int, req: MTRVerifyRequest, db: Session = Depends(get_db)):
    """Verify an MTR against a material specification."""
    cert = db.query(MaterialCert).filter(MaterialCert.id == mtr_id).first()
    if cert is None:
        raise HTTPException(status_code=404, detail=f"MTR {mtr_id} not found")

    from agents.mtr_reader import MTRExtraction
    extraction = MTRExtraction(
        chemistry=cert.chemistry,
        mechanicals=cert.mechanicals,
        material_spec=cert.material_spec,
    )

    result = _agent.verify_against_spec(extraction, spec_key=req.spec_key)

    # Update DB
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    cert.verification_status = result.status
    cert.verification_details_json = json.dumps([
        {
            "property_name": c.property_name,
            "actual_value": c.actual_value,
            "spec_min": c.spec_min,
            "spec_max": c.spec_max,
            "unit": c.unit,
            "passed": c.passed,
        }
        for c in result.details
    ])
    cert.verified_at = now
    db.commit()

    # AS9100 audit trail
    _record_audit_trail(
        db, user_id=0,
        event_type="mtr_verified",
        source_table="material_certs",
        source_id=cert.id,
        description=f"MTR verified against {result.spec_used}: {'PASS' if result.overall_pass else 'FAIL'}",
    )

    return MTRVerifyResponse(
        id=cert.id,
        verification_status=result.status,
        overall_pass=result.overall_pass,
        spec_used=result.spec_used,
        details=[
            PropertyCheck(
                property_name=c.property_name,
                actual_value=c.actual_value,
                spec_min=c.spec_min,
                spec_max=c.spec_max,
                unit=c.unit,
                passed=c.passed,
            )
            for c in result.details
        ],
    )


@router.post("/{mtr_id}/link-job")
def link_mtr_to_job(mtr_id: int, req: MTRLinkJobRequest, db: Session = Depends(get_db)):
    """Manually link an MTR to a job."""
    cert = db.query(MaterialCert).filter(MaterialCert.id == mtr_id).first()
    if cert is None:
        raise HTTPException(status_code=404, detail=f"MTR {mtr_id} not found")
    job = db.query(Job).filter(Job.id == req.job_id).first()
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {req.job_id} not found")
    cert.job_id = req.job_id
    db.commit()
    return {"status": "linked", "mtr_id": mtr_id, "job_id": req.job_id}
