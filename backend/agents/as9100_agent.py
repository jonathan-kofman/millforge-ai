"""
AS9100 Certification Agent — AI-guided quality management system.

Manages AS9100D clause compliance tracking, AI-generated QMS procedures,
audit trail from MTR/Drawing/Logbook modules, and audit readiness scoring.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("millforge.as9100")

# AS9100D clause definitions — the 20 most relevant clauses for small machine shops
AS9100D_CLAUSES = [
    {"number": "4.1", "title": "Understanding the Organization and its Context",
     "description": "Determine external and internal issues relevant to the QMS.",
     "required_documents": ["context_analysis"]},
    {"number": "4.2", "title": "Understanding Needs and Expectations of Interested Parties",
     "description": "Identify interested parties and their requirements.",
     "required_documents": ["interested_parties_register"]},
    {"number": "4.4", "title": "Quality Management System and its Processes",
     "description": "Establish, implement, maintain, and improve the QMS.",
     "required_documents": ["quality_manual", "process_map"]},
    {"number": "5.1", "title": "Leadership and Commitment",
     "description": "Top management commitment to the QMS.",
     "required_documents": ["quality_policy"]},
    {"number": "5.2", "title": "Quality Policy",
     "description": "Establish and communicate a quality policy.",
     "required_documents": ["quality_policy"]},
    {"number": "6.1", "title": "Actions to Address Risks and Opportunities",
     "description": "Identify risks and opportunities, plan actions to address them.",
     "required_documents": ["risk_register"]},
    {"number": "6.2", "title": "Quality Objectives and Planning",
     "description": "Establish quality objectives and plan to achieve them.",
     "required_documents": ["quality_objectives"]},
    {"number": "7.1.5", "title": "Monitoring and Measuring Resources",
     "description": "Ensure measuring equipment is calibrated and maintained.",
     "required_documents": ["calibration_records", "equipment_register"]},
    {"number": "7.2", "title": "Competence",
     "description": "Determine competence of persons affecting quality.",
     "required_documents": ["training_records", "competence_matrix"]},
    {"number": "7.5", "title": "Documented Information",
     "description": "Control of documents and records.",
     "required_documents": ["document_control_procedure"]},
    {"number": "8.1", "title": "Operational Planning and Control",
     "description": "Plan and control processes needed for product realization.",
     "required_documents": ["production_plan"]},
    {"number": "8.2", "title": "Requirements for Products and Services",
     "description": "Customer communication and review of requirements.",
     "required_documents": ["contract_review_procedure"]},
    {"number": "8.4", "title": "Control of Externally Provided Processes",
     "description": "Control of outsourced processes and purchased products.",
     "required_documents": ["supplier_evaluation", "approved_supplier_list"]},
    {"number": "8.5.1", "title": "Control of Production and Service Provision",
     "description": "Controlled conditions for production including work instructions.",
     "required_documents": ["work_instructions", "inspection_plans"]},
    {"number": "8.5.2", "title": "Identification and Traceability",
     "description": "Identify outputs and trace back to material certificates.",
     "required_documents": ["traceability_procedure", "material_certs"]},
    {"number": "8.6", "title": "Release of Products and Services",
     "description": "Verify product requirements have been met before release.",
     "required_documents": ["final_inspection_records"]},
    {"number": "8.7", "title": "Control of Nonconforming Outputs",
     "description": "Identify and control nonconforming outputs.",
     "required_documents": ["nonconformance_procedure", "ncr_log"]},
    {"number": "9.1", "title": "Monitoring, Measurement, Analysis and Evaluation",
     "description": "Monitor and measure QMS performance.",
     "required_documents": ["kpi_dashboard", "data_analysis"]},
    {"number": "9.2", "title": "Internal Audit",
     "description": "Conduct internal audits at planned intervals.",
     "required_documents": ["audit_schedule", "audit_reports"]},
    {"number": "10.2", "title": "Nonconformity and Corrective Action",
     "description": "React to nonconformities and take corrective action.",
     "required_documents": ["corrective_action_procedure", "capa_log"]},
]


class AS9100Agent:
    """AI-guided AS9100D certification management."""

    def __init__(self) -> None:
        pass

    def initialize_clauses(self, db: Session) -> int:
        """Seed as9100_clauses table if empty. Returns count of clauses created."""
        from db_models import AS9100Clause

        existing = db.query(AS9100Clause).count()
        if existing > 0:
            return 0

        count = 0
        for clause_data in AS9100D_CLAUSES:
            clause = AS9100Clause(
                clause_number=clause_data["number"],
                clause_title=clause_data["title"],
                description=clause_data["description"],
                required_documents_json=json.dumps(clause_data["required_documents"]),
            )
            db.add(clause)
            count += 1
        db.commit()
        return count

    def initialize_user_compliance(self, db: Session, user_id: int) -> int:
        """Create compliance status rows for a user across all clauses."""
        from db_models import AS9100Clause, AS9100ComplianceStatus

        clauses = db.query(AS9100Clause).all()
        count = 0
        for clause in clauses:
            existing = db.query(AS9100ComplianceStatus).filter(
                AS9100ComplianceStatus.user_id == user_id,
                AS9100ComplianceStatus.clause_id == clause.id,
            ).first()
            if existing is None:
                status = AS9100ComplianceStatus(
                    user_id=user_id,
                    clause_id=clause.id,
                    status="not_started",
                )
                db.add(status)
                count += 1
        db.commit()
        return count

    def get_compliance_dashboard(self, db: Session, user_id: int) -> dict:
        """Overall compliance status across all clauses."""
        from db_models import AS9100Clause, AS9100ComplianceStatus

        clauses = db.query(AS9100Clause).all()
        statuses = {
            s.clause_id: s
            for s in db.query(AS9100ComplianceStatus).filter(
                AS9100ComplianceStatus.user_id == user_id
            ).all()
        }

        clause_list = []
        documented_count = 0
        verified_count = 0

        for clause in clauses:
            status_obj = statuses.get(clause.id)
            status_str = status_obj.status if status_obj else "not_started"
            evidence = json.loads(status_obj.evidence_json) if status_obj else []

            if status_str in ("documented", "verified"):
                documented_count += 1
            if status_str == "verified":
                verified_count += 1

            clause_list.append({
                "clause_id": clause.id,
                "clause_number": clause.clause_number,
                "clause_title": clause.clause_title,
                "status": status_str,
                "evidence_count": len(evidence),
                "last_reviewed_at": (
                    status_obj.last_reviewed_at.isoformat()
                    if status_obj and status_obj.last_reviewed_at else None
                ),
            })

        total = len(clauses)
        overall_pct = (documented_count / total * 100) if total > 0 else 0.0

        # Generate next actions
        next_actions = []
        for cs in clause_list:
            if cs["status"] == "not_started":
                next_actions.append(f"Start clause {cs['clause_number']}: {cs['clause_title']}")
            elif cs["status"] == "in_progress":
                next_actions.append(f"Complete documentation for {cs['clause_number']}")
            if len(next_actions) >= 5:
                break

        return {
            "clauses": clause_list,
            "overall_percent": round(overall_pct, 1),
            "total_clauses": total,
            "documented_count": documented_count,
            "verified_count": verified_count,
            "next_actions": next_actions,
        }

    def generate_procedure(self, db: Session, user_id: int, clause_id: int,
                           shop_context: dict) -> dict:
        """AI-generate a QMS procedure for a specific clause."""
        from db_models import AS9100Clause, AS9100Procedure

        clause = db.query(AS9100Clause).filter(AS9100Clause.id == clause_id).first()
        if clause is None:
            return {"error": f"Clause {clause_id} not found"}

        from services.llm_service import generate_procedure as llm_generate
        content = llm_generate(
            clause.clause_number, clause.clause_title,
            clause.description, shop_context,
        )

        # Check for existing procedure
        existing = db.query(AS9100Procedure).filter(
            AS9100Procedure.user_id == user_id,
            AS9100Procedure.clause_id == clause_id,
        ).first()

        if existing:
            existing.content = content
            existing.version += 1
            db.commit()
            db.refresh(existing)
            proc = existing
        else:
            proc = AS9100Procedure(
                user_id=user_id,
                clause_id=clause_id,
                procedure_type=clause.clause_number.replace(".", "_"),
                title=f"Procedure: {clause.clause_title}",
                content=content,
            )
            db.add(proc)
            db.commit()
            db.refresh(proc)

        return {
            "id": proc.id,
            "clause_number": clause.clause_number,
            "clause_title": clause.clause_title,
            "procedure_type": proc.procedure_type,
            "title": proc.title,
            "content": proc.content,
            "version": proc.version,
            "status": proc.status,
            "created_at": proc.created_at.isoformat(),
        }

    def record_evidence(self, db: Session, user_id: int, clause_number: str,
                        evidence_type: str, source_id: int) -> None:
        """Link a quality record as evidence for an AS9100 clause."""
        from db_models import AS9100Clause, AS9100ComplianceStatus, AS9100AuditTrail

        clause = db.query(AS9100Clause).filter(
            AS9100Clause.clause_number == clause_number
        ).first()
        if clause is None:
            return

        status = db.query(AS9100ComplianceStatus).filter(
            AS9100ComplianceStatus.user_id == user_id,
            AS9100ComplianceStatus.clause_id == clause.id,
        ).first()
        if status is None:
            return

        evidence = json.loads(status.evidence_json)
        evidence.append({"type": evidence_type, "id": source_id})
        status.evidence_json = json.dumps(evidence)
        db.commit()

    def audit_readiness_score(self, db: Session, user_id: int) -> dict:
        """Compute audit readiness score (0-100) per clause and overall."""
        from db_models import AS9100Clause, AS9100ComplianceStatus

        clauses = db.query(AS9100Clause).all()
        statuses = {
            s.clause_id: s
            for s in db.query(AS9100ComplianceStatus).filter(
                AS9100ComplianceStatus.user_id == user_id
            ).all()
        }

        STATUS_SCORES = {
            "not_started": 0,
            "in_progress": 25,
            "documented": 75,
            "verified": 100,
            "non_conforming": 10,
        }

        clause_scores = {}
        gaps = []
        total_score = 0

        for clause in clauses:
            status_obj = statuses.get(clause.id)
            status_str = status_obj.status if status_obj else "not_started"
            score = STATUS_SCORES.get(status_str, 0)
            clause_scores[clause.clause_number] = score
            total_score += score

            if score < 75:
                gaps.append(f"{clause.clause_number} ({clause.clause_title}): {status_str}")

        overall = (total_score / len(clauses)) if clauses else 0

        return {
            "overall_score": round(overall, 1),
            "clause_scores": clause_scores,
            "gaps": gaps,
        }

    def pull_from_modules(self, db: Session, user_id: int) -> dict:
        """Auto-ingest new MTRs, inspection plans, and logbook entries as evidence."""
        from db_models import MaterialCert, DrawingInspection, LogbookEntry, AS9100AuditTrail

        ingested = {"mtr": 0, "inspection": 0, "logbook": 0}

        # Find MTRs not yet in audit trail
        existing_mtr_ids = {
            row.source_id
            for row in db.query(AS9100AuditTrail).filter(
                AS9100AuditTrail.source_table == "material_certs",
                AS9100AuditTrail.user_id == user_id,
            ).all()
        }
        new_mtrs = db.query(MaterialCert).filter(
            MaterialCert.id.notin_(existing_mtr_ids) if existing_mtr_ids else True
        ).all()
        for mtr in new_mtrs:
            self.record_evidence(db, user_id, "8.5.2", "mtr", mtr.id)
            ingested["mtr"] += 1

        # Find approved inspection plans not yet in audit trail
        existing_insp_ids = {
            row.source_id
            for row in db.query(AS9100AuditTrail).filter(
                AS9100AuditTrail.source_table == "drawing_inspections",
                AS9100AuditTrail.user_id == user_id,
            ).all()
        }
        new_inspections = db.query(DrawingInspection).filter(
            DrawingInspection.status == "approved",
            DrawingInspection.id.notin_(existing_insp_ids) if existing_insp_ids else True,
        ).all()
        for insp in new_inspections:
            self.record_evidence(db, user_id, "8.5.1", "inspection_plan", insp.id)
            ingested["inspection"] += 1

        # Find logbook issues not yet in audit trail
        existing_log_ids = {
            row.source_id
            for row in db.query(AS9100AuditTrail).filter(
                AS9100AuditTrail.source_table == "logbook_entries",
                AS9100AuditTrail.user_id == user_id,
            ).all()
        }
        new_issues = db.query(LogbookEntry).filter(
            LogbookEntry.category == "issue",
            LogbookEntry.id.notin_(existing_log_ids) if existing_log_ids else True,
        ).all()
        for issue in new_issues:
            self.record_evidence(db, user_id, "10.2", "logbook_entry", issue.id)
            ingested["logbook"] += 1

        return ingested
