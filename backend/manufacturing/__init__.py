"""
Manufacturing Package — MillForge AI Core Abstraction Layer
=============================================================
Provides the unified ontology, registry, routing engine, work order model,
validation, simulation, and process adapters for all manufacturing operations.

Quick start:
    from manufacturing import (
        ManufacturingIntent, MaterialSpec, ProcessFamily,
        ProcessRegistry, RoutingEngine,
        WorkOrder, WorkOrderStatus,
        CNCMillingAdapter, ArcWeldingAdapter, PressBrakeAdapter,
        FeasibilityChecker,
    )

    # 1. Bootstrap the registry
    registry = ProcessRegistry.get_instance()
    registry.register_adapter(CNCMillingAdapter())
    registry.register_adapter(ArcWeldingAdapter())
    registry.register_adapter(PressBrakeAdapter())

    # 2. Register machines
    from manufacturing.registry import MachineCapability, ProcessCapability
    registry.register_machine(
        MachineCapability(
            machine_id="VMC-001",
            machine_name="Haas VF-2",
            machine_type="VMC",
            capabilities=[
                ProcessCapability(
                    process_family=ProcessFamily.CNC_MILLING,
                    supported_materials=["steel", "aluminum", "copper"],
                    tolerances={"position_mm": 0.005, "surface_ra_um": 0.8},
                    setup_time_range_minutes=(15, 90),
                )
            ],
        )
    )

    # 3. Build an intent
    intent = ManufacturingIntent(
        part_id="PN-00123",
        part_name="Bracket Assembly",
        target_quantity=50,
        material=MaterialSpec(material_name="aluminum", material_family="non_ferrous", form="plate"),
        required_processes=[ProcessFamily.CNC_MILLING],
    )

    # 4. Route
    engine = RoutingEngine(registry)
    result = engine.route(intent)
    print(result.selected)

Module structure:
    manufacturing/
        __init__.py         ← you are here
        ontology.py         ← ProcessFamily, MaterialSpec, ManufacturingIntent, ProcessPlan, …
        registry.py         ← ProcessRegistry, ProcessAdapter, MachineCapability
        routing.py          ← RoutingEngine, RouteOption, RoutingResult
        work_order.py       ← WorkOrder, WorkOrderStep, WorkOrderStatus
        validation.py       ← validate_intent, validate_work_order, validate_process_step
        simulation.py       ← CycleTimeEstimator, CostEstimator, FeasibilityChecker
        adapters/
            __init__.py
            base_adapter.py ← BaseAdapter + shared constants
            cnc_milling.py  ← CNCMillingAdapter
            welding.py      ← ArcWeldingAdapter, LaserWeldingAdapter, EBWeldingAdapter
            bending.py      ← PressBrakeAdapter
"""

# Ontology
from .ontology import (
    EnergyProfile,
    FixtureSpec,
    ManufacturingIntent,
    MaterialSpec,
    ProcessCategory,
    ProcessConstraints,
    ProcessFamily,
    ProcessPlan,
    ProcessStepDefinition,
    QualityRequirement,
    ToolingSpec,
)

# Registry
from .registry import (
    MachineCapability,
    ProcessAdapter,
    ProcessCapability,
    ProcessRegistry,
)

# Routing
from .routing import (
    RouteOption,
    RoutingEngine,
    RoutingResult,
)

# Work Order
from .work_order import (
    WorkOrder,
    WorkOrderStatus,
    WorkOrderStep,
)

# Validation
from .validation import (
    validate_intent,
    validate_process_step,
    validate_work_order,
)

# Simulation
from .simulation import (
    CostEstimator,
    CycleTimeEstimator,
    FeasibilityChecker,
    FeasibilityResult,
)

# Adapters — concrete implementations
from .adapters import (
    ArcWeldingAdapter,
    BaseAdapter,
    CNCMillingAdapter,
    EBWeldingAdapter,
    KG_PER_UNIT,
    LaserWeldingAdapter,
    MACHINE_POWER_KW,
    SETUP_MATRIX,
    THROUGHPUT,
    PressBrakeAdapter,
    get_welding_adapter,
)


__all__ = [
    # Ontology
    "ProcessFamily",
    "ProcessCategory",
    "MaterialSpec",
    "ToolingSpec",
    "FixtureSpec",
    "QualityRequirement",
    "EnergyProfile",
    "ProcessConstraints",
    "ProcessStepDefinition",
    "ManufacturingIntent",
    "ProcessPlan",
    # Registry
    "ProcessCapability",
    "MachineCapability",
    "ProcessAdapter",
    "ProcessRegistry",
    # Routing
    "RouteOption",
    "RoutingResult",
    "RoutingEngine",
    # Work Order
    "WorkOrderStatus",
    "WorkOrderStep",
    "WorkOrder",
    # Validation
    "validate_intent",
    "validate_work_order",
    "validate_process_step",
    # Simulation
    "CycleTimeEstimator",
    "CostEstimator",
    "FeasibilityResult",
    "FeasibilityChecker",
    # Adapters
    "BaseAdapter",
    "CNCMillingAdapter",
    "ArcWeldingAdapter",
    "LaserWeldingAdapter",
    "EBWeldingAdapter",
    "PressBrakeAdapter",
    "get_welding_adapter",
    # Constants (backward compat with existing agents)
    "SETUP_MATRIX",
    "THROUGHPUT",
    "MACHINE_POWER_KW",
    "KG_PER_UNIT",
]

__version__ = "1.0.0"
