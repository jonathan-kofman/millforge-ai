"""
Bridge between the new manufacturing abstraction layer and existing MillForge agents.

This module provides functions to:
1. Convert existing Order dataclass to ManufacturingIntent and back
2. Wrap existing SETUP_MATRIX/THROUGHPUT lookups in the process adapter pattern
3. Register existing CNC machines from the Machine DB model
4. Allow the existing scheduler to use process-aware setup/throughput when available

Design contract:
  - All functions in this module are SAFE to call even if the manufacturing
    layer is not fully bootstrapped. Each function falls back gracefully to
    the original scheduler constants when adapters or machines are absent.
  - No imports from FastAPI, SQLAlchemy, or any async framework at module
    level — this file must be importable from Celery tasks and CLI scripts.
  - Thread-safe: relies on ProcessRegistry's internal locking.

Typical usage in scheduler:
    from manufacturing.bridge import (
        bootstrap_registry,
        order_to_intent,
        setup_matrix_from_registry,
        throughput_from_registry,
    )

    registry = bootstrap_registry()
    intent = order_to_intent(order)
    setup_time = setup_matrix_from_registry(registry, "steel", "aluminum")
    throughput  = throughput_from_registry(registry, "steel")
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from .ontology import (
    ManufacturingIntent,
    MaterialSpec,
    ProcessFamily,
)
from .registry import (
    MachineCapability,
    ProcessCapability,
    ProcessRegistry,
)
from .adapters.base_adapter import (
    BASE_SETUP_MINUTES,
    SETUP_MATRIX,
    THROUGHPUT,
)

if TYPE_CHECKING:
    # Import Order only for type hints — avoids circular dependency at runtime
    # if this module is imported before agents.scheduler is loaded.
    from agents.scheduler import Order

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default process family assumed for scheduler orders that don't specify one
# ---------------------------------------------------------------------------

CNC_MILLING = ProcessFamily.CNC_MILLING


# ---------------------------------------------------------------------------
# Order ↔ ManufacturingIntent conversion
# ---------------------------------------------------------------------------


def order_to_intent(order: "Order") -> ManufacturingIntent:
    """
    Convert a legacy scheduler Order dataclass into a ManufacturingIntent.

    Field mapping:
        order.order_id    → intent.part_id
        order.material    → intent.material.material_name (and normalized)
        order.quantity    → intent.target_quantity
        order.dimensions  → parsed into MaterialSpec width/length/thickness
        order.due_date    → intent.due_date
        order.priority    → intent.priority
        order.complexity  → intent.custom_metadata["complexity"]

    The resulting intent always has required_processes=[CNC_MILLING] since
    that is the only process supported by the legacy scheduler.

    Args:
        order: A scheduler.Order dataclass instance.

    Returns:
        ManufacturingIntent populated from the order fields.

    Raises:
        ValueError: if order.order_id or order.material is empty.
    """
    if not order.order_id or not order.order_id.strip():
        raise ValueError("order.order_id must be a non-empty string")
    if not order.material or not order.material.strip():
        raise ValueError("order.material must be a non-empty string")

    # Determine material family from material name heuristic
    mat_name_lower = order.material.lower().strip()
    material_family = _infer_material_family(mat_name_lower)

    # Parse dimensions string like "100x50x5mm" → (length, width, thickness)
    length_mm, width_mm, thickness_mm = _parse_dimensions(order.dimensions)

    material = MaterialSpec(
        material_name=order.material,
        alloy_designation=None,
        material_family=material_family,
        form="bar_stock",
        thickness_mm=thickness_mm,
        width_mm=width_mm,
        length_mm=length_mm,
    )

    # Normalize due_date to naive UTC for consistency with ontology
    due_date = order.due_date
    if due_date is not None and hasattr(due_date, "tzinfo") and due_date.tzinfo is not None:
        due_date = due_date.replace(tzinfo=None)

    return ManufacturingIntent(
        part_id=order.order_id,
        part_name=order.order_id,
        description=f"Converted from scheduler Order {order.order_id}",
        target_quantity=max(1, int(order.quantity)),
        material=material,
        required_processes=[CNC_MILLING],
        due_date=due_date,
        priority=int(getattr(order, "priority", 5)),
        custom_metadata={
            "complexity": float(getattr(order, "complexity", 1.0)),
            "source": "scheduler_bridge",
            "original_dimensions": order.dimensions,
        },
    )


def intent_to_order(intent: ManufacturingIntent) -> "Order":
    """
    Convert a ManufacturingIntent back into a legacy scheduler Order.

    This is a lossy conversion — only fields that exist on Order are preserved.
    Quality requirements, forbidden processes, geometry references, etc. are dropped.

    Field mapping:
        intent.part_id             → order.order_id
        intent.material.material_name → order.material
        intent.target_quantity     → order.quantity
        intent.material dims       → order.dimensions (reconstructed string)
        intent.due_date            → order.due_date
        intent.priority            → order.priority
        custom_metadata.complexity → order.complexity

    Args:
        intent: A ManufacturingIntent to convert.

    Returns:
        An Order dataclass compatible with agents.scheduler.

    Raises:
        ImportError: if agents.scheduler cannot be imported.
    """
    try:
        from agents.scheduler import Order
    except ImportError as exc:
        raise ImportError(
            "Cannot import agents.scheduler.Order — ensure the backend package is on sys.path. "
            f"Original error: {exc}"
        ) from exc

    dimensions = _build_dimensions_string(
        length_mm=intent.material.length_mm,
        width_mm=intent.material.width_mm,
        thickness_mm=intent.material.thickness_mm,
    )
    complexity = float(intent.custom_metadata.get("complexity", 1.0))

    # Restore timezone-naive due_date
    due_date = intent.due_date
    if due_date is None:
        # Default: 7 days from now if not specified
        due_date = datetime.utcnow().replace(microsecond=0)

    return Order(
        order_id=intent.part_id,
        material=intent.material.material_name,
        quantity=intent.target_quantity,
        dimensions=dimensions,
        due_date=due_date,
        priority=intent.priority,
        complexity=complexity,
    )


# ---------------------------------------------------------------------------
# Registry-aware setup/throughput lookups
# ---------------------------------------------------------------------------


def setup_matrix_from_registry(
    registry: ProcessRegistry,
    from_material: str,
    to_material: str,
    process_family: ProcessFamily = CNC_MILLING,
) -> int:
    """
    Return the sequence-dependent setup time in minutes for a material changeover.

    Lookup order:
      1. If a ProcessAdapter is registered for process_family, call
         adapter.estimate_setup_time() via a minimal synthetic intent + machine.
      2. Fall back to SETUP_MATRIX[from_material, to_material].
      3. Fall back to BASE_SETUP_MINUTES if the pair is not in SETUP_MATRIX.

    Args:
        registry:       The ProcessRegistry to query.
        from_material:  The material the machine is currently set up for.
        to_material:    The material of the incoming order.
        process_family: Which process family to query (default: CNC_MILLING).

    Returns:
        Setup time in minutes as an integer.
    """
    from_mat = from_material.lower().strip()
    to_mat = to_material.lower().strip()

    adapter = registry.get_adapter(process_family)
    if adapter is not None:
        try:
            # Build a minimal synthetic intent for the target material
            synthetic_intent = _make_minimal_intent(to_mat, process_family)
            # Build a minimal machine with last_material populated
            synthetic_machine = MachineCapability(
                machine_id="_bridge_lookup",
                machine_name="Bridge Lookup Machine",
                machine_type="VMC",
                capabilities=[],
                custom_attributes={"last_material": from_mat},
            )
            setup_time = adapter.estimate_setup_time(synthetic_intent, synthetic_machine)
            return int(round(setup_time))
        except Exception as exc:
            logger.warning(
                "setup_matrix_from_registry: adapter raised for %s→%s on %s: %s",
                from_mat, to_mat, process_family.value, exc,
            )

    # Fall back to SETUP_MATRIX constant
    key = (from_mat, to_mat)
    return int(SETUP_MATRIX.get(key, BASE_SETUP_MINUTES))


def throughput_from_registry(
    registry: ProcessRegistry,
    material: str,
    process_family: ProcessFamily = CNC_MILLING,
) -> float:
    """
    Return the throughput in units/hour for a material on the given process.

    Lookup order:
      1. If a ProcessAdapter is registered and a machine is available, call
         adapter.estimate_cycle_time() for a 1-unit batch and convert.
      2. Fall back to THROUGHPUT[material].
      3. Fall back to 3.0 units/hour (safe default).

    Args:
        registry:       The ProcessRegistry to query.
        material:       The material name (e.g. "steel").
        process_family: Which process family to query (default: CNC_MILLING).

    Returns:
        Throughput in units/hour (float > 0).
    """
    mat = material.lower().strip()

    adapter = registry.get_adapter(process_family)
    if adapter is not None:
        # Find any capable machine to base the estimate on
        machines = registry.find_capable_machines(process_family, mat)
        if not machines:
            machines = registry.find_capable_machines_any_material(process_family)

        if machines:
            try:
                synthetic_intent = _make_minimal_intent(mat, process_family)
                cycle_minutes_per_unit = adapter.estimate_cycle_time(synthetic_intent, machines[0])
                if cycle_minutes_per_unit > 0:
                    return 60.0 / cycle_minutes_per_unit  # convert minutes/unit → units/hour
            except Exception as exc:
                logger.warning(
                    "throughput_from_registry: adapter raised for %s on %s: %s",
                    mat, process_family.value, exc,
                )

    # Fall back to THROUGHPUT constant
    return float(THROUGHPUT.get(mat, 3.0))


# ---------------------------------------------------------------------------
# DB machine registration
# ---------------------------------------------------------------------------


def register_db_machines(registry: ProcessRegistry, db_session: Any) -> int:
    """
    Read Machine rows from the database and register them in the ProcessRegistry.

    Each DB Machine record is treated as a CNC milling VMC with:
      - All materials supported (open list)
      - 600×400×300mm work envelope
      - Standard ISO 2768-m tolerances
      - is_available mirrors Machine.is_available

    Call this once at startup (e.g. in app lifespan) to warm the registry.

    Args:
        registry:   The ProcessRegistry to populate.
        db_session: An active SQLAlchemy Session with access to the Machine table.

    Returns:
        The number of Machine records registered.

    Raises:
        ImportError: if db_models cannot be imported.
    """
    try:
        from db_models import Machine
    except ImportError as exc:
        raise ImportError(
            f"register_db_machines: cannot import db_models.Machine — {exc}"
        ) from exc

    machines: List[Any] = db_session.query(Machine).all()
    count = 0

    for db_machine in machines:
        machine_id = f"DB-{db_machine.id}"
        machine_type = db_machine.machine_type or "VMC"

        # Infer supported process families from machine_type string
        supported_families = _infer_process_families(machine_type)

        capabilities = [
            ProcessCapability(
                process_family=family,
                supported_materials=[],  # empty = accept all
                max_part_dimensions_mm=(600.0, 400.0, 300.0),
                tolerances={"position_mm": 0.05},
                throughput_range=(2.0, 6.0),
                setup_time_range_minutes=(15.0, 90.0),
            )
            for family in supported_families
        ]

        machine_cap = MachineCapability(
            machine_id=machine_id,
            machine_name=db_machine.name,
            machine_type=machine_type,
            capabilities=capabilities,
            is_available=bool(db_machine.is_available),
            custom_attributes={
                "db_id": db_machine.id,
                "notes": db_machine.notes or "",
                "created_at": db_machine.created_at.isoformat() if db_machine.created_at else None,
            },
        )

        registry.register_machine(machine_cap)
        count += 1
        logger.debug("Registered DB machine: %s (%s)", machine_id, db_machine.name)

    logger.info("register_db_machines: registered %d machines from DB.", count)
    return count


# ---------------------------------------------------------------------------
# Bootstrap helper
# ---------------------------------------------------------------------------


def bootstrap_registry() -> ProcessRegistry:
    """
    Create a ProcessRegistry with all built-in adapters registered.

    Registers (16 total):
      - CNCMillingAdapter          → ProcessFamily.CNC_MILLING
      - ArcWeldingAdapter          → ProcessFamily.WELDING_ARC
      - LaserWeldingAdapter        → ProcessFamily.WELDING_LASER
      - EBWeldingAdapter           → ProcessFamily.WELDING_EBW
      - PressBrakeAdapter          → ProcessFamily.BENDING_PRESS_BRAKE
      - LaserCuttingAdapter        → ProcessFamily.CUTTING_LASER
      - PlasmaCuttingAdapter       → ProcessFamily.CUTTING_PLASMA
      - WaterjetCuttingAdapter     → ProcessFamily.CUTTING_WATERJET
      - StampingAdapter            → ProcessFamily.STAMPING
      - WireEDMAdapter             → ProcessFamily.EDM_WIRE
      - SinkerEDMAdapter           → ProcessFamily.EDM_SINKER
      - InjectionMoldingAdapter    → ProcessFamily.INJECTION_MOLDING
      - CMMInspectionAdapter       → ProcessFamily.INSPECTION_CMM
      - VisionInspectionAdapter    → ProcessFamily.INSPECTION_VISION
      - XRayInspectionAdapter      → ProcessFamily.INSPECTION_XRAY

    This does NOT register machines — use register_db_machines() or
    registry.register_machine() to add physical machines after bootstrapping.

    Returns:
        The global ProcessRegistry singleton with all built-in adapters registered.

    Example::

        from manufacturing.bridge import bootstrap_registry
        registry = bootstrap_registry()
        # then register machines...
        from manufacturing.bridge import register_db_machines
        register_db_machines(registry, db_session)
    """
    from .adapters.cnc_milling import CNCMillingAdapter
    from .adapters.welding import ArcWeldingAdapter, EBWeldingAdapter, LaserWeldingAdapter
    from .adapters.bending import PressBrakeAdapter
    from .adapters.cutting import (
        LaserCuttingAdapter,
        PlasmaCuttingAdapter,
        WaterjetCuttingAdapter,
    )
    from .adapters.stamping import StampingAdapter
    from .adapters.edm import WireEDMAdapter, SinkerEDMAdapter
    from .adapters.molding import InjectionMoldingAdapter
    from .adapters.inspection import (
        CMMInspectionAdapter,
        VisionInspectionAdapter,
        XRayInspectionAdapter,
    )

    registry = ProcessRegistry.get_instance()

    adapters = [
        # Original 5
        CNCMillingAdapter(),
        ArcWeldingAdapter(),
        LaserWeldingAdapter(),
        EBWeldingAdapter(),
        PressBrakeAdapter(),
        # New cutting adapters
        LaserCuttingAdapter(),
        PlasmaCuttingAdapter(),
        WaterjetCuttingAdapter(),
        # Forming
        StampingAdapter(),
        # EDM
        WireEDMAdapter(),
        SinkerEDMAdapter(),
        # Molding
        InjectionMoldingAdapter(),
        # Inspection
        CMMInspectionAdapter(),
        VisionInspectionAdapter(),
        XRayInspectionAdapter(),
    ]

    for adapter in adapters:
        registry.register_adapter(adapter)
        logger.debug("bootstrap_registry: registered adapter for %s", adapter.process_family.value)

    logger.info(
        "bootstrap_registry: %d adapters registered (%s).",
        len(adapters),
        ", ".join(a.process_family.value for a in adapters),
    )

    return registry


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _infer_material_family(material_name: str) -> str:
    """
    Infer a broad material family from a normalized material name string.

    Maps common scheduler material tokens to ontology material_family values.
    Falls back to "ferrous" (the most common family in the original scheduler).
    """
    name = material_name.lower().strip()

    _FERROUS = {"steel", "iron", "carbon_steel", "tool_steel", "stainless", "stainless_steel",
                "cast_iron", "spring_steel", "hardox"}
    _NON_FERROUS = {"aluminum", "aluminium", "copper", "titanium", "brass", "bronze", "nickel",
                   "inconel", "zinc", "magnesium"}
    _POLYMER = {"nylon", "abs", "pvc", "ptfe", "hdpe", "ldpe", "polypropylene",
                "polycarbonate", "peek", "acetal", "delrin", "plastic", "polymer"}
    _COMPOSITE = {"carbon_fiber", "fiberglass", "carbon_fibre", "composite", "cfrp", "gfrp"}

    if name in _FERROUS or "steel" in name or "iron" in name:
        return "ferrous"
    if name in _NON_FERROUS or "aluminum" in name or "aluminium" in name or "titanium" in name:
        return "non_ferrous"
    if name in _POLYMER:
        return "polymer"
    if name in _COMPOSITE:
        return "composite"
    return "ferrous"  # safe default for legacy scheduler (all orders were metals)


def _parse_dimensions(dimensions_str: Optional[str]) -> tuple:
    """
    Parse a scheduler dimension string like "100x50x5mm" into (length, width, thickness).

    Returns (None, None, None) if parsing fails or string is empty/None.
    Handles both "100x50x5mm" and "100 x 50 x 5 mm" and "100x50x5" formats.
    """
    if not dimensions_str:
        return None, None, None

    try:
        # Strip units and whitespace
        clean = dimensions_str.lower().replace("mm", "").replace(" ", "")
        parts = clean.split("x")
        if len(parts) == 3:
            return float(parts[0]), float(parts[1]), float(parts[2])
        elif len(parts) == 2:
            return float(parts[0]), float(parts[1]), None
    except (ValueError, AttributeError):
        pass

    return None, None, None


def _build_dimensions_string(
    length_mm: Optional[float],
    width_mm: Optional[float],
    thickness_mm: Optional[float],
) -> str:
    """
    Build a scheduler-compatible dimension string from individual dimensions.
    Falls back to a generic placeholder if all values are None.
    """
    parts = []
    for val in [length_mm, width_mm, thickness_mm]:
        if val is not None:
            parts.append(str(int(val)) if val == int(val) else str(val))

    if len(parts) == 3:
        return f"{parts[0]}x{parts[1]}x{parts[2]}mm"
    if len(parts) == 2:
        return f"{parts[0]}x{parts[1]}mm"
    return "unknown"


def _make_minimal_intent(material_name: str, process_family: ProcessFamily) -> ManufacturingIntent:
    """
    Build a single-unit ManufacturingIntent for a given material and process.
    Used internally for adapter method calls that require an intent object.
    """
    return ManufacturingIntent(
        part_id="_bridge_lookup",
        part_name="_bridge_lookup",
        target_quantity=1,
        material=MaterialSpec(
            material_name=material_name,
            material_family=_infer_material_family(material_name),
            form="bar_stock",
        ),
        required_processes=[process_family],
        custom_metadata={"source": "bridge_lookup"},
    )


def _infer_process_families(machine_type: str) -> List[ProcessFamily]:
    """
    Map a DB machine_type string to a list of ProcessFamily values.

    Provides a best-effort mapping based on common machine type naming conventions.
    Defaults to [CNC_MILLING] for unknown types (safe assumption for existing DB machines).
    """
    mt = machine_type.upper().strip()

    # Machining centers
    if any(token in mt for token in ["VMC", "HMC", "CNC", "MILLING", "MACHINING_CENTER"]):
        return [ProcessFamily.CNC_MILLING]

    # Turning / lathes
    if any(token in mt for token in ["LATHE", "TURNING", "CNC_LATHE"]):
        return [ProcessFamily.CNC_TURNING]

    # Welding
    if "MIG" in mt or "TIG" in mt or "SMAW" in mt or "WELDING_ARC" in mt or "ARC_WELD" in mt:
        return [ProcessFamily.WELDING_ARC]
    if "LASER_WELD" in mt:
        return [ProcessFamily.WELDING_LASER]
    if "EBW" in mt or "ELECTRON_BEAM" in mt:
        return [ProcessFamily.WELDING_EBW]

    # Press brake / forming
    if "PRESS_BRAKE" in mt or "PRESS BRAKE" in mt or "BENDING" in mt:
        return [ProcessFamily.BENDING_PRESS_BRAKE]

    # Laser / plasma / waterjet cutting
    if "LASER_CUT" in mt or "LASER CUT" in mt:
        return [ProcessFamily.CUTTING_LASER]
    if "PLASMA" in mt:
        return [ProcessFamily.CUTTING_PLASMA]
    if "WATERJET" in mt or "WATER JET" in mt:
        return [ProcessFamily.CUTTING_WATERJET]

    # Inspection
    if "CMM" in mt:
        return [ProcessFamily.INSPECTION_CMM]

    logger.debug("_infer_process_families: unknown machine type %r — defaulting to CNC_MILLING", machine_type)
    return [ProcessFamily.CNC_MILLING]
