"""
Manufacturing Simulation & Estimation Interface
=================================================
Provides cycle time, cost, and feasibility estimates for manufacturing intents.

These estimators are designed to be:
  - Registry-backed: use adapter domain knowledge when available
  - Fallback-capable: gracefully handle missing adapters with physics-based models
  - Composable: combine individual estimators in the RoutingEngine or other agents

Typical usage:
    from manufacturing.simulation import CycleTimeEstimator, CostEstimator, FeasibilityChecker
    from manufacturing.registry import ProcessRegistry

    registry = ProcessRegistry.get_instance()
    estimator = CycleTimeEstimator(registry)
    minutes = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from .ontology import (
    EnergyProfile,
    ManufacturingIntent,
    ProcessCategory,
    ProcessFamily,
)
from .registry import MachineCapability, ProcessRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default physics-based fallback models
# ---------------------------------------------------------------------------

# Fallback cycle time in minutes per unit, by process category
_FALLBACK_CYCLE_TIME_PER_UNIT: Dict[ProcessCategory, float] = {
    ProcessCategory.SUBTRACTIVE: 15.0,
    ProcessCategory.ADDITIVE: 60.0,
    ProcessCategory.JOINING: 20.0,
    ProcessCategory.FORMING: 5.0,
    ProcessCategory.CASTING_MOLDING: 3.0,
    ProcessCategory.INSPECTION: 10.0,
    ProcessCategory.MATERIAL_HANDLING: 2.0,
    ProcessCategory.THERMAL: 120.0,
    ProcessCategory.FINISHING: 8.0,
    ProcessCategory.ASSEMBLY: 30.0,
}

# Fallback energy profile by process category (kW)
_FALLBACK_ENERGY: Dict[ProcessCategory, Tuple[float, float, float]] = {
    # (base_kw, peak_kw, idle_kw)
    ProcessCategory.SUBTRACTIVE: (75.0, 110.0, 8.0),
    ProcessCategory.ADDITIVE: (5.0, 8.0, 1.0),
    ProcessCategory.JOINING: (35.0, 60.0, 5.0),
    ProcessCategory.FORMING: (45.0, 120.0, 3.0),
    ProcessCategory.CASTING_MOLDING: (80.0, 120.0, 10.0),
    ProcessCategory.INSPECTION: (3.0, 5.0, 1.0),
    ProcessCategory.MATERIAL_HANDLING: (2.0, 4.0, 0.5),
    ProcessCategory.THERMAL: (50.0, 70.0, 15.0),
    ProcessCategory.FINISHING: (10.0, 20.0, 2.0),
    ProcessCategory.ASSEMBLY: (1.0, 3.0, 0.5),
}

# Electricity rate used when not otherwise specified
DEFAULT_ENERGY_RATE_USD_KWH = 0.12

# Blended shop labor rate ($/hour) — includes burden
DEFAULT_LABOR_RATE_USD_HOUR = 75.0

# Tooling wear cost factor (fraction of energy cost)
TOOLING_WEAR_FACTOR = 0.15


# ---------------------------------------------------------------------------
# Cycle Time Estimator
# ---------------------------------------------------------------------------


class CycleTimeEstimator:
    """
    Estimates manufacturing cycle time in minutes for a given intent,
    process family, and machine.

    Estimation hierarchy:
      1. If a ProcessAdapter is registered, delegate to adapter.estimate_cycle_time().
      2. If the machine's ProcessCapability has throughput_range, use midpoint throughput.
      3. Fall back to _FALLBACK_CYCLE_TIME_PER_UNIT × quantity.
    """

    def __init__(self, registry: ProcessRegistry) -> None:
        self.registry = registry

    def estimate(
        self,
        intent: ManufacturingIntent,
        process_family: ProcessFamily,
        machine: MachineCapability,
    ) -> float:
        """
        Estimate cycle time in minutes (excludes setup time).

        Args:
            intent:         The manufacturing intent.
            process_family: Which process to estimate for.
            machine:        The target machine.

        Returns:
            Estimated cycle time in minutes (total for all units).
        """
        # 1. Adapter path
        adapter = self.registry.get_adapter(process_family)
        if adapter is not None:
            try:
                return adapter.estimate_cycle_time(intent, machine)
            except Exception as exc:
                logger.warning(
                    "CycleTimeEstimator: adapter raised for %s/%s: %s",
                    process_family.value,
                    machine.machine_id,
                    exc,
                )

        # 2. Capability throughput
        cap = machine.get_capability(process_family)
        if cap and cap.throughput_range:
            midpoint_throughput = (cap.throughput_range[0] + cap.throughput_range[1]) / 2.0
            if midpoint_throughput > 0:
                return (intent.target_quantity / midpoint_throughput) * 60.0

        # 3. Category-based fallback
        category = ProcessCategory.for_process(process_family)
        per_unit = _FALLBACK_CYCLE_TIME_PER_UNIT.get(category, 15.0)
        baseline = per_unit * intent.target_quantity

        # 4. LLM advisory — ask agent to review and adjust the estimate
        try:
            from manufacturing.agent import advise_estimation
            import json as _json
            intent_data = {
                "part_id": intent.part_id,
                "material": {
                    "material_name": intent.material.material_name,
                    "material_family": intent.material.material_family,
                },
                "quantity": intent.target_quantity,
                "tolerance_class": intent.tolerance_class,
            }
            advice = advise_estimation(
                _json.dumps(intent_data),
                process_family.value,
                baseline / max(intent.target_quantity, 1),  # per-unit
                0.0,  # cost not yet calculated at this stage
            )
            if advice and "adjustment_factor" in advice:
                factor = float(advice["adjustment_factor"])
                factor = max(0.5, min(factor, 3.0))  # clamp to reasonable range
                adjusted = baseline * factor
                logger.info(
                    "LLM adjusted cycle time for %s: %.1f → %.1f min (factor %.2f, confidence: %s)",
                    intent.part_id, baseline, adjusted, factor,
                    advice.get("confidence", "unknown"),
                )
                return adjusted
        except Exception as exc:
            logger.debug("LLM estimation advisory skipped: %s", exc)

        return baseline

    def estimate_with_complexity(
        self,
        intent: ManufacturingIntent,
        process_family: ProcessFamily,
        machine: MachineCapability,
        complexity_factor: float = 1.0,
    ) -> float:
        """Estimate cycle time with an explicit complexity multiplier."""
        base = self.estimate(intent, process_family, machine)
        return base * max(0.5, min(complexity_factor, 5.0))


# ---------------------------------------------------------------------------
# Cost Estimator
# ---------------------------------------------------------------------------


class CostEstimator:
    """
    Estimates manufacturing cost in USD for a given intent, process, and machine.

    Cost components:
      1. Energy cost = energy_kWh × energy_rate_usd_kwh
      2. Labor cost  = (cycle_time_hours) × labor_rate_usd_hour
      3. Tooling wear = tooling_wear_factor × energy_cost
      4. Consumables = from adapter if available

    Setup cost is NOT included here; it is treated separately by the scheduler.
    """

    def __init__(
        self,
        registry: ProcessRegistry,
        energy_rate_usd_kwh: float = DEFAULT_ENERGY_RATE_USD_KWH,
        labor_rate_usd_hour: float = DEFAULT_LABOR_RATE_USD_HOUR,
    ) -> None:
        self.registry = registry
        self.energy_rate = energy_rate_usd_kwh
        self.labor_rate = labor_rate_usd_hour
        self._cycle_estimator = CycleTimeEstimator(registry)

    def estimate(
        self,
        intent: ManufacturingIntent,
        process_family: ProcessFamily,
        machine: MachineCapability,
        energy_rate_usd_kwh: Optional[float] = None,
    ) -> float:
        """
        Estimate total job cost in USD (all units, excluding setup).

        Args:
            intent:              The manufacturing intent.
            process_family:      Which process to estimate for.
            machine:             The target machine.
            energy_rate_usd_kwh: Override the instance-level energy rate.

        Returns:
            Total cost estimate in USD.
        """
        rate = energy_rate_usd_kwh or self.energy_rate

        # 1. Try adapter for a fully-integrated estimate
        adapter = self.registry.get_adapter(process_family)
        if adapter is not None:
            try:
                return adapter.estimate_cost(intent, machine)
            except Exception as exc:
                logger.warning(
                    "CostEstimator: adapter raised for %s/%s: %s",
                    process_family.value,
                    machine.machine_id,
                    exc,
                )

        # 2. Component-based fallback
        cycle_minutes = self._cycle_estimator.estimate(intent, process_family, machine)
        cycle_hours = cycle_minutes / 60.0

        energy_profile = self._get_energy_profile(intent, process_family, machine, adapter)
        energy_kwh = energy_profile.average_power_kw * cycle_hours
        energy_cost = energy_kwh * rate

        labor_cost = cycle_hours * self.labor_rate
        tooling_cost = energy_cost * TOOLING_WEAR_FACTOR

        # Consumables from adapter if available
        consumable_cost = 0.0
        if adapter is not None:
            try:
                consumables = adapter.get_consumables(intent)
                # Rough consumable material cost: $5/kg average for metals
                consumable_cost = sum(consumables.values()) * 5.0
            except Exception:
                pass

        return energy_cost + labor_cost + tooling_cost + consumable_cost

    def estimate_breakdown(
        self,
        intent: ManufacturingIntent,
        process_family: ProcessFamily,
        machine: MachineCapability,
        energy_rate_usd_kwh: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Return a full cost breakdown dict with keys:
        energy_usd, labor_usd, tooling_usd, consumables_usd, total_usd
        """
        rate = energy_rate_usd_kwh or self.energy_rate
        adapter = self.registry.get_adapter(process_family)

        cycle_minutes = self._cycle_estimator.estimate(intent, process_family, machine)
        cycle_hours = cycle_minutes / 60.0
        energy_profile = self._get_energy_profile(intent, process_family, machine, adapter)

        energy_kwh = energy_profile.average_power_kw * cycle_hours
        energy_usd = energy_kwh * rate
        labor_usd = cycle_hours * self.labor_rate
        tooling_usd = energy_usd * TOOLING_WEAR_FACTOR
        consumables_usd = 0.0

        if adapter is not None:
            try:
                consumables = adapter.get_consumables(intent)
                consumables_usd = sum(consumables.values()) * 5.0
            except Exception:
                pass

        total = energy_usd + labor_usd + tooling_usd + consumables_usd
        return {
            "energy_usd": round(energy_usd, 2),
            "labor_usd": round(labor_usd, 2),
            "tooling_usd": round(tooling_usd, 2),
            "consumables_usd": round(consumables_usd, 2),
            "total_usd": round(total, 2),
        }

    def _get_energy_profile(
        self, intent, process_family, machine, adapter
    ) -> EnergyProfile:
        """Get energy profile, trying adapter first then capability then fallback."""
        if adapter is not None:
            try:
                return adapter.get_energy_profile(intent, machine)
            except Exception:
                pass

        cap = machine.get_capability(process_family)
        if cap and cap.energy_profile:
            return cap.energy_profile

        category = ProcessCategory.for_process(process_family)
        base, peak, idle = _FALLBACK_ENERGY.get(category, (70.0, 100.0, 5.0))
        return EnergyProfile(
            base_power_kw=base,
            peak_power_kw=peak,
            idle_power_kw=idle,
        )


# ---------------------------------------------------------------------------
# Feasibility Result
# ---------------------------------------------------------------------------


@dataclass
class FeasibilityResult:
    """
    Result of a feasibility check on a ManufacturingIntent.

    Attributes:
        is_feasible:           True if the intent can be executed with current registry
        errors:                Blocking issues that make execution impossible
        warnings:              Non-blocking issues (suboptimal but possible)
        capable_process_count: Number of process/machine combinations that could work
        estimated_lead_time_hours: Rough lead time estimate across all steps
        recommendations:       Suggested process alternatives or improvements
        checked_at:            Timestamp of the check
    """
    is_feasible: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    capable_process_count: int = 0
    estimated_lead_time_hours: Optional[float] = None
    recommendations: List[str] = field(default_factory=list)
    checked_at: datetime = field(default_factory=datetime.utcnow)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "is_feasible": self.is_feasible,
            "errors": self.errors,
            "warnings": self.warnings,
            "capable_process_count": self.capable_process_count,
            "estimated_lead_time_hours": self.estimated_lead_time_hours,
            "recommendations": self.recommendations,
            "checked_at": self.checked_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Feasibility Checker
# ---------------------------------------------------------------------------


class FeasibilityChecker:
    """
    Determines whether a ManufacturingIntent can be executed with the
    currently registered process adapters and machines.

    Performs:
      1. Validation (delegates to validation.validate_intent)
      2. Routing feasibility (any capable machine exists?)
      3. Lead time estimate (cycle + setup across all required steps)
      4. Recommendations for process substitution when blocked
    """

    def __init__(self, registry: ProcessRegistry) -> None:
        self.registry = registry
        self._time_estimator = CycleTimeEstimator(registry)

    def check(self, intent: ManufacturingIntent) -> FeasibilityResult:
        """
        Run a full feasibility check on the intent.

        Returns:
            FeasibilityResult with errors, warnings, and estimates.
        """
        from .validation import validate_intent  # avoid circular import at module level

        errors: List[str] = []
        warnings: List[str] = []
        recommendations: List[str] = []
        capable_process_count = 0
        total_lead_time_minutes = 0.0

        # 1. Structural validation
        validation_errors = validate_intent(intent, self.registry)
        for e in validation_errors:
            # Distinguish between errors and warnings
            if "consider" in e.lower() or "warning" in e.lower():
                warnings.append(e)
            else:
                errors.append(e)

        # 2. Process routing feasibility
        processes = intent.required_processes or self.registry.list_supported_processes()
        for pf in processes:
            machines = self.registry.find_capable_machines(pf, intent.material.normalized_name)
            if not machines:
                machines = self.registry.find_capable_machines_any_material(pf)
            if machines:
                capable_process_count += 1
                # Estimate lead time contribution
                best_machine = machines[0]
                try:
                    cycle = self._time_estimator.estimate(intent, pf, best_machine)
                    cap = best_machine.get_capability(pf)
                    setup = cap.setup_time_range_minutes[0] if (
                        cap and cap.setup_time_range_minutes
                    ) else 30.0
                    total_lead_time_minutes += cycle + setup
                except Exception:
                    total_lead_time_minutes += 60.0  # 1-hour default fallback
            else:
                if pf in (intent.required_processes or []):
                    errors.append(
                        f"No capable machine found for required process '{pf.value}' "
                        f"with material '{intent.material.normalized_name}'."
                    )
                    # Suggest alternatives
                    alt = self._suggest_alternatives(pf)
                    if alt:
                        recommendations.append(
                            f"For '{pf.value}', consider alternatives: {', '.join(alt)}"
                        )

        # 3. Cost feasibility
        if intent.cost_target_usd is not None:
            cost_estimator = CostEstimator(self.registry)
            total_cost = 0.0
            for pf in (intent.required_processes or []):
                machines = self.registry.find_capable_machines(
                    pf, intent.material.normalized_name
                ) or self.registry.find_capable_machines_any_material(pf)
                if machines:
                    try:
                        total_cost += cost_estimator.estimate(intent, pf, machines[0])
                    except Exception:
                        pass

            if total_cost > intent.cost_target_usd:
                warnings.append(
                    f"Estimated cost ${total_cost:.0f} exceeds target ${intent.cost_target_usd:.0f}. "
                    f"Consider higher-volume runs or alternative processes."
                )

        # 4. Due date feasibility
        if intent.due_date is not None:
            now = datetime.utcnow()
            if intent.due_date.tzinfo is not None:
                now = datetime.now(timezone.utc)
            hours_available = (intent.due_date - now).total_seconds() / 3600.0
            lead_time_hours = total_lead_time_minutes / 60.0
            if hours_available < lead_time_hours:
                warnings.append(
                    f"Estimated lead time {lead_time_hours:.1f}h may exceed available "
                    f"time before due date ({hours_available:.1f}h). "
                    f"Consider overtime shifts or parallel processing."
                )

        is_feasible = len(errors) == 0

        return FeasibilityResult(
            is_feasible=is_feasible,
            errors=errors,
            warnings=warnings,
            capable_process_count=capable_process_count,
            estimated_lead_time_hours=round(total_lead_time_minutes / 60.0, 2),
            recommendations=recommendations,
        )

    def _suggest_alternatives(self, process_family: ProcessFamily) -> List[str]:
        """Suggest alternative process families for common substitutions."""
        alt_map: Dict[ProcessFamily, List[ProcessFamily]] = {
            ProcessFamily.WELDING_LASER: [ProcessFamily.WELDING_ARC, ProcessFamily.WELDING_EBW],
            ProcessFamily.WELDING_EBW: [ProcessFamily.WELDING_LASER, ProcessFamily.WELDING_ARC],
            ProcessFamily.CUTTING_LASER: [ProcessFamily.CUTTING_PLASMA, ProcessFamily.CUTTING_WATERJET],
            ProcessFamily.CUTTING_PLASMA: [ProcessFamily.CUTTING_LASER, ProcessFamily.CUTTING_WATERJET],
            ProcessFamily.EDM_WIRE: [ProcessFamily.EDM_SINKER, ProcessFamily.CNC_MILLING],
            ProcessFamily.ADDITIVE_DMLS: [ProcessFamily.ADDITIVE_SLS, ProcessFamily.ADDITIVE_WIRE_ARC],
            ProcessFamily.CNC_MILLING: [ProcessFamily.CNC_TURNING, ProcessFamily.EDM_SINKER],
        }
        alts = alt_map.get(process_family, [])
        # Only suggest alternatives that actually have registered adapters
        registered = set(self.registry.list_supported_processes())
        return [a.value for a in alts if a in registered]
