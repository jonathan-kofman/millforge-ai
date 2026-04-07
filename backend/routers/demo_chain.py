"""
/api/demo/cad-to-quote — end-to-end lights-out demo.

Chains: STL upload → order extraction → SA schedule → energy estimate → quote.
All logic calls agent objects directly (no inter-process HTTP hops).
"""

import uuid
import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from typing import Optional

from models.schemas import (
    DemoChainResponse, CadParseResponse, ScheduledOrderOutput,
    EnergyEstimateResponse, QuoteResponse, SuggestedSupplier,
    MaterialType,
)
from agents.cad_parser import extract_from_stl
from agents.sa_scheduler import SAScheduler
from agents.scheduler import Order, get_mock_orders, THROUGHPUT
from agents.energy_optimizer import EnergyOptimizer, MACHINE_POWER_KW

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/demo", tags=["Demo"])

_sa = SAScheduler()
_energy = EnergyOptimizer()


@router.post(
    "/cad-to-quote",
    response_model=DemoChainResponse,
    summary="End-to-end demo: upload STL → get schedule + energy + quote in one call",
)
async def cad_to_quote(
    file: UploadFile = File(..., description="STL file (binary or ASCII)"),
    material: str = Form("steel", description="Material: steel | aluminum | titanium | copper"),
    quantity: int = Form(100, description="Number of units (1–100 000)", ge=1, le=100_000),
    priority: int = Form(3, description="Order priority 1 (urgent) – 10 (low)", ge=1, le=10),
    due_date_days: int = Form(14, description="Days from now for due date", ge=1, le=365),
) -> DemoChainResponse:
    """
    Upload an STL file and receive a complete production plan in one call:

    1. **CAD parse** — extract dimensions, complexity, volume from the STL
    2. **SA schedule** — slot the order into the current queue
    3. **Energy estimate** — cost and kWh for the scheduled production window
    4. **Quote** — unit price, total, lead time, carbon footprint

    This is the bridge that eliminates the human step of translating CAD geometry
    into a scheduled job — the entire flow runs without operator input.
    """
    # Validate material
    material = material.lower().strip()
    valid_materials = {"steel", "aluminum", "titanium", "copper"}
    if material not in valid_materials:
        raise HTTPException(status_code=400, detail=f"material must be one of {sorted(valid_materials)}")

    # Validate file
    if not file.filename or not file.filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only .stl files are accepted")
    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # ── Step 1: Parse STL ────────────────────────────────────────────────────
    try:
        parsed = extract_from_stl(file_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse STL: {exc}")

    cad_result = CadParseResponse(**parsed)

    # ── Step 2: Build order and schedule ────────────────────────────────────
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    due = now + timedelta(days=due_date_days)
    order_id = f"DEMO-{uuid.uuid4().hex[:8].upper()}"

    # Use complexity from CAD parse; blend with quantity for realistic job size
    order = Order(
        order_id=order_id,
        material=material,
        quantity=quantity,
        dimensions=cad_result.dimensions,
        due_date=due,
        priority=priority,
        complexity=float(cad_result.complexity),
    )

    # Schedule against the mock queue (same queue the benchmark uses)
    queue = get_mock_orders() + [order]
    try:
        schedule = _sa.optimize(queue, start_time=now)
    except Exception as exc:
        logger.error("SA scheduler error in demo chain: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scheduling engine error")

    # Find our demo order in the result
    demo_slot = next(
        (s for s in schedule.scheduled_orders if s.order.order_id == order_id), None
    )
    if demo_slot is None:
        raise HTTPException(status_code=500, detail="Demo order was not scheduled")

    scheduled_out = ScheduledOrderOutput(
        order_id=demo_slot.order.order_id,
        machine_id=demo_slot.machine_id,
        material=demo_slot.order.material,
        quantity=demo_slot.order.quantity,
        setup_start=demo_slot.setup_start,
        processing_start=demo_slot.processing_start,
        completion_time=demo_slot.completion_time,
        setup_minutes=demo_slot.setup_minutes,
        processing_minutes=demo_slot.processing_minutes,
        on_time=demo_slot.on_time,
        lateness_hours=demo_slot.lateness_hours,
        due_date=demo_slot.order.due_date,
    )

    # ── Step 3: Energy estimate ──────────────────────────────────────────────
    duration_hours = demo_slot.processing_minutes / 60.0
    try:
        ep = _energy.estimate_energy_cost(
            demo_slot.processing_start, duration_hours, material
        )
        energy_out = EnergyEstimateResponse(
            start_time=ep.start_time,
            end_time=ep.end_time,
            material=ep.material,
            estimated_kwh=round(ep.estimated_kwh, 2),
            estimated_cost_usd=round(ep.estimated_cost_usd, 2),
            peak_rate=ep.peak_rate,
            off_peak_rate=ep.off_peak_rate,
            recommendation=ep.recommendation,
            data_source=ep.data_source,
            validation_failures=ep.validation_failures,
        )
    except Exception as exc:
        logger.warning("Energy estimate failed in demo chain (non-fatal): %s", exc)
        energy_out = EnergyEstimateResponse(
            start_time=demo_slot.processing_start,
            end_time=demo_slot.completion_time,
            material=material,
            estimated_kwh=0.0,
            estimated_cost_usd=0.0,
            peak_rate=0.0,
            off_peak_rate=0.0,
            recommendation="Energy estimate unavailable",
            data_source="unavailable",
            validation_failures=["energy_estimation_error"],
        )

    # ── Step 4: Quote ────────────────────────────────────────────────────────
    UNIT_PRICE = {"steel": 2.50, "aluminum": 4.00, "titanium": 18.00, "copper": 6.50}
    unit_price = UNIT_PRICE.get(material, 3.00)

    # Volume discount
    if quantity >= 10_000:
        discount = 0.20
    elif quantity >= 1_000:
        discount = 0.10
    elif quantity >= 500:
        discount = 0.05
    else:
        discount = 0.0

    total_price = round(unit_price * quantity * (1 - discount), 2)
    lead_time_hours = (demo_slot.completion_time - now).total_seconds() / 3600
    lead_time_days = round(lead_time_hours / 24, 1)

    # Carbon footprint
    try:
        from agents.energy_optimizer import _get_carbon_intensity
        power_kw = MACHINE_POWER_KW.get(material, 70)
        carbon_intensity = _get_carbon_intensity()
        carbon_kg = round(power_kw * duration_hours * carbon_intensity, 3)
    except Exception:
        carbon_kg = None

    quote_out = QuoteResponse(
        quote_id=f"Q-{order_id}",
        material=material,
        dimensions=cad_result.dimensions,
        quantity=quantity,
        estimated_lead_time_hours=round(lead_time_hours, 1),
        estimated_lead_time_days=lead_time_days,
        unit_price_usd=unit_price,
        total_price_usd=total_price,
        currency="USD",
        valid_until=now + timedelta(days=7),
        notes=f"Volume discount applied: {int(discount*100)}%" if discount else "Standard pricing",
        carbon_footprint_kg_co2=carbon_kg,
    )

    # ── Summary line ─────────────────────────────────────────────────────────
    status = "on-time" if demo_slot.on_time else f"{demo_slot.lateness_hours:.1f}h late"
    summary = (
        f"{quantity}× {material} | Machine {demo_slot.machine_id} | "
        f"Ready {demo_slot.completion_time.strftime('%b %d %H:%M')} | "
        f"{status} | ${total_price:,.2f} | {energy_out.estimated_kwh:.1f} kWh"
    )

    return DemoChainResponse(
        cad_parse=cad_result,
        scheduled_order=scheduled_out,
        energy=energy_out,
        quote=quote_out,
        generated_at=now,
        on_time=demo_slot.on_time,
        summary=summary,
    )
