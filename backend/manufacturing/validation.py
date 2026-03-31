"""
Unified Manufacturing Validation Layer
=========================================
Cross-cutting validation for manufacturing intents, work orders, and process steps.

Validation philosophy:
  - Errors are returned as strings, never raised as exceptions.
    Callers decide what to do with errors (reject, warn, or log).
  - Validation is layered: structural (Pydantic) → semantic (this module).
  - Each function is idempotent and stateless.

These validators complement Pydantic's field-level validation with
cross-entity, registry-aware, and domain-specific checks.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from .ontology import (
    ManufacturingIntent,
    MaterialSpec,
    ProcessFamily,
    ProcessStepDefinition,
    QualityRequirement,
)
from .registry import ProcessRegistry
from .work_order import WorkOrder, WorkOrderStatus

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Material families that cannot be cut by laser (reflective)
_LASER_INCOMPATIBLE = {"copper", "brass", "gold", "silver", "highly_reflective_aluminum"}

# Processes that require a dedicated atmosphere controller
_ATMOSPHERE_REQUIRED = {
    ProcessFamily.WELDING_EBW,
    ProcessFamily.WELDING_LASER,
    ProcessFamily.ADDITIVE_DMLS,
    ProcessFamily.ADDITIVE_SLS,
    ProcessFamily.HEAT_TREATMENT,
}

# Processes that absolutely cannot handle polymers
_NO_POLYMER = {
    ProcessFamily.CNC_MILLING,
    ProcessFamily.CNC_TURNING,
    ProcessFamily.CNC_DRILLING,
    ProcessFamily.WELDING_ARC,
    ProcessFamily.WELDING_EBW,
    ProcessFamily.WELDING_FRICTION_STIR,
    ProcessFamily.EDM_WIRE,
    ProcessFamily.EDM_SINKER,
    ProcessFamily.DIE_FORGING,
}

# Minimum quantity requirements by process
_MIN_QUANTITY: dict[ProcessFamily, int] = {
    ProcessFamily.INJECTION_MOLDING: 50,
    ProcessFamily.BLOW_MOLDING: 50,
    ProcessFamily.DIE_CASTING: 20,
    ProcessFamily.STAMPING: 10,
}

# Maximum priority for rush jobs (warn if tighter deadlines are unrealistic)
_WARN_PRIORITY_THRESHOLD = 2


# ---------------------------------------------------------------------------
# Intent Validation
# ---------------------------------------------------------------------------


def validate_intent(
    intent: ManufacturingIntent,
    registry: ProcessRegistry,
) -> List[str]:
    """
    Validate a ManufacturingIntent against registry capabilities and
    domain rules. Returns a list of human-readable error strings.
    An empty list means the intent is valid.

    Checks performed:
      1. Quantity > 0 (Pydantic ensures ≥ 1, but we double-check)
      2. Required processes are registered
      3. Required processes are not forbidden
      4. Material-process compatibility
      5. Minimum batch size enforcement for high-setup processes
      6. Due date is in the future
      7. Cost target is positive if set
      8. Quality requirements are internally consistent
      9. At least one capable machine exists for each required process
    """
    errors: List[str] = []

    # 1. Quantity sanity
    if intent.target_quantity < 1:
        errors.append(f"target_quantity must be ≥ 1 (got {intent.target_quantity})")

    # 2. Required processes are registered
    if intent.required_processes:
        supported = set(registry.list_supported_processes())
        for pf in intent.required_processes:
            if pf not in supported:
                errors.append(
                    f"Required process '{pf.value}' has no registered adapter. "
                    f"Register a ProcessAdapter for it before routing."
                )

    # 3. Required / forbidden overlap (also validated by Pydantic, but be explicit)
    if intent.required_processes and intent.forbidden_processes:
        overlap = set(intent.required_processes) & set(intent.forbidden_processes)
        for pf in overlap:
            errors.append(
                f"Process '{pf.value}' appears in both required_processes and "
                f"forbidden_processes — this is contradictory."
            )

    # 4. Material-process compatibility
    errors.extend(_validate_material_compatibility(intent))

    # 5. Minimum batch enforcement
    errors.extend(_validate_batch_requirements(intent))

    # 6. Due date
    if intent.due_date is not None:
        now = datetime.now(timezone.utc) if intent.due_date.tzinfo else datetime.utcnow()
        if intent.due_date < now:
            errors.append(
                f"due_date {intent.due_date.isoformat()} is in the past."
            )

    # 7. Cost target
    if intent.cost_target_usd is not None and intent.cost_target_usd <= 0:
        errors.append(
            f"cost_target_usd must be positive (got {intent.cost_target_usd})"
        )

    # 8. Quality requirements
    for i, qr in enumerate(intent.quality_requirements):
        errors.extend(_validate_quality_requirement(qr, context=f"quality_requirements[{i}]"))

    # 9. Capable machines
    if intent.required_processes:
        for pf in intent.required_processes:
            machines = registry.find_capable_machines(pf, intent.material.normalized_name)
            if not machines:
                errors.append(
                    f"No available machine is registered that can run '{pf.value}' "
                    f"on material '{intent.material.normalized_name}'."
                )

    # 10. LLM advisory validation — augments rule-based checks with
    #     web-researched material knowledge and process reasoning
    try:
        from manufacturing.agent import advise_validation
        import json as _json
        intent_data = {
            "part_id": intent.part_id,
            "material": {
                "material_name": intent.material.material_name,
                "material_family": intent.material.material_family,
            },
            "quantity": intent.target_quantity,
            "tolerance_class": intent.tolerance_class,
            "priority": intent.priority,
        }
        process_str = (
            intent.required_processes[0].value
            if intent.required_processes
            else "unspecified"
        )
        advice = advise_validation(_json.dumps(intent_data), process_str)
        if advice and advice.get("issues"):
            for issue in advice["issues"]:
                severity = issue.get("severity", "info")
                msg = issue.get("message", "")
                fix = issue.get("fix", "")
                if severity == "critical" and msg:
                    errors.append(f"[AI] {msg}" + (f" — Fix: {fix}" if fix else ""))
                elif severity == "warning" and msg:
                    logger.info("LLM validation warning: %s", msg)
    except Exception as exc:
        logger.debug("LLM validation advisory skipped: %s", exc)

    return errors


# ---------------------------------------------------------------------------
# Work Order Validation
# ---------------------------------------------------------------------------


def validate_work_order(
    work_order: WorkOrder,
    registry: ProcessRegistry,
) -> List[str]:
    """
    Validate a WorkOrder against registry capabilities and business rules.
    Returns a list of error strings; empty = valid.

    Checks:
      1. steps list is non-empty
      2. step numbers are contiguous starting at 1
      3. each step's process_family has a registered adapter
      4. assigned machines exist and are capable
      5. work order status is consistent with step statuses
      6. due_date matches intent if both set
    """
    errors: List[str] = []

    # 1. Non-empty steps
    if not work_order.steps:
        errors.append("WorkOrder has no steps. At least one ProcessStep is required.")

    # 2. Step number continuity
    if work_order.steps:
        expected = list(range(1, len(work_order.steps) + 1))
        actual = sorted(s.step_number for s in work_order.steps)
        if actual != expected:
            errors.append(
                f"Step numbers must be contiguous from 1. Got: {actual}"
            )

    # 3. Registered adapters + 4. Capable machines
    supported = set(registry.list_supported_processes())
    for step in work_order.steps:
        if step.process_family not in supported:
            errors.append(
                f"Step {step.step_number}: process '{step.process_family.value}' "
                f"has no registered adapter."
            )
        if step.machine_id is not None:
            machine = registry.get_machine(step.machine_id)
            if machine is None:
                errors.append(
                    f"Step {step.step_number}: assigned machine '{step.machine_id}' "
                    f"is not registered in the registry."
                )
            elif not machine.supports_process(step.process_family):
                errors.append(
                    f"Step {step.step_number}: machine '{step.machine_id}' does not "
                    f"support process '{step.process_family.value}'."
                )

    # 5. Status consistency
    errors.extend(_validate_work_order_status_consistency(work_order))

    # 6. Due date match
    if (
        work_order.due_date is not None
        and work_order.intent.due_date is not None
        and work_order.due_date != work_order.intent.due_date
    ):
        errors.append(
            "WorkOrder.due_date differs from ManufacturingIntent.due_date. "
            "Ensure they are in sync to avoid scheduling conflicts."
        )

    return errors


# ---------------------------------------------------------------------------
# Process Step Validation
# ---------------------------------------------------------------------------


def validate_process_step(
    step: ProcessStepDefinition,
    registry: ProcessRegistry,
) -> List[str]:
    """
    Validate a single ProcessStepDefinition.
    Returns a list of error strings; empty = valid.

    Checks:
      1. Registered adapter exists for the process family
      2. step_id is non-empty
      3. Cycle time and setup time are non-negative
      4. EnergyProfile values are physically plausible
      5. ProcessConstraints batch ranges are sensible
      6. Quality requirements are internally consistent
      7. Parameters validation via the adapter
    """
    errors: List[str] = []

    # 1. Registered adapter
    adapter = registry.get_adapter(step.process_family)
    if adapter is None:
        errors.append(
            f"No adapter registered for process '{step.process_family.value}'. "
            f"Cannot validate step '{step.step_id}'."
        )

    # 2. Non-empty step_id
    if not step.step_id.strip():
        errors.append("step_id must be a non-empty string.")

    # 3. Time values
    if step.estimated_cycle_time_minutes < 0:
        errors.append(
            f"estimated_cycle_time_minutes must be ≥ 0 (got {step.estimated_cycle_time_minutes})"
        )
    if step.setup_time_minutes < 0:
        errors.append(
            f"setup_time_minutes must be ≥ 0 (got {step.setup_time_minutes})"
        )

    # 4. Energy profile plausibility
    ep = step.energy
    if ep.peak_power_kw < ep.base_power_kw:
        errors.append(
            f"EnergyProfile: peak_power_kw ({ep.peak_power_kw}) must be ≥ "
            f"base_power_kw ({ep.base_power_kw})"
        )
    if ep.base_power_kw < 0:
        errors.append("EnergyProfile: base_power_kw must be ≥ 0")
    if ep.idle_power_kw < 0:
        errors.append("EnergyProfile: idle_power_kw must be ≥ 0")

    # 5. Constraints
    c = step.constraints
    if c.max_batch_size is not None and c.max_batch_size < c.min_batch_size:
        errors.append(
            f"ProcessConstraints: max_batch_size ({c.max_batch_size}) < "
            f"min_batch_size ({c.min_batch_size})"
        )

    # 6. Quality requirements
    for i, qr in enumerate(step.quality_requirements):
        errors.extend(
            _validate_quality_requirement(qr, context=f"quality_requirements[{i}]")
        )

    # 7. Adapter-level validation if available
    if adapter is not None:
        # Build a minimal ManufacturingIntent for the adapter to validate against
        # (adapters expect an intent, not a step directly)
        dummy_intent = ManufacturingIntent(
            part_id="__validation__",
            part_name="__validation__",
            target_quantity=1,
            material=step.material_input,
            required_processes=[step.process_family],
            quality_requirements=step.quality_requirements,
        )
        adapter_errors = adapter.validate_intent(dummy_intent)
        for err in adapter_errors:
            errors.append(f"Adapter validation [{step.process_family.value}]: {err}")

    return errors


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _validate_material_compatibility(intent: ManufacturingIntent) -> List[str]:
    """Check process-material compatibility rules."""
    errors: List[str] = []
    mat = intent.material
    mat_family = mat.material_family.lower()
    mat_name = mat.normalized_name

    processes = (intent.required_processes or []) + (intent.preferred_processes or [])

    for pf in processes:
        # Polymer through metal-only processes
        if pf in _NO_POLYMER and mat_family == "polymer":
            errors.append(
                f"Process '{pf.value}' is incompatible with polymer materials "
                f"(material: '{mat_name}')."
            )

        # Laser cutting reflective metals
        if pf == ProcessFamily.CUTTING_LASER and mat_name in _LASER_INCOMPATIBLE:
            errors.append(
                f"CUTTING_LASER is not suitable for highly reflective material "
                f"'{mat_name}'. Consider CUTTING_WATERJET or CUTTING_PLASMA."
            )

        # EBW requires metals
        if pf == ProcessFamily.WELDING_EBW and mat_family not in {"ferrous", "non_ferrous"}:
            errors.append(
                f"WELDING_EBW requires metallic materials; '{mat_family}' is not supported."
            )

        # Injection molding requires polymer or composite
        if pf == ProcessFamily.INJECTION_MOLDING and mat_family not in {"polymer", "composite"}:
            errors.append(
                f"INJECTION_MOLDING requires polymer or composite materials "
                f"(got '{mat_family}')."
            )

    return errors


def _validate_batch_requirements(intent: ManufacturingIntent) -> List[str]:
    """Enforce minimum batch size for high-tooling-cost processes."""
    errors: List[str] = []
    processes = intent.required_processes or []
    for pf in processes:
        min_qty = _MIN_QUANTITY.get(pf)
        if min_qty is not None and intent.target_quantity < min_qty:
            errors.append(
                f"Process '{pf.value}' requires a minimum batch of {min_qty} units "
                f"to be economical (requested: {intent.target_quantity}). "
                f"Consider a different process for smaller runs."
            )
    return errors


def _validate_quality_requirement(
    qr: QualityRequirement, context: str = ""
) -> List[str]:
    """Validate a single QualityRequirement."""
    errors: List[str] = []
    prefix = f"{context}: " if context else ""

    if qr.surface_finish_ra is not None and qr.surface_finish_ra <= 0:
        errors.append(f"{prefix}surface_finish_ra must be > 0 µm")

    for dim in qr.critical_dimensions:
        if "feature" not in dim:
            errors.append(f"{prefix}critical_dimension entry missing 'feature' key: {dim}")
        if "nominal_mm" not in dim and "value" not in dim:
            errors.append(
                f"{prefix}critical_dimension entry missing 'nominal_mm' or 'value' key: {dim}"
            )

    return errors


def _validate_work_order_status_consistency(work_order: WorkOrder) -> List[str]:
    """
    Check that work order step statuses are consistent with the overall
    work order status.
    """
    errors: List[str] = []
    wo_status = work_order.status

    if wo_status == WorkOrderStatus.DRAFT:
        active_steps = [s for s in work_order.steps if s.status.is_active]
        if active_steps:
            errors.append(
                f"WorkOrder is in DRAFT status but {len(active_steps)} step(s) are "
                f"in active execution states."
            )

    if wo_status == WorkOrderStatus.COMPLETE:
        incomplete = [s for s in work_order.steps if not s.is_complete]
        if incomplete:
            errors.append(
                f"WorkOrder is marked COMPLETE but {len(incomplete)} step(s) are "
                f"not yet in a completed state."
            )

    if wo_status == WorkOrderStatus.CANCELLED:
        # Cancelled WOs can have steps in any state — just informational
        pass

    return errors
