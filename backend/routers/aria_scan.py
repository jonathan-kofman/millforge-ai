"""
/api/aria — ARIA-OS scan catalog → MillForge pipeline.

Translates scanned part catalog entries (geometry, material, primitives) into
quotable, schedulable MillForge jobs — no human CAD interpretation required.

Distinct from /api/jobs/from-aria (aria_bridge.py) which handles validated
ARIA-OS machine job submissions. This router handles the earlier upstream
step: raw scan catalog → quote / order.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, Field

from agents.aria_bridge_agent import ARIABridgeAgent
from agents.stl_analyzer import STLAnalyzer
from agents.scheduler import Scheduler, Order, get_mock_orders
from routers.quote import UNIT_PRICE, _volume_discount

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/aria", tags=["ARIA Scan Bridge"])

_agent = ARIABridgeAgent()
_stl = STLAnalyzer()
_scheduler = Scheduler()


# ---------------------------------------------------------------------------
# Request / response schemas (local to this router — not added to schemas.py
# as these are ARIA-specific and not shared by other endpoints)
# ---------------------------------------------------------------------------

class PrimitiveSummary(BaseModel):
    type: str
    count: int = 1
    key_dimensions: Optional[Dict[str, Any]] = None


class BoundingBox(BaseModel):
    x: float = Field(..., gt=0)
    y: float = Field(..., gt=0)
    z: float = Field(..., gt=0)


class CatalogEntry(BaseModel):
    part_id: Optional[str] = None
    material: str = Field(..., description="ARIA material designation, e.g. '6061-T6', 'steel', '4140'")
    bounding_box: BoundingBox
    volume_mm3: Optional[float] = None
    primitives_summary: List[PrimitiveSummary] = Field(default_factory=list)
    priority: int = Field(5, ge=1, le=10)
    quantity: int = Field(1, gt=0)
    due_days: Optional[int] = Field(None, ge=1, le=365)


class ImportRequest(BaseModel):
    catalog_entry: CatalogEntry
    quantity: Optional[int] = Field(None, gt=0)
    due_days: Optional[int] = Field(None, ge=1, le=365)
    priority: Optional[int] = Field(None, ge=1, le=10)


class BulkImportRequest(BaseModel):
    catalog_entries: List[CatalogEntry] = Field(..., min_length=1, max_length=100)
    default_quantity: int = Field(1, gt=0)
    default_due_days: int = Field(14, ge=1, le=365)


class QuoteFromScanRequest(BaseModel):
    catalog_entry: CatalogEntry
    quantity: int = Field(1, gt=0)


class ComplexityEstimateRequest(BaseModel):
    primitives_summary: List[PrimitiveSummary]
    material: Optional[str] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entry_to_dict(entry: CatalogEntry) -> Dict[str, Any]:
    return {
        "part_id": entry.part_id,
        "material": entry.material,
        "bounding_box": {"x": entry.bounding_box.x, "y": entry.bounding_box.y, "z": entry.bounding_box.z},
        "volume_mm3": entry.volume_mm3,
        "primitives_summary": [p.model_dump() for p in entry.primitives_summary],
        "priority": entry.priority,
        "quantity": entry.quantity,
    }


def _build_quote(catalog_dict: Dict[str, Any], quantity: int) -> Dict[str, Any]:
    """Run the quote pipeline and return the full quote response dict."""
    quote_data = _agent.catalog_to_quote(catalog_dict, quantity)
    material = quote_data["material"]
    dimensions = quote_data["dimensions"]

    new_order = Order(
        order_id=f"ARIA-Q-{uuid.uuid4().hex[:8].upper()}",
        material=material,
        quantity=quantity,
        dimensions=dimensions,
        due_date=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=14),
        priority=int(catalog_dict.get("priority", 5)),
    )
    current_queue = get_mock_orders()
    try:
        lead_time_hours = _scheduler.estimate_lead_time(new_order, current_queue)
    except Exception as e:
        logger.warning("Scheduler error during ARIA quote: %s", e)
        lead_time_hours = 24.0

    unit_price = UNIT_PRICE.get(material, 5.00)
    discount = _volume_discount(quantity)
    discounted_unit = unit_price * (1 - discount)
    total_price = discounted_unit * quantity

    return {
        "quote_id": new_order.order_id,
        "material": material,
        "dimensions": dimensions,
        "quantity": quantity,
        "estimated_lead_time_hours": round(lead_time_hours, 1),
        "estimated_lead_time_days": round(lead_time_hours / 24, 2),
        "unit_price_usd": round(discounted_unit, 4),
        "total_price_usd": round(total_price, 2),
        "complexity": quote_data["complexity"],
        "estimated_machining_minutes": quote_data["estimated_machining_minutes"],
        "source_part_id": quote_data["source_part_id"],
        "valid_until": (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7)).isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/import", summary="Import a scanned part as a schedulable order")
async def import_from_scan(req: ImportRequest) -> Dict[str, Any]:
    """
    Accept an ARIA-OS catalog entry and return a ready-to-schedule order dict
    plus an instant quote.

    The response includes both the order (passable to POST /api/schedule) and
    the quote so the shop owner can confirm before committing.
    """
    catalog_dict = _entry_to_dict(req.catalog_entry)
    quantity = req.quantity or req.catalog_entry.quantity or 1
    priority = req.priority or req.catalog_entry.priority or 5
    due_days = req.due_days or req.catalog_entry.due_days or 14
    due_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=due_days)

    try:
        order = _agent.catalog_to_order(catalog_dict, quantity=quantity,
                                        due_date=due_date, priority=priority)
        summary = _agent.part_summary(catalog_dict)
        quote = _build_quote(catalog_dict, quantity)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "order": order,
        "quote": quote,
        "part_summary": summary,
    }


@router.post("/quote", summary="Get an instant quote for a scanned part")
async def quote_from_scan(req: QuoteFromScanRequest) -> Dict[str, Any]:
    """
    Accept an ARIA-OS catalog entry and return an instant quote.
    Does not create an order.
    """
    catalog_dict = _entry_to_dict(req.catalog_entry)
    try:
        quote = _build_quote(catalog_dict, req.quantity)
        summary = _agent.part_summary(catalog_dict)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {"quote": quote, "part_summary": summary}


@router.post("/bulk-import", summary="Batch import multiple scanned parts as orders")
async def bulk_import(req: BulkImportRequest) -> Dict[str, Any]:
    """
    Convert a batch of catalog entries to orders. Entries that fail material
    mapping or validation are skipped and reported in `skipped`.
    """
    orders: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for entry in req.catalog_entries:
        catalog_dict = _entry_to_dict(entry)
        try:
            due_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                days=int(entry.due_days or req.default_due_days)
            )
            qty = entry.quantity or req.default_quantity
            order = _agent.catalog_to_order(
                catalog_dict,
                quantity=qty,
                due_date=due_date,
                priority=entry.priority,
            )
            orders.append(order)
        except Exception as e:
            skipped.append({"part_id": entry.part_id or "?", "error": str(e)})

    return {
        "imported": len(orders),
        "skipped": len(skipped),
        "orders": orders,
        "skipped_details": skipped,
    }


@router.post("/complexity-estimate", summary="Estimate complexity from primitive feature list")
async def complexity_estimate(req: ComplexityEstimateRequest) -> Dict[str, Any]:
    """
    Quick complexity estimate without a full catalog entry.
    Useful for the UI to show a live complexity preview as features are added.
    """
    catalog_dict: Dict[str, Any] = {
        "material": req.material or "steel",
        "primitives_summary": [p.model_dump() for p in req.primitives_summary],
        "bounding_box": {"x": 100, "y": 100, "z": 50},
    }
    complexity = _agent.estimate_complexity(catalog_dict)
    return {"complexity": complexity, "feature_count": sum(p.count for p in req.primitives_summary)}


@router.post("/stl-analyze", summary="Analyze an uploaded STL file and return geometry + instant quote")
async def stl_analyze(
    file: UploadFile = File(...),
    material: str = Query("steel", description="Material designation (maps to steel/aluminum/titanium/copper)"),
    quantity: int = Query(1, gt=0, le=100_000),
) -> Dict[str, Any]:
    """
    Accept an STL file upload. Returns geometry analysis + a ready-to-import
    catalog entry + instant quote. No ARIA catalog JSON required.

    This is the zero-friction path: drop in an STL, get a quote.
    """
    if not file.filename or not file.filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only .stl files are accepted")

    stl_bytes = await file.read()
    if not stl_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        analysis = _stl.analyze(stl_bytes)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"STL parse error: {e}")

    # Map material
    try:
        mapped_material = _agent.map_material(material)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    catalog_dict = _stl.to_catalog_entry(analysis, material=mapped_material,
                                          part_id=file.filename.rsplit(".", 1)[0])

    try:
        quote = _build_quote(catalog_dict, quantity)
        summary = _agent.part_summary(catalog_dict)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return {
        "stl_analysis": analysis,
        "catalog_entry": catalog_dict,
        "quote": quote,
        "part_summary": summary,
    }
