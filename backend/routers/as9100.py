"""
AS9100 Certification router — compliance tracking, procedure generation, audit readiness.

Prefix: /api/quality/as9100
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import (
    AS9100Clause, AS9100ComplianceStatus, AS9100Procedure,
    AS9100AuditTrail, ShopConfig,
)
from agents.as9100_agent import AS9100Agent
from auth.dependencies import get_current_user
from models.quality_models import (
    ComplianceDashboard, ClauseStatus, ProcedureGenerateRequest,
    ProcedureResponse, ProcedureUpdateRequest, ClauseStatusUpdate,
    AuditTrailItem, AuditReadiness,
)

logger = logging.getLogger("millforge.as9100_router")

router = APIRouter(prefix="/api/quality/as9100", tags=["Quality — AS9100 Certification"])

_agent = AS9100Agent()


def _get_shop_context(db: Session, user_id: int) -> dict:
    """Get shop config for procedure generation context."""
    config = db.query(ShopConfig).filter(ShopConfig.user_id == user_id).first()
    if config is None:
        return {}
    return {
        "shop_name": config.shop_name,
        "machine_count": config.machine_count,
        "materials": config.materials,
        "shifts_per_day": config.shifts_per_day,
    }


@router.post("/initialize")
def initialize_as9100(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user_id = current_user.id
    """Initialize AS9100 clauses and user compliance tracking."""
    clauses_created = _agent.initialize_clauses(db)
    statuses_created = _agent.initialize_user_compliance(db, user_id)
    return {
        "clauses_created": clauses_created,
        "statuses_created": statuses_created,
    }


@router.get("/dashboard", response_model=ComplianceDashboard)
def get_dashboard(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user_id = current_user.id
    """Overall compliance dashboard."""
    result = _agent.get_compliance_dashboard(db, user_id)
    return ComplianceDashboard(
        clauses=[ClauseStatus(**c) for c in result["clauses"]],
        overall_percent=result["overall_percent"],
        total_clauses=result["total_clauses"],
        documented_count=result["documented_count"],
        verified_count=result["verified_count"],
        next_actions=result["next_actions"],
    )


@router.get("/clauses")
def list_clauses(db: Session = Depends(get_db)):
    """List all AS9100D clauses."""
    clauses = db.query(AS9100Clause).order_by(AS9100Clause.clause_number).all()
    return [
        {
            "id": c.id,
            "clause_number": c.clause_number,
            "clause_title": c.clause_title,
            "description": c.description,
            "required_documents": c.required_documents,
        }
        for c in clauses
    ]


@router.get("/clauses/{clause_id}")
def get_clause(clause_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user_id = current_user.id
    """Get a single clause with compliance status and evidence."""
    clause = db.query(AS9100Clause).filter(AS9100Clause.id == clause_id).first()
    if clause is None:
        raise HTTPException(status_code=404, detail=f"Clause {clause_id} not found")

    status = db.query(AS9100ComplianceStatus).filter(
        AS9100ComplianceStatus.user_id == user_id,
        AS9100ComplianceStatus.clause_id == clause_id,
    ).first()

    procedures = db.query(AS9100Procedure).filter(
        AS9100Procedure.user_id == user_id,
        AS9100Procedure.clause_id == clause_id,
    ).all()

    return {
        "clause": {
            "id": clause.id,
            "clause_number": clause.clause_number,
            "clause_title": clause.clause_title,
            "description": clause.description,
            "required_documents": clause.required_documents,
        },
        "status": status.status if status else "not_initialized",
        "evidence": status.evidence if status else [],
        "procedures": [
            {
                "id": p.id, "title": p.title, "version": p.version,
                "status": p.status, "created_at": p.created_at.isoformat(),
            }
            for p in procedures
        ],
    }


@router.put("/clauses/{clause_id}/status")
def update_clause_status(
    clause_id: int, req: ClauseStatusUpdate,
    db: Session = Depends(get_db), current_user=Depends(get_current_user),
):
    user_id = current_user.id
    """Update compliance status for a clause."""
    status = db.query(AS9100ComplianceStatus).filter(
        AS9100ComplianceStatus.user_id == user_id,
        AS9100ComplianceStatus.clause_id == clause_id,
    ).first()
    if status is None:
        raise HTTPException(status_code=404, detail="Status not found. Initialize AS9100 first.")

    status.status = req.status
    if req.notes:
        status.notes = req.notes
    db.commit()
    return {"clause_id": clause_id, "status": req.status}


@router.post("/procedures/generate", response_model=ProcedureResponse)
def generate_procedure(
    req: ProcedureGenerateRequest,
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = current_user.id
    """AI-generate a QMS procedure for a clause."""
    shop_context = _get_shop_context(db, user_id)
    result = _agent.generate_procedure(db, user_id, req.clause_id, shop_context)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return ProcedureResponse(**result)


@router.get("/procedures/{procedure_id}", response_model=ProcedureResponse)
def get_procedure(procedure_id: int, db: Session = Depends(get_db)):
    """Get a procedure."""
    proc = db.query(AS9100Procedure).filter(AS9100Procedure.id == procedure_id).first()
    if proc is None:
        raise HTTPException(status_code=404, detail=f"Procedure {procedure_id} not found")
    clause = db.query(AS9100Clause).filter(AS9100Clause.id == proc.clause_id).first()
    return ProcedureResponse(
        id=proc.id,
        clause_number=clause.clause_number if clause else "",
        clause_title=clause.clause_title if clause else "",
        procedure_type=proc.procedure_type,
        title=proc.title,
        content=proc.content,
        version=proc.version,
        status=proc.status,
        created_at=proc.created_at.isoformat(),
    )


@router.put("/procedures/{procedure_id}")
def update_procedure(procedure_id: int, req: ProcedureUpdateRequest, db: Session = Depends(get_db)):
    """Edit a procedure."""
    proc = db.query(AS9100Procedure).filter(AS9100Procedure.id == procedure_id).first()
    if proc is None:
        raise HTTPException(status_code=404, detail=f"Procedure {procedure_id} not found")
    if req.title:
        proc.title = req.title
    if req.content:
        proc.content = req.content
    db.commit()
    return {"id": proc.id, "status": "updated"}


@router.post("/procedures/{procedure_id}/approve")
def approve_procedure(procedure_id: int, db: Session = Depends(get_db)):
    """Approve a procedure."""
    proc = db.query(AS9100Procedure).filter(AS9100Procedure.id == procedure_id).first()
    if proc is None:
        raise HTTPException(status_code=404, detail=f"Procedure {procedure_id} not found")
    proc.status = "approved"
    db.commit()

    trail = AS9100AuditTrail(
        user_id=proc.user_id,
        event_type="procedure_approved",
        source_table="as9100_procedures",
        source_id=proc.id,
        description=f"Procedure approved: {proc.title}",
    )
    db.add(trail)
    db.commit()

    return {"id": proc.id, "status": "approved"}


@router.get("/audit-trail", response_model=list[AuditTrailItem])
def get_audit_trail(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(get_current_user),
):
    user_id = current_user.id
    """Full audit trail."""
    trails = db.query(AS9100AuditTrail).filter(
        AS9100AuditTrail.user_id == user_id
    ).order_by(AS9100AuditTrail.occurred_at.desc()).offset(skip).limit(limit).all()
    return [
        AuditTrailItem(
            id=t.id, event_type=t.event_type,
            source_table=t.source_table, source_id=t.source_id,
            description=t.description, occurred_at=t.occurred_at.isoformat(),
        )
        for t in trails
    ]


@router.get("/readiness", response_model=AuditReadiness)
def get_readiness(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user_id = current_user.id
    """Audit readiness score."""
    result = _agent.audit_readiness_score(db, user_id)
    return AuditReadiness(**result)


@router.post("/sync")
def sync_evidence(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    user_id = current_user.id
    """Pull evidence from MTR, Drawing, and Logbook modules."""
    result = _agent.pull_from_modules(db, user_id)
    return {"ingested": result}
