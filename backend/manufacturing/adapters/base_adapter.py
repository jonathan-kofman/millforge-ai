"""
Base Process Adapter
======================
Provides sensible defaults and common helpers for ProcessAdapter implementations.
Concrete adapters should subclass BaseAdapter and override only the methods
that differ from the defaults.

Default implementations:
  - validate_intent: checks material family, batch size, quantity
  - estimate_setup_time: uses SETUP_MATRIX from scheduler.py if available
  - get_quality_checks: returns a single CMM inspection step
  - get_consumables: returns empty dict (no consumables by default)
  - generate_setup_sheet: assembles a standardized dict from intent + machine

Concrete adapters MUST implement:
  - process_family (property)
  - estimate_cycle_time
  - estimate_cost
  - get_required_tooling
  - get_required_fixtures
  - get_energy_profile
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..ontology import (
    EnergyProfile,
    FixtureSpec,
    ManufacturingIntent,
    ProcessCategory,
    ProcessFamily,
    QualityRequirement,
    ToolingSpec,
)
from ..registry import MachineCapability, ProcessAdapter

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared constants (mirrors from scheduler.py and inventory_agent.py)
# These are re-exported here so adapters can import from one place.
# ---------------------------------------------------------------------------

#: Sequence-dependent changeover times (minutes), indexed by (from_material, to_material).
#: Pulled from agents/scheduler.py for backward compatibility.
SETUP_MATRIX: Dict[tuple, int] = {
    ("steel", "aluminum"): 60,
    ("aluminum", "steel"): 75,
    ("steel", "titanium"): 90,
    ("titanium", "steel"): 90,
    ("aluminum", "titanium"): 45,
    ("titanium", "aluminum"): 45,
    ("steel", "steel"): 15,
    ("aluminum", "aluminum"): 15,
    ("titanium", "titanium"): 20,
    ("steel", "copper"): 50,
    ("copper", "steel"): 50,
    ("aluminum", "copper"): 35,
    ("copper", "aluminum"): 35,
    ("copper", "copper"): 15,
}

BASE_SETUP_MINUTES = 30  # fallback if material pair not in SETUP_MATRIX

#: Material throughput (units / hour) from agents/scheduler.py
THROUGHPUT: Dict[str, float] = {
    "steel": 4.0,
    "aluminum": 6.0,
    "titanium": 2.5,
    "copper": 5.0,
}

#: Machine power draw (kW) by material from agents/energy_optimizer.py
MACHINE_POWER_KW: Dict[str, float] = {
    "steel": 85.0,
    "aluminum": 55.0,
    "titanium": 110.0,
    "copper": 65.0,
    "default": 70.0,
}

#: Material mass consumption (kg / unit) from agents/inventory_agent.py
KG_PER_UNIT: Dict[str, float] = {
    "steel": 2.5,
    "aluminum": 0.8,
    "titanium": 1.2,
    "copper": 1.5,
}


# ---------------------------------------------------------------------------
# Base Adapter
# ---------------------------------------------------------------------------


class BaseAdapter(ProcessAdapter):
    """
    Abstract base class with sensible defaults for all ProcessAdapter methods.

    Subclasses must implement:
        - process_family (property)
        - estimate_cycle_time
        - estimate_cost
        - get_required_tooling
        - get_required_fixtures
        - get_energy_profile
    """

    # ------------------------------------------------------------------
    # Validation (override to add process-specific rules)
    # ------------------------------------------------------------------

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        """
        Base validation: checks quantity, material completeness, and optional
        process-family compatibility. Subclasses should call super() and extend.
        """
        errors: List[str] = []

        if intent.target_quantity < 1:
            errors.append(f"target_quantity must be ≥ 1 (got {intent.target_quantity})")

        if not intent.material.material_name.strip():
            errors.append("material.material_name must not be empty.")

        if not intent.material.material_family.strip():
            errors.append("material.material_family must not be empty.")

        return errors

    # ------------------------------------------------------------------
    # Setup time
    # ------------------------------------------------------------------

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Return setup time in minutes using the SETUP_MATRIX.
        Reads 'last_material' from machine.custom_attributes if available to
        compute sequence-dependent changeover time.
        """
        current_material = intent.material.normalized_name
        last_material = machine.custom_attributes.get("last_material", current_material)

        key = (last_material.lower(), current_material.lower())
        return float(SETUP_MATRIX.get(key, BASE_SETUP_MINUTES))

    # ------------------------------------------------------------------
    # Consumables
    # ------------------------------------------------------------------

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        """
        Default consumables: raw stock material consumed.
        Subclasses can override for process-specific consumables (filler wire, gas, etc.)
        """
        mat = intent.material.normalized_name
        kg_per = KG_PER_UNIT.get(mat, 1.0)
        return {f"stock_{mat}": kg_per * intent.target_quantity}

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """
        Default quality check: CMM dimensional inspection.
        Processes with tighter quality requirements should override this.
        """
        tolerance_class = "ISO_2768_m"
        # Infer tighter tolerance from intent requirements if present
        if intent.quality_requirements:
            tolerance_class = intent.quality_requirements[0].tolerance_class

        return [
            QualityRequirement(
                inspection_method="CMM",
                tolerance_class=tolerance_class,
                critical_dimensions=intent.quality_requirements[0].critical_dimensions
                if intent.quality_requirements else [],
                surface_finish_ra=intent.quality_requirements[0].surface_finish_ra
                if intent.quality_requirements else None,
                standards=["ASME Y14.5"],
                acceptance_criteria={"pass_rate_min_pct": 98.0},
            )
        ]

    # ------------------------------------------------------------------
    # Setup sheet
    # ------------------------------------------------------------------

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        """
        Assemble a standardized setup sheet dict. Subclasses should call
        super() and merge their process-specific fields.
        """
        tooling = self.get_required_tooling(intent)
        fixtures = self.get_required_fixtures(intent)
        quality = self.get_quality_checks(intent)
        setup_time = self.estimate_setup_time(intent, machine)
        cycle_time = self.estimate_cycle_time(intent, machine)

        return {
            "process": self.process_family.value,
            "machine_id": machine.machine_id,
            "machine_name": machine.machine_name,
            "part_id": intent.part_id,
            "part_name": intent.part_name,
            "material": intent.material.material_name,
            "alloy": intent.material.alloy_designation,
            "quantity": intent.target_quantity,
            "setup_time_minutes": setup_time,
            "estimated_cycle_time_minutes": cycle_time,
            "tooling": [
                {"type": t.tooling_type, "id": t.tool_id, "desc": t.description}
                for t in tooling
            ],
            "fixtures": [
                {"type": f.fixture_type, "desc": f.description, "setup_min": f.setup_time_minutes}
                for f in fixtures
            ],
            "quality_checks": [
                {"method": q.inspection_method, "standard": q.tolerance_class}
                for q in quality
            ],
            "process_parameters": {},  # overridden by subclass
        }

    # ------------------------------------------------------------------
    # Helpers available to all subclasses
    # ------------------------------------------------------------------

    def _get_power_kw(self, intent: ManufacturingIntent) -> float:
        """Look up base machine power for the intent's material."""
        mat = intent.material.normalized_name
        return MACHINE_POWER_KW.get(mat, MACHINE_POWER_KW["default"])

    def _get_throughput(self, intent: ManufacturingIntent) -> float:
        """Return units/hour throughput for the intent's material (or 3.0 default)."""
        mat = intent.material.normalized_name
        return THROUGHPUT.get(mat, 3.0)

    def _material_is_metal(self, intent: ManufacturingIntent) -> bool:
        return intent.material.material_family.lower() in {"ferrous", "non_ferrous"}

    def _material_is_polymer(self, intent: ManufacturingIntent) -> bool:
        return intent.material.material_family.lower() == "polymer"

    def _category(self) -> ProcessCategory:
        return ProcessCategory.for_process(self.process_family)
