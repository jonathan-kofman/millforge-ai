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

from models.schemas import QuoteRequest, QuoteResponse, QuotePlaceRequest, QuotePlaceResponse
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

# ---------------------------------------------------------------------------
# Fabrication process constants — used when process_type != cnc_milling
# ---------------------------------------------------------------------------

# Human-readable label for each process type
PROCESS_LABELS: dict[str, str] = {
    "cnc_milling":        "CNC Milling",
    "cnc_turning":        "CNC Turning",
    "cutting_laser":      "Laser Cutting",
    "cutting_plasma":     "Plasma Cutting",
    "cutting_waterjet":   "Waterjet Cutting",
    "bending_press_brake":"Press Brake Bending",
    "welding_arc":        "Arc Welding",
    "stamping":           "Stamping",
    "edm_wire":           "Wire EDM",
    "edm_sinker":         "Sinker EDM",
}

# Cutting speed (mm/min) by process and material — for cut-path processes
CUTTING_SPEED_MM_MIN: dict[str, dict[str, float]] = {
    "cutting_laser":    {"steel": 3000, "aluminum": 6000, "stainless_steel": 2000, "titanium": 1500, "copper": 0, "default": 2500},
    "cutting_plasma":   {"steel": 4000, "aluminum": 3500, "stainless_steel": 2500, "titanium": 2000, "default": 3000},
    "cutting_waterjet": {"steel": 200, "aluminum": 400, "stainless_steel": 150, "titanium": 100, "copper": 300, "default": 250},
}

# Power draw (kW) for energy/carbon calc by process
PROCESS_POWER_KW: dict[str, float] = {
    "cnc_milling":         85, "cnc_turning": 45,
    "cutting_laser":        8, "cutting_plasma": 22, "cutting_waterjet": 45,
    "bending_press_brake": 18, "welding_arc": 12,
    "stamping":            55, "edm_wire": 4, "edm_sinker": 3,
}

# Setup time (hours) by process
SETUP_HOURS: dict[str, float] = {
    "cnc_milling": 0.5, "cnc_turning": 0.33,
    "cutting_laser": 0.25, "cutting_plasma": 0.25, "cutting_waterjet": 0.33,
    "bending_press_brake": 0.75, "welding_arc": 1.0,
    "stamping": 2.0, "edm_wire": 1.0, "edm_sinker": 1.5,
}

# Per-unit machining overhead (USD) by process — value-added labor + machine time
PROCESS_OVERHEAD_PER_UNIT: dict[str, float] = {
    "cnc_milling": 1.50, "cnc_turning": 1.20,
    "cutting_laser": 0.40, "cutting_plasma": 0.25, "cutting_waterjet": 0.80,
    "bending_press_brake": 0.60, "welding_arc": 3.50,
    "stamping": 0.15, "edm_wire": 8.00, "edm_sinker": 10.00,
}


def _parse_dims_mm(dimensions: str) -> tuple[float, float, float]:
    """Parse 'LxWxHmm' → (length, width, thickness) in mm. Returns (200,100,10) on failure."""
    import re
    cleaned = dimensions.lower().replace("×", "x").replace(" ", "")
    cleaned = re.sub(r"[a-z]+$", "", cleaned)
    parts = cleaned.split("x")
    try:
        vals = [float(p) for p in parts]
        if len(vals) == 3:
            return vals[0], vals[1], vals[2]
        if len(vals) == 2:
            return vals[0], vals[1], 10.0
    except ValueError:
        pass
    return 200.0, 100.0, 10.0


def _estimate_fabrication(req, process_type: str) -> tuple[float, float, str]:
    """
    Estimate lead-time hours and unit cost for non-CNC fabrication processes.

    Returns (lead_time_hours, unit_cost_usd, notes_suffix).
    """
    mat = req.material.value
    qty = req.quantity
    length_mm, width_mm, thickness_mm = _parse_dims_mm(req.dimensions)

    if process_type in ("cutting_laser", "cutting_plasma", "cutting_waterjet"):
        speeds = CUTTING_SPEED_MM_MIN[process_type]
        speed = speeds.get(mat, speeds["default"])
        if speed <= 0:
            speed = speeds["default"]
        # Perimeter + ~50% for interior features, times quantity
        cut_length_mm = (2 * (length_mm + width_mm) * 1.5) * qty
        cut_hours = (cut_length_mm / speed) / 60.0
        lead_hours = SETUP_HOURS[process_type] + cut_hours
        unit_cost = PROCESS_OVERHEAD_PER_UNIT[process_type]
        note = f"Cut path ~{cut_length_mm/qty:.0f} mm/part at {speed:.0f} mm/min."

    elif process_type == "bending_press_brake":
        # Assume 1 bend per 100mm of length, min 2 bends per part
        bends_per_part = max(2, int(length_mm / 100))
        time_per_bend_min = 2.0 + thickness_mm * 0.1  # thicker = slower
        bend_hours = (bends_per_part * time_per_bend_min * qty) / 60.0
        lead_hours = SETUP_HOURS[process_type] + bend_hours
        unit_cost = PROCESS_OVERHEAD_PER_UNIT[process_type]
        note = f"~{bends_per_part} bends/part at {time_per_bend_min:.1f} min/bend."

    elif process_type == "welding_arc":
        # Travel speed: ~300 mm/min on thin stock, slower on thick
        travel_speed = max(100.0, 400.0 - thickness_mm * 10.0)
        weld_length_mm = (length_mm + width_mm) * qty  # perimeter estimate
        weld_hours = (weld_length_mm / travel_speed) / 60.0
        lead_hours = SETUP_HOURS[process_type] + weld_hours
        unit_cost = PROCESS_OVERHEAD_PER_UNIT[process_type]
        note = f"Weld run ~{weld_length_mm/qty:.0f} mm/part at {travel_speed:.0f} mm/min."

    elif process_type == "stamping":
        spm = 60.0  # strokes per minute, typical progressive die
        stamp_hours = (qty / spm) / 60.0
        lead_hours = SETUP_HOURS[process_type] + stamp_hours
        unit_cost = PROCESS_OVERHEAD_PER_UNIT[process_type]
        note = f"Progressive die at {spm:.0f} SPM. Setup {SETUP_HOURS[process_type]:.0f}h."

    elif process_type in ("edm_wire", "edm_sinker"):
        # Wire EDM: ~50 mm/min on 10mm steel; sinker: slower for cavity
        base_speed = 50.0 if process_type == "edm_wire" else 20.0
        speed = base_speed / max(1.0, thickness_mm / 10.0)  # slower on thicker
        cut_mm = 2 * (length_mm + width_mm) * qty
        edm_hours = (cut_mm / speed) / 60.0
        lead_hours = SETUP_HOURS[process_type] + edm_hours
        unit_cost = PROCESS_OVERHEAD_PER_UNIT[process_type]
        note = f"EDM at ~{speed:.0f} mm/min, {thickness_mm:.0f}mm depth."

    elif process_type == "cnc_turning":
        # Turning: cylindrical parts, simpler than milling
        diameter_mm = min(length_mm, width_mm)
        surface_speed_mm_min = {"steel": 200, "aluminum": 600, "titanium": 80, "copper": 300}.get(mat, 200)
        circumference = 3.14159 * diameter_mm
        turns_needed = length_mm / 0.2  # 0.2 mm/rev feed
        lathe_hours = (circumference * turns_needed * qty) / (surface_speed_mm_min * 1000 * 60)
        lead_hours = SETUP_HOURS[process_type] + max(lathe_hours, qty * 0.02)
        unit_cost = PROCESS_OVERHEAD_PER_UNIT[process_type]
        note = f"Turning Ø{diameter_mm:.0f}mm × {length_mm:.0f}mm at {surface_speed_mm_min} mm/min surface speed."

    else:
        # Generic fallback for any unrecognized process
        lead_hours = SETUP_HOURS.get(process_type, 1.0) + qty * 0.01
        unit_cost = PROCESS_OVERHEAD_PER_UNIT.get(process_type, 2.0)
        note = f"Process: {PROCESS_LABELS.get(process_type, process_type)}."

    return lead_hours, unit_cost, note


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
    process_type = getattr(req, "process_type", "cnc_milling") or "cnc_milling"
    process_label = PROCESS_LABELS.get(process_type, process_type.replace("_", " ").title())
    logger.info(f"Quote request: {req.material} x{req.quantity} [{req.dimensions}] process={process_type}")

    due_date = req.due_date or datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
    quote_id = f"QUOTE-{uuid.uuid4().hex[:8].upper()}"

    is_cnc = process_type in ("cnc_milling", "cnc_turning", "") or process_type is None

    # --- Lead time ---
    if is_cnc and process_type != "cnc_turning":
        # Original CNC milling path: scheduler-based
        new_order = Order(
            order_id=quote_id,
            material=req.material.value,
            quantity=req.quantity,
            dimensions=req.dimensions,
            due_date=due_date,
            priority=req.priority,
        )
        current_queue = _load_db_queue(db)
        try:
            t0 = time.perf_counter()
            lead_time_hours = _scheduler.estimate_lead_time(new_order, current_queue)
            edd_ms = (time.perf_counter() - t0) * 1000
            logger.info("Quote EDD | lead=%.1fh elapsed=%.1fms", lead_time_hours, edd_ms)
        except Exception as e:
            logger.error(f"Scheduler error during quote: {e}")
            raise HTTPException(status_code=500, detail="Scheduling engine error")
        queue_depth = len(current_queue)
        fab_note = f"Lead time based on {queue_depth} orders in queue."
    else:
        # Fabrication process path: physics-based estimation
        lead_time_hours, _fab_overhead, fab_note = _estimate_fabrication(req, process_type)
        queue_depth = 0

    # Scale to calendar days based on shift schedule.
    if req.shifts_per_day and req.hours_per_shift:
        productive_hours_per_day = req.shifts_per_day * req.hours_per_shift
        lead_time_hours = lead_time_hours * (24 / productive_hours_per_day)
    lead_time_days = lead_time_hours / 24

    # --- Price ---
    if is_cnc and process_type != "cnc_turning":
        overhead = MACHINING_OVERHEAD_PER_UNIT.get(req.material.value, 2.00)
    else:
        _, overhead, _ = _estimate_fabrication(req, process_type)

    spot_price_per_lb, spot_source = _get_spot_price(req.material.value)
    unit_weight_lb = _estimate_unit_weight_lb(req.dimensions, req.material.value)
    material_cost_per_unit = spot_price_per_lb * unit_weight_lb
    unit_price = overhead + material_cost_per_unit

    discount = _volume_discount(req.quantity)
    discounted_unit = unit_price * (1 - discount)
    total_price = discounted_unit * req.quantity

    notes = (
        f"[{process_label}] {fab_note} "
        f"Material cost: ${material_cost_per_unit:.2f}/unit ({spot_source}, {unit_weight_lb:.2f} lb). "
        f"Volume discount: {discount*100:.0f}%."
    )

    # --- Carbon footprint ---
    carbon_kg: float | None = None
    try:
        power_kw = PROCESS_POWER_KW.get(process_type, MACHINE_POWER_KW.get(req.material.value, 70))
        kwh = lead_time_hours * power_kw
        intensity, _ = _get_carbon_intensity()
        carbon_kg = round(kwh * intensity, 2)
    except Exception as e:
        logger.warning(f"Carbon footprint calc failed (non-fatal): {e}")

    response = QuoteResponse(
        quote_id=quote_id,
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


@router.post("/quote/place", response_model=QuotePlaceResponse, status_code=201)
async def place_order_from_quote(
    req: QuotePlaceRequest,
    db: Session = Depends(get_db),
) -> QuotePlaceResponse:
    """
    Convert an accepted quote into a live order. No auth required — guest
    buyers supply their email. The created OrderRecord is immediately visible
    in the production schedule.

    The quote_id is preserved as po_number if no explicit PO is provided,
    so shop staff can trace the order back to the original quote.
    """
    due_date = req.desired_due_date or (
        datetime.now(timezone.utc).replace(tzinfo=None)
        + timedelta(days=max(1, int(req.estimated_lead_time_days) + 3))
    )

    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"

    rec = OrderRecord(
        order_id=order_id,
        material=req.material,
        dimensions=req.dimensions,
        quantity=req.quantity,
        priority=req.priority,
        complexity=1.0,
        due_date=due_date,
        status="pending",
        notes=req.notes or f"Placed from quote {req.quote_id}.",
        customer_name=req.customer_name,
        po_number=req.po_number or req.quote_id,
        process_type=req.process_type,
        contact_email=req.email,
        quoted_price_usd=req.total_price_usd,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)

    logger.info(
        "Order placed from quote: order_id=%s quote_id=%s customer=%s email=%s",
        order_id, req.quote_id, req.customer_name, req.email,
    )

    # Confirmation email to customer — non-fatal if SMTP not configured
    try:
        import os, smtplib
        from email.mime.text import MIMEText as _MIMEText
        smtp_email = os.getenv("SMTP_EMAIL", "").strip()
        smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
        if smtp_email and smtp_password:
            process_label = PROCESS_LABELS.get(req.process_type, req.process_type.replace("_", " ").title())
            body = (
                f"Hi {req.customer_name},\n\n"
                f"Your order has been placed and entered the production queue.\n\n"
                f"Order ID:     {order_id}\n"
                f"Process:      {process_label}\n"
                f"Material:     {req.material}\n"
                f"Quantity:     {req.quantity:,}\n"
                f"Dimensions:   {req.dimensions}\n"
                f"Quoted price: ${req.total_price_usd:,.2f}\n"
                f"Est. ship:    {due_date.strftime('%Y-%m-%d')}\n\n"
                f"Quote ref: {req.quote_id}\n\n"
                f"— MillForge"
            )
            msg = _MIMEText(body)
            msg["Subject"] = f"MillForge order confirmed — {order_id}"
            msg["From"] = smtp_email
            msg["To"] = str(req.email)
            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(smtp_email, smtp_password)
                server.sendmail(smtp_email, [str(req.email)], msg.as_string())
    except Exception as exc:
        logger.warning("Confirmation email failed (non-fatal): %s", exc)

    ship_date = due_date.strftime("%Y-%m-%d")
    return QuotePlaceResponse(
        order_id=order_id,
        status="pending",
        message=f"Order {order_id} created and added to the production queue.",
        estimated_ship_date=ship_date,
    )
