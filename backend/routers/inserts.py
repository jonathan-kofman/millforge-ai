"""
Insert Cross-Reference router — manage tooling inserts, find equivalents, optimize costs.

Prefix: /api/tooling/inserts
"""

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from db_models import ToolingInsert
from agents.insert_crossref import InsertCrossRefAgent
from models.quality_models import (
    InsertCreateRequest, InsertResponse, InsertSpec as InsertSpecSchema,
    EquivalentInsert, CostReport, WearComparison,
)

logger = logging.getLogger("millforge.inserts_router")

router = APIRouter(prefix="/api/tooling/inserts", tags=["Tooling — Insert Cross-Reference"])

_agent = InsertCrossRefAgent()


@router.get("", response_model=list[InsertResponse])
def list_inserts(
    manufacturer: Optional[str] = Query(None),
    insert_type: Optional[str] = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """List inserts with optional filtering."""
    q = db.query(ToolingInsert)
    if manufacturer:
        q = q.filter(ToolingInsert.manufacturer.ilike(f"%{manufacturer}%"))
    if insert_type:
        q = q.filter(ToolingInsert.insert_type == insert_type)
    q = q.order_by(ToolingInsert.manufacturer, ToolingInsert.part_number)
    inserts = q.offset(skip).limit(limit).all()
    return [
        InsertResponse(
            id=i.id, manufacturer=i.manufacturer, part_number=i.part_number,
            iso_designation=i.iso_designation, ansi_designation=i.ansi_designation,
            insert_type=i.insert_type, grade=i.grade, coating=i.coating,
            geometry=i.geometry, unit_cost_usd=i.unit_cost_usd,
            equivalents=i.equivalents, created_at=i.created_at.isoformat(),
        )
        for i in inserts
    ]


@router.post("", response_model=InsertResponse, status_code=201)
def create_insert(req: InsertCreateRequest, db: Session = Depends(get_db)):
    """Add an insert to the database."""
    insert = ToolingInsert(
        manufacturer=req.manufacturer,
        part_number=req.part_number,
        iso_designation=req.iso_designation,
        ansi_designation=req.ansi_designation,
        insert_type=req.insert_type,
        grade=req.grade,
        coating=req.coating,
        geometry_json=json.dumps(req.geometry),
        unit_cost_usd=req.unit_cost_usd,
    )
    db.add(insert)
    db.commit()
    db.refresh(insert)
    return InsertResponse(
        id=insert.id, manufacturer=insert.manufacturer,
        part_number=insert.part_number,
        iso_designation=insert.iso_designation,
        ansi_designation=insert.ansi_designation,
        insert_type=insert.insert_type, grade=insert.grade,
        coating=insert.coating, geometry=insert.geometry,
        unit_cost_usd=insert.unit_cost_usd,
        equivalents=insert.equivalents,
        created_at=insert.created_at.isoformat(),
    )


@router.get("/cost-report", response_model=CostReport)
def get_cost_report(db: Session = Depends(get_db)):
    """Cost optimization report across all inserts."""
    return CostReport(**_agent.cost_optimize(db))


@router.get("/{insert_id}", response_model=InsertResponse)
def get_insert(insert_id: int, db: Session = Depends(get_db)):
    """Get a single insert with equivalents."""
    insert = db.query(ToolingInsert).filter(ToolingInsert.id == insert_id).first()
    if insert is None:
        raise HTTPException(status_code=404, detail=f"Insert {insert_id} not found")
    return InsertResponse(
        id=insert.id, manufacturer=insert.manufacturer,
        part_number=insert.part_number,
        iso_designation=insert.iso_designation,
        ansi_designation=insert.ansi_designation,
        insert_type=insert.insert_type, grade=insert.grade,
        coating=insert.coating, geometry=insert.geometry,
        unit_cost_usd=insert.unit_cost_usd,
        equivalents=insert.equivalents,
        created_at=insert.created_at.isoformat(),
    )


@router.post("/parse", response_model=InsertSpecSchema)
def parse_designation(designation: str = Query(...)):
    """Parse an ISO 1832 / ANSI insert designation string."""
    spec = _agent.parse_designation(designation)
    return InsertSpecSchema(
        shape=spec.shape, clearance_angle=spec.clearance_angle,
        tolerance_class=spec.tolerance_class, insert_type=spec.insert_type,
        ic_mm=spec.ic_mm, thickness_mm=spec.thickness_mm,
        nose_radius_mm=spec.nose_radius_mm, chipbreaker=spec.chipbreaker,
        grade=spec.grade, raw_designation=spec.raw_designation,
    )


@router.post("/cross-ref", response_model=list[EquivalentInsert])
def find_cross_references(insert_id: int = Query(...), db: Session = Depends(get_db)):
    """Find cross-manufacturer equivalents for an insert."""
    equivalents = _agent.find_equivalents(db, insert_id)
    return [
        EquivalentInsert(
            id=e["id"], manufacturer=e["manufacturer"],
            part_number=e["part_number"],
            iso_designation=e.get("iso_designation"),
            unit_cost_usd=e.get("unit_cost_usd"),
            cost_savings_pct=e.get("cost_savings_pct"),
            wear_validated=e.get("wear_validated", False),
        )
        for e in equivalents
    ]


@router.post("/import-invoice")
def import_from_invoice(text: str = Query(..., description="Invoice text to parse")):
    """Parse invoice text for insert part numbers."""
    specs = _agent.import_from_invoice(text)
    return [
        {
            "shape": s.shape, "ic_mm": s.ic_mm, "thickness_mm": s.thickness_mm,
            "nose_radius_mm": s.nose_radius_mm, "chipbreaker": s.chipbreaker,
            "grade": s.grade, "raw_designation": s.raw_designation,
        }
        for s in specs
    ]


@router.post("/{insert_id}/validate-equivalent", response_model=WearComparison)
def validate_equivalent(
    insert_id: int, candidate_id: int = Query(...),
    db: Session = Depends(get_db),
):
    """Validate equivalence between two inserts using wear sensor data."""
    result = _agent.validate_with_wear_data(db, insert_id, candidate_id)
    return WearComparison(**result)
