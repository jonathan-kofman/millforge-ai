"""
Manufacturing REST API Router
================================
Exposes the manufacturing abstraction layer over HTTP at /api/manufacturing.

Design philosophy:
  - Thin router: all logic delegated to manufacturing.* modules
  - Registry is a module-level singleton, initialized lazily on first request
  - All request/response schemas defined here (self-contained Pydantic v2)
  - Error handling: validation errors → 422, registry not ready → 503

Endpoints:
  GET  /api/manufacturing/health           — registry stats + adapter count
  GET  /api/manufacturing/processes        — list registered process families
  GET  /api/manufacturing/machines         — list registered machines
  POST /api/manufacturing/route            — route a ManufacturingIntent
  POST /api/manufacturing/feasibility      — feasibility check for an intent
  POST /api/manufacturing/validate         — validate an intent, return errors
  POST /api/manufacturing/work-order       — create a WorkOrder from intent + route
  GET  /api/manufacturing/work-orders      — list work orders (placeholder)
  POST /api/manufacturing/estimate         — cycle time + cost estimate
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from manufacturing.bridge import bootstrap_registry
from manufacturing.ontology import (
    ManufacturingIntent,
    MaterialSpec,
    ProcessFamily,
)
from manufacturing.registry import (
    MachineCapability,
    ProcessCapability,
    ProcessRegistry,
)
from manufacturing.routing import RoutingEngine, RoutingResult
from manufacturing.validation import validate_intent as _validate_intent
from manufacturing.work_order import WorkOrder, WorkOrderStatus, WorkOrderStep

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/manufacturing",
    tags=["Manufacturing Intelligence"],
)

# ---------------------------------------------------------------------------
# Lazy registry singleton
# ---------------------------------------------------------------------------

_registry: Optional[ProcessRegistry] = None


def _get_registry() -> ProcessRegistry:
    """
    Return the module-level ProcessRegistry singleton, bootstrapping it lazily
    on first call. This is a fallback for when the lifespan hook hasn't run
    (e.g. standalone tests that don't start the full app).
    """
    global _registry
    if _registry is None:
        _registry = bootstrap_registry()
        logger.info("manufacturing router: lazily bootstrapped ProcessRegistry")
    return _registry


def set_registry(registry: ProcessRegistry) -> None:
    """
    Allow the lifespan hook (main.py) to inject the already-bootstrapped
    registry singleton, avoiding a second bootstrap on first request.
    """
    global _registry
    _registry = registry


# ---------------------------------------------------------------------------
# Request / Response schemas (Pydantic v2)
# ---------------------------------------------------------------------------


class MaterialSpecIn(BaseModel):
    """Slim material spec for API requests — maps to manufacturing.ontology.MaterialSpec."""
    model_config = {"populate_by_name": True}

    material_name: str = Field(min_length=1, description="e.g. 'aluminum', '304 Stainless Steel'")
    alloy_designation: Optional[str] = None
    material_family: str = Field(default="ferrous", description="ferrous | non_ferrous | polymer | composite | ceramic | other")
    form: str = Field(default="sheet", description="bar_stock | sheet | plate | tube | wire | powder | billet")
    thickness_mm: Optional[float] = Field(default=None, gt=0)
    width_mm: Optional[float] = Field(default=None, gt=0)
    length_mm: Optional[float] = Field(default=None, gt=0)
    density_kg_m3: Optional[float] = None
    yield_strength_mpa: Optional[float] = None
    hardness: Optional[str] = None
    custom_properties: Dict[str, Any] = Field(default_factory=dict)


class ManufacturingIntentRequest(BaseModel):
    """Request body for endpoints that accept a ManufacturingIntent."""
    model_config = {"populate_by_name": True}

    part_id: str = Field(min_length=1, description="Unique part identifier or order number")
    part_name: str = Field(default="", description="Human-readable part name")
    description: str = Field(default="")
    target_quantity: int = Field(ge=1, description="Number of finished parts required")
    material: MaterialSpecIn
    required_processes: Optional[List[str]] = Field(
        default=None,
        description="Process families that MUST be used (e.g. ['CNC_MILLING', 'CUTTING_LASER'])"
    )
    preferred_processes: Optional[List[str]] = None
    forbidden_processes: Optional[List[str]] = None
    due_date: Optional[datetime] = None
    priority: int = Field(default=5, ge=1, le=10)
    cost_target_usd: Optional[float] = Field(default=None, gt=0)
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)


class RouteOptionOut(BaseModel):
    """A single routing option with scores."""
    process_family: str
    machine_id: str
    machine_name: str
    estimated_cycle_time_minutes: float
    estimated_cost_usd: float
    setup_time_minutes: float
    score: float
    reasoning: str


class RoutingResultOut(BaseModel):
    """Response for POST /route."""
    part_id: str
    viable: bool
    selected: Optional[RouteOptionOut] = None
    options: List[RouteOptionOut]
    warnings: List[str]


class FeasibilityResultOut(BaseModel):
    """Response for POST /feasibility."""
    part_id: str
    feasible: bool
    supported_processes: List[str]
    validation_errors: List[str]
    routing_warnings: List[str]
    capable_machine_count: int


class ValidationResultOut(BaseModel):
    """Response for POST /validate."""
    part_id: str
    valid: bool
    errors: List[str]


class WorkOrderRequest(BaseModel):
    """Request body for POST /work-order."""
    intent: ManufacturingIntentRequest
    process_family: Optional[str] = Field(
        default=None,
        description="Force a specific process family. If omitted, best route is auto-selected."
    )
    machine_id: Optional[str] = Field(
        default=None,
        description="Force a specific machine. If omitted, best available machine is selected."
    )


class WorkOrderStepOut(BaseModel):
    """Serializable work order step."""
    step_number: int
    process_family: str
    machine_id: Optional[str]
    status: str
    setup_sheet: Dict[str, Any]
    estimated_time_minutes: float


class WorkOrderOut(BaseModel):
    """Response for POST /work-order."""
    work_order_id: str
    part_id: str
    part_name: str
    status: str
    priority: int
    step_count: int
    steps: List[WorkOrderStepOut]
    total_estimated_cost_usd: Optional[float]
    due_date: Optional[datetime]
    created_at: datetime


class EstimateRequest(BaseModel):
    """Request body for POST /estimate."""
    intent: ManufacturingIntentRequest
    process_family: str = Field(description="e.g. 'CNC_MILLING', 'CUTTING_LASER'")


class EstimateOut(BaseModel):
    """Response for POST /estimate."""
    part_id: str
    process_family: str
    machine_id: Optional[str]
    estimated_cycle_time_minutes: float
    estimated_cost_usd: float
    setup_time_minutes: float
    energy_profile: Dict[str, Any]


class ProcessFamilyOut(BaseModel):
    """One process family entry in GET /processes."""
    process_family: str
    adapter_registered: bool
    supported_materials: List[str]
    capabilities_summary: Dict[str, Any]


class MachineOut(BaseModel):
    """One machine entry in GET /machines."""
    machine_id: str
    machine_name: str
    machine_type: str
    is_available: bool
    supported_processes: List[str]
    location: str
    max_weight_kg: Optional[float]


class HealthOut(BaseModel):
    """Response for GET /health."""
    status: str
    registered_adapters: int
    registered_machines: int
    available_machines: int
    supported_processes: List[str]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_process_families(families: Optional[List[str]]) -> Optional[List[ProcessFamily]]:
    """Convert list of string process family names to ProcessFamily enums."""
    if families is None:
        return None
    result: List[ProcessFamily] = []
    for f in families:
        try:
            result.append(ProcessFamily(f))
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown process family: '{f}'. "
                       f"Valid values: {[e.value for e in ProcessFamily]}"
            )
    return result


def _intent_from_request(req: ManufacturingIntentRequest) -> ManufacturingIntent:
    """Convert API request model to domain ManufacturingIntent."""
    material = MaterialSpec(
        material_name=req.material.material_name,
        alloy_designation=req.material.alloy_designation,
        material_family=req.material.material_family,
        form=req.material.form,
        thickness_mm=req.material.thickness_mm,
        width_mm=req.material.width_mm,
        length_mm=req.material.length_mm,
        density_kg_m3=req.material.density_kg_m3,
        yield_strength_mpa=req.material.yield_strength_mpa,
        hardness=req.material.hardness,
        custom_properties=req.material.custom_properties,
    )

    try:
        return ManufacturingIntent(
            part_id=req.part_id,
            part_name=req.part_name or req.part_id,
            description=req.description,
            target_quantity=req.target_quantity,
            material=material,
            required_processes=_parse_process_families(req.required_processes),
            preferred_processes=_parse_process_families(req.preferred_processes),
            forbidden_processes=_parse_process_families(req.forbidden_processes),
            due_date=req.due_date,
            priority=req.priority,
            cost_target_usd=req.cost_target_usd,
            custom_metadata=req.custom_metadata,
        )
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=422, detail=str(e))


def _route_option_to_out(option) -> RouteOptionOut:
    return RouteOptionOut(
        process_family=option.process_family.value,
        machine_id=option.machine.machine_id,
        machine_name=option.machine.machine_name,
        estimated_cycle_time_minutes=option.estimated_cycle_time_minutes,
        estimated_cost_usd=option.estimated_cost_usd,
        setup_time_minutes=option.setup_time_minutes,
        score=option.score,
        reasoning=option.reasoning,
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/health", response_model=HealthOut, summary="Manufacturing registry health")
async def manufacturing_health() -> HealthOut:
    """
    Return the current state of the process registry — adapter count,
    machine count, supported processes.
    """
    registry = _get_registry()
    stats = registry.get_stats()
    return HealthOut(
        status="ok",
        registered_adapters=stats["registered_adapters"],
        registered_machines=stats["registered_machines"],
        available_machines=stats["available_machines"],
        supported_processes=stats["supported_processes"],
    )


@router.get(
    "/processes",
    response_model=List[ProcessFamilyOut],
    summary="List all registered process families with capabilities",
)
async def list_processes() -> List[ProcessFamilyOut]:
    """
    Return all process families that have a registered adapter.
    Includes the adapter's capability summary (materials, envelope, tolerances).
    """
    registry = _get_registry()
    families = registry.list_supported_processes()

    result: List[ProcessFamilyOut] = []
    for family in families:
        adapter = registry.get_adapter(family)
        # Find any registered machine for this process to get capability details
        machines = registry.find_capable_machines_any_material(family)
        if machines:
            cap = machines[0].get_capability(family)
            cap_summary: Dict[str, Any] = {
                "supported_materials": cap.supported_materials if cap else [],
                "max_part_dimensions_mm": cap.max_part_dimensions_mm if cap else None,
                "tolerances": cap.tolerances if cap else {},
                "throughput_range": cap.throughput_range if cap else None,
                "machine_count": len(machines),
            }
            supported_materials = cap.supported_materials if cap else []
        else:
            cap_summary = {"machine_count": 0, "note": "no machines registered for this process"}
            supported_materials = []

        result.append(ProcessFamilyOut(
            process_family=family.value,
            adapter_registered=adapter is not None,
            supported_materials=supported_materials,
            capabilities_summary=cap_summary,
        ))

    return result


@router.get(
    "/machines",
    response_model=List[MachineOut],
    summary="List all registered machines with capabilities",
)
async def list_machines(available_only: bool = True) -> List[MachineOut]:
    """
    Return all registered machines with their process capabilities.

    Query params:
      - available_only: If True (default), only return machines where is_available=True.
    """
    registry = _get_registry()
    machines = registry.list_machines(available_only=available_only)

    return [
        MachineOut(
            machine_id=m.machine_id,
            machine_name=m.machine_name,
            machine_type=m.machine_type,
            is_available=m.is_available,
            supported_processes=[cap.process_family.value for cap in m.capabilities],
            location=m.location,
            max_weight_kg=m.max_weight_kg,
        )
        for m in machines
    ]


@router.post(
    "/route",
    response_model=RoutingResultOut,
    summary="Route a ManufacturingIntent to optimal process + machine",
)
async def route_intent(body: ManufacturingIntentRequest) -> RoutingResultOut:
    """
    Given a ManufacturingIntent, return all viable (process, machine) pairs
    scored by cost, time, quality, and energy efficiency.

    The `selected` field contains the highest-scoring option.
    """
    registry = _get_registry()
    intent = _intent_from_request(body)

    engine = RoutingEngine(registry)
    result: RoutingResult = engine.route(intent)

    return RoutingResultOut(
        part_id=intent.part_id,
        viable=result.has_viable_route,
        selected=_route_option_to_out(result.selected) if result.selected else None,
        options=[_route_option_to_out(o) for o in result.options],
        warnings=result.warnings,
    )


@router.post(
    "/feasibility",
    response_model=FeasibilityResultOut,
    summary="Check feasibility of a ManufacturingIntent",
)
async def check_feasibility(body: ManufacturingIntentRequest) -> FeasibilityResultOut:
    """
    Check whether the manufacturing layer can fulfill the given intent.
    Returns supported processes, validation errors, and machine counts.
    """
    registry = _get_registry()
    intent = _intent_from_request(body)

    # Run validation
    errors = _validate_intent(intent, registry)

    # Run routing to find viable options
    engine = RoutingEngine(registry)
    result = engine.route(intent)

    # Count capable machines across all registered processes
    material = intent.material.normalized_name
    capable_count = 0
    for family in registry.list_supported_processes():
        machines = registry.find_capable_machines(family, material)
        capable_count += len(machines)

    return FeasibilityResultOut(
        part_id=intent.part_id,
        feasible=result.has_viable_route and len(errors) == 0,
        supported_processes=[p.value for p in registry.list_supported_processes()],
        validation_errors=errors,
        routing_warnings=result.warnings,
        capable_machine_count=capable_count,
    )


@router.post(
    "/validate",
    response_model=ValidationResultOut,
    summary="Validate a ManufacturingIntent and return errors",
)
async def validate_manufacturing_intent(body: ManufacturingIntentRequest) -> ValidationResultOut:
    """
    Run all validation rules against the intent.
    Returns a list of human-readable errors. An empty list means valid.
    """
    registry = _get_registry()
    intent = _intent_from_request(body)
    errors = _validate_intent(intent, registry)

    return ValidationResultOut(
        part_id=intent.part_id,
        valid=len(errors) == 0,
        errors=errors,
    )


@router.post(
    "/work-order",
    response_model=WorkOrderOut,
    summary="Create a WorkOrder from a ManufacturingIntent",
)
async def create_work_order(body: WorkOrderRequest) -> WorkOrderOut:
    """
    Route the intent and create a WorkOrder from the best match.

    If `process_family` and/or `machine_id` are specified, they constrain
    the routing to that specific combination. Otherwise the highest-scoring
    option is selected automatically.
    """
    registry = _get_registry()
    intent = _intent_from_request(body.intent)

    # Override required_processes if caller specified a process family
    if body.process_family:
        try:
            forced_family = ProcessFamily(body.process_family)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown process_family: '{body.process_family}'"
            )
        intent = intent.model_copy(update={"required_processes": [forced_family]})

    engine = RoutingEngine(registry)
    result = engine.route(intent)

    if not result.has_viable_route:
        raise HTTPException(
            status_code=422,
            detail={
                "message": f"No viable manufacturing route found for part '{intent.part_id}'.",
                "warnings": result.warnings,
            }
        )

    # Select option — forced machine_id overrides score-based selection
    selected = result.selected
    if body.machine_id and selected is not None:
        # Try to find the option with the matching machine
        for option in result.options:
            if option.machine.machine_id == body.machine_id:
                selected = option
                break
        else:
            raise HTTPException(
                status_code=422,
                detail=f"Machine '{body.machine_id}' is not among the viable routing options."
            )

    if selected is None:
        raise HTTPException(status_code=422, detail="No route selected.")

    adapter = registry.get_adapter(selected.process_family)
    if adapter is None:
        raise HTTPException(
            status_code=503,
            detail=f"Adapter for {selected.process_family.value} not available."
        )

    # Generate setup sheet
    setup_sheet = adapter.generate_setup_sheet(intent, selected.machine)

    # Build work order step
    step = WorkOrderStep(
        step_number=1,
        process_family=selected.process_family,
        machine_id=selected.machine.machine_id,
        status=WorkOrderStatus.DRAFT,
        setup_sheet=setup_sheet,
        estimated_time_minutes=selected.setup_time_minutes + selected.estimated_cycle_time_minutes,
    )

    # Build a minimal ProcessPlan for WorkOrder (required field)
    from manufacturing.ontology import (
        ProcessPlan,
        ProcessStepDefinition,
        ProcessConstraints,
    )
    energy = adapter.get_energy_profile(intent, selected.machine)
    step_def = ProcessStepDefinition(
        step_id="step-1",
        process_family=selected.process_family,
        description=f"{selected.process_family.value} on {selected.machine.machine_name}",
        material_input=intent.material,
        energy=energy,
        estimated_cycle_time_minutes=selected.estimated_cycle_time_minutes,
        setup_time_minutes=selected.setup_time_minutes,
    )
    plan = ProcessPlan(
        plan_id=str(uuid.uuid4()),
        intent=intent,
        steps=[step_def],
        total_estimated_time_minutes=step.estimated_time_minutes,
        total_estimated_cost_usd=selected.estimated_cost_usd,
    )

    work_order = WorkOrder(
        work_order_id=str(uuid.uuid4()),
        intent=intent,
        process_plan=plan,
        steps=[step],
        status=WorkOrderStatus.DRAFT,
        priority=intent.priority,
        total_estimated_cost_usd=selected.estimated_cost_usd,
    )

    return WorkOrderOut(
        work_order_id=work_order.work_order_id,
        part_id=intent.part_id,
        part_name=intent.part_name,
        status=work_order.status.value,
        priority=work_order.priority,
        step_count=len(work_order.steps),
        steps=[
            WorkOrderStepOut(
                step_number=s.step_number,
                process_family=s.process_family.value,
                machine_id=s.machine_id,
                status=s.status.value,
                setup_sheet=s.setup_sheet,
                estimated_time_minutes=s.estimated_time_minutes,
            )
            for s in work_order.steps
        ],
        total_estimated_cost_usd=work_order.total_estimated_cost_usd,
        due_date=work_order.due_date,
        created_at=work_order.created_at,
    )


@router.get(
    "/work-orders",
    response_model=List[Dict[str, Any]],
    summary="List work orders (placeholder — no DB persistence yet)",
)
async def list_work_orders() -> List[Dict[str, Any]]:
    """
    Placeholder endpoint — returns empty list until a WorkOrder DB model
    is added. Will be wired to the DB in a future iteration.
    """
    return []


@router.post(
    "/estimate",
    response_model=EstimateOut,
    summary="Estimate cycle time and cost for a specific process",
)
async def estimate_process(body: EstimateRequest) -> EstimateOut:
    """
    Given a ManufacturingIntent and a specific process_family, return
    the estimated cycle time, cost, and energy profile.

    Uses the best available machine for the process. If no machine is
    registered, a synthetic dummy machine is used as a fallback.
    """
    registry = _get_registry()
    intent = _intent_from_request(body.intent)

    try:
        process_family = ProcessFamily(body.process_family)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown process_family: '{body.process_family}'"
        )

    adapter = registry.get_adapter(process_family)
    if adapter is None:
        raise HTTPException(
            status_code=404,
            detail=f"No adapter registered for process '{process_family.value}'."
        )

    # Find a capable machine, or fall back to a synthetic dummy
    machines = registry.find_capable_machines_any_material(process_family)
    if machines:
        machine = machines[0]
    else:
        machine = MachineCapability(
            machine_id="_estimate_fallback",
            machine_name="Synthetic Estimate Machine",
            machine_type="GENERIC",
            capabilities=[],
        )

    cycle_time = adapter.estimate_cycle_time(intent, machine)
    cost = adapter.estimate_cost(intent, machine)
    setup_time = adapter.estimate_setup_time(intent, machine)
    energy = adapter.get_energy_profile(intent, machine)

    return EstimateOut(
        part_id=intent.part_id,
        process_family=process_family.value,
        machine_id=machine.machine_id if machine.machine_id != "_estimate_fallback" else None,
        estimated_cycle_time_minutes=cycle_time,
        estimated_cost_usd=cost,
        setup_time_minutes=setup_time,
        energy_profile={
            "base_power_kw": energy.base_power_kw,
            "peak_power_kw": energy.peak_power_kw,
            "idle_power_kw": energy.idle_power_kw,
            "average_power_kw": energy.average_power_kw,
            "duty_cycle": energy.duty_cycle,
            "power_curve_type": energy.power_curve_type,
        },
    )


# ---------------------------------------------------------------------------
# Agentic endpoints — LLM-powered manufacturing intelligence
# ---------------------------------------------------------------------------


@router.post(
    "/analyze",
    summary="LLM-powered manufacturing analysis",
    description=(
        "Submit a manufacturing intent for full agentic analysis: "
        "material research, process recommendation, quality risk assessment, "
        "and setup sheet generation. All powered by Ollama — zero hardcoded logic."
    ),
)
async def analyze_intent(request: Request):
    """
    Full agentic manufacturing analysis pipeline.
    Uses Ollama + web research for every decision.
    """
    from manufacturing.agent import (
        advise_routing,
        advise_validation,
        assess_quality_risk,
        generate_setup_sheet,
        plan_work_order,
        research_material,
    )
    import json as _json

    body = await request.json()

    material_name = body.get("material", "steel")
    process = body.get("process", "cnc_milling")
    quantity = body.get("quantity", 1)
    tolerance = body.get("tolerance_class", "ISO_2768_m")
    part_id = body.get("part_id", "ANALYSIS-001")

    intent_json = _json.dumps({
        "part_id": part_id,
        "material": {"material_name": material_name, "material_family": "unknown"},
        "quantity": quantity,
        "tolerance_class": tolerance,
        "priority": body.get("priority", 5),
        "cost_target_usd": body.get("cost_target_usd"),
    })

    results = {}

    # 1. Material research (web + LLM)
    mat_data = research_material(material_name)
    results["material_research"] = mat_data

    # 2. Validation advisory
    validation = advise_validation(intent_json, process)
    results["validation"] = validation

    # 3. Quality risk assessment
    quality = assess_quality_risk(process, material_name, tolerance, quantity)
    results["quality_risk"] = quality

    # 4. Work order planning
    plan = plan_work_order(intent_json)
    results["work_order_plan"] = plan

    # 5. Setup sheet generation
    machine_name = body.get("machine", "Default Machine")
    setup = generate_setup_sheet(intent_json, process, machine_name)
    results["setup_sheet"] = setup

    return {
        "part_id": part_id,
        "material": material_name,
        "process": process,
        "analysis": results,
        "source": "ollama_agent",
        "note": "All analysis generated by LLM + web research. No hardcoded logic.",
    }
