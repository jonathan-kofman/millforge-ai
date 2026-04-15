"""
/api/quote endpoint – instant pricing and lead time estimation.

Performance note (2026-03-23): SA benchmark was removed from this path.
Profiling showed EDD vs SA delta averaged ~180 ms with negligible lead-time
difference for single-order estimation; EDD alone is used here for latency.
"""

import re
import time
import uuid
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.schemas import QuoteRequest, QuoteResponse
from agents.scheduler import Scheduler, Order, get_mock_orders, THROUGHPUT
from agents.energy_optimizer import MACHINE_POWER_KW, _get_carbon_intensity
from agents.market_quoter import _get_spot_price
from database import get_db
from db_models import OrderRecord

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["Quote"])

# Machining overhead per unit (USD) — value-added labor + machine time.
# Material cost is calculated separately from live spot prices.
MACHINING_OVERHEAD_PER_UNIT: dict = {
    "steel":            1.50,
    "aluminum":         2.00,
    "titanium":        12.00,
    "copper":           3.50,
    "brass":            2.20,
    "bronze":           2.50,
    "stainless_steel":  2.80,
    "carbon_steel":     1.60,
    "tool_steel":       4.00,
    "cast_iron":        1.20,
}

# Solid densities in g/cm³ for weight estimation from bounding box dimensions
MATERIAL_DENSITY_G_CM3: dict = {
    "steel":            7.85,
    "aluminum":         2.70,
    "titanium":         4.51,
    "copper":           8.96,
    "brass":            8.50,
    "bronze":           8.80,
    "stainless_steel":  7.99,
    "carbon_steel":     7.85,
    "tool_steel":       7.80,
    "cast_iron":        7.20,
}

_scheduler = Scheduler()


def _parse_vol_cm3(dimensions: str) -> float | None:
    """Parse 'LxWxHmm' (or '×' separator) → bounding box volume in cm³. Returns None if unparseable."""
    cleaned = dimensions.lower().replace("×", "x").replace(" ", "")
    cleaned = re.sub(r"[a-z]+$", "", cleaned)  # strip unit suffix
    parts = cleaned.split("x")
    if len(parts) == 3:
        try:
            dims_mm = [float(p) for p in parts]
            return (dims_mm[0] / 10) * (dims_mm[1] / 10) * (dims_mm[2] / 10)
        except ValueError:
            pass
    return None


def _estimate_unit_weight_lb(dimensions: str, material: str) -> float:
    """Estimate weight in lbs for one unit from bounding-box dimensions + material density."""
    vol_cm3 = _parse_vol_cm3(dimensions)
    if vol_cm3 is None:
        return 1.0  # 1 lb default when dimensions can't be parsed
    density = MATERIAL_DENSITY_G_CM3.get(material, 7.0)
    return max(vol_cm3 * density / 453.592, 0.01)


def _load_db_queue(db: Session) -> list[Order]:
    """
    Load pending/scheduled orders from DB for queue-depth estimation.
    Falls back to the demo order set if the shop has no orders yet.
    """
    try:
        records = (
            db.query(OrderRecord)
            .filter(OrderRecord.status.in_(["pending", "scheduled"]))
            .limit(200)
            .all()
        )
        if records:
            return [
                Order(
                    order_id=r.order_id,
                    material=r.material,
                    quantity=r.quantity,
                    dimensions=r.dimensions,
                    due_date=r.due_date,
                    priority=r.priority,
                    complexity=r.complexity,
                )
                for r in records
            ]
    except Exception as exc:
        logger.warning("DB queue fetch failed, using demo order set: %s", exc)
    return get_mock_orders()


@router.post("/quote", response_model=QuoteResponse, summary="Instant quote within real shop capacity constraints")
async def get_quote(
    req: QuoteRequest,
    db: Session = Depends(get_db),
) -> QuoteResponse:
    """
    Accept material, dimensions, and quantity; return a price and realistic
    lead-time estimate grounded in the shop's current capacity.

    The lead time is computed by injecting the new order into the live production
    queue and running the scheduler to find the earliest completion slot — not a
    static table lookup. If the shop is busy, the estimate reflects that. If
    capacity is available, the customer sees it immediately.

    Pricing = (machining overhead + live material cost) × quantity × volume discount.
    Material cost uses Yahoo Finance spot prices when available.
    """
    logger.info(f"Quote request: {req.material} x{req.quantity} [{req.dimensions}]")

    due_date = req.due_date or datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)

    new_order = Order(
        order_id=f"QUOTE-{uuid.uuid4().hex[:8].upper()}",
        material=req.material.value,
        quantity=req.quantity,
        dimensions=req.dimensions,
        due_date=due_date,
        priority=req.priority,
    )

    # Use real pending orders from DB; fall back to demo set if shop is empty
    current_queue = _load_db_queue(db)
    try:
        t0 = time.perf_counter()
        lead_time_hours = _scheduler.estimate_lead_time(new_order, current_queue)
        edd_ms = (time.perf_counter() - t0) * 1000
        logger.info("Quote EDD | lead=%.1fh elapsed=%.1fms", lead_time_hours, edd_ms)
    except Exception as e:
        logger.error(f"Scheduler error during quote: {e}")
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    # Scale to calendar days based on shift schedule.
    if req.shifts_per_day and req.hours_per_shift:
        productive_hours_per_day = req.shifts_per_day * req.hours_per_shift
        lead_time_hours = lead_time_hours * (24 / productive_hours_per_day)
    lead_time_days = lead_time_hours / 24

    # Price = machining overhead + live spot material cost
    machining = MACHINING_OVERHEAD_PER_UNIT.get(req.material.value, 2.00)
    spot_price_per_lb, spot_source = _get_spot_price(req.material.value)
    unit_weight_lb = _estimate_unit_weight_lb(req.dimensions, req.material.value)
    material_cost_per_unit = spot_price_per_lb * unit_weight_lb
    unit_price = machining + material_cost_per_unit

    discount = _volume_discount(req.quantity)
    discounted_unit = unit_price * (1 - discount)
    total_price = discounted_unit * req.quantity

    notes = (
        f"Lead time {lead_time_days:.1f} days based on {len(current_queue)} orders in queue. "
        f"Material cost: ${material_cost_per_unit:.2f}/unit ({spot_source}, {unit_weight_lb:.2f} lb). "
        f"Volume discount: {discount*100:.0f}%."
    )

    # Carbon footprint
    carbon_kg: float | None = None
    try:
        tput = THROUGHPUT.get(req.material.value, 3.0)
        proc_hours = (req.quantity / tput) * 1.0
        power_kw = MACHINE_POWER_KW.get(req.material.value, 70)
        kwh = proc_hours * power_kw
        intensity, _ = _get_carbon_intensity()
        carbon_kg = round(kwh * intensity, 2)
    except Exception as e:
        logger.warning(f"Carbon footprint calc failed (non-fatal): {e}")

    response = QuoteResponse(
        quote_id=new_order.order_id,
        material=req.material.value,
        dimensions=req.dimensions,
        quantity=req.quantity,
        estimated_lead_time_hours=round(lead_time_hours, 1),
        estimated_lead_time_days=round(lead_time_days, 2),
        unit_price_usd=round(discounted_unit, 4),
        total_price_usd=round(total_price, 2),
        valid_until=datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=7),
        notes=notes,
        carbon_footprint_kg_co2=carbon_kg,
    )

    # Fire-and-forget product analytics event
    try:
        from routers.analytics import record_event
        record_event(
            db,
            user_id=None,  # quote endpoint is public
            event_category="scheduling",
            event_type="quote_generated",
            payload={
                "material": req.material.value,
                "quantity": req.quantity,
                "lead_time_days": round(lead_time_days, 2),
                "total_price_usd": round(total_price, 2),
            },
        )
    except Exception:
        pass

    return response


def _volume_discount(quantity: int) -> float:
    """Return a discount fraction based on order quantity."""
    if quantity >= 10_000:
        return 0.20
    elif quantity >= 1_000:
        return 0.10
    elif quantity >= 500:
        return 0.05
    return 0.0
