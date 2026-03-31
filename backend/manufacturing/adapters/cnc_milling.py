"""
CNC Milling Process Adapter
=============================
Reference implementation of BaseAdapter for CNC_MILLING.

This adapter wraps the existing MillForge scheduler / energy optimizer constants
into the new ProcessAdapter pattern, providing backward compatibility while
exposing a clean interface for the routing engine.

Key domain model:
  - Throughput: units/hour by material (from THROUGHPUT constant)
  - Setup: sequence-dependent changeover from SETUP_MATRIX
  - Power: kW by material from MACHINE_POWER_KW
  - Material consumption: kg/unit from KG_PER_UNIT
  - Coolant, cutting oil classified as consumables
  - Quality: CMM dimensional check + optional surface finish measurement

Process parameters (stored in ProcessStepDefinition.parameters):
  spindle_speed_rpm, feed_rate_mm_min, depth_of_cut_mm, coolant_type,
  number_of_passes, cutting_strategy ("climb" | "conventional")
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from ..ontology import (
    EnergyProfile,
    FixtureSpec,
    ManufacturingIntent,
    ProcessFamily,
    QualityRequirement,
    ToolingSpec,
)
from ..registry import MachineCapability
from .base_adapter import (
    BASE_SETUP_MINUTES,
    KG_PER_UNIT,
    MACHINE_POWER_KW,
    SETUP_MATRIX,
    THROUGHPUT,
    BaseAdapter,
)


# ---------------------------------------------------------------------------
# CNC Milling constants
# ---------------------------------------------------------------------------

# Spindle speed (RPM) by material — starting point, adjusted by tool diameter
SPINDLE_SPEED_RPM: Dict[str, int] = {
    "steel": 800,
    "aluminum": 3500,
    "titanium": 400,
    "copper": 2000,
    "default": 1200,
}

# Feed rate (mm/min) by material
FEED_RATE_MM_MIN: Dict[str, float] = {
    "steel": 300.0,
    "aluminum": 1200.0,
    "titanium": 150.0,
    "copper": 800.0,
    "default": 500.0,
}

# Depth of cut (mm) by material — roughing pass
DEPTH_OF_CUT_MM: Dict[str, float] = {
    "steel": 1.5,
    "aluminum": 4.0,
    "titanium": 0.8,
    "copper": 2.5,
    "default": 2.0,
}

# Coolant type by material
COOLANT_TYPE: Dict[str, str] = {
    "steel": "flood_coolant",
    "aluminum": "mist_coolant",
    "titanium": "flood_coolant",
    "copper": "dry",
    "default": "mist_coolant",
}

# Cutting oil consumption (liters/hour) by material
COOLANT_LITERS_PER_HOUR: Dict[str, float] = {
    "steel": 8.0,
    "aluminum": 3.0,
    "titanium": 10.0,
    "copper": 0.0,
    "default": 4.0,
}

# Tool life factor — average end mill life (hours) by material
TOOL_LIFE_HOURS: Dict[str, float] = {
    "steel": 4.0,
    "aluminum": 8.0,
    "titanium": 2.0,
    "copper": 6.0,
    "default": 4.0,
}

# Tool cost (USD per end mill)
TOOL_COST_USD = 45.0

# Labor rate ($/hour)
LABOR_RATE_USD_HOUR = 75.0

# Default electricity rate
ENERGY_RATE_USD_KWH = 0.12


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class CNCMillingAdapter(BaseAdapter):
    """
    Process adapter for CNC_MILLING.

    Wraps the existing SETUP_MATRIX, THROUGHPUT, MACHINE_POWER_KW, and KG_PER_UNIT
    constants from the legacy scheduler/inventory modules into the adapter interface.

    Extends BaseAdapter with:
      - Material-specific spindle speed and feed rate
      - Tool selection logic (end mill diameter from material + complexity)
      - Cutting oil consumables
      - Detailed setup sheet with NC program parameters
      - ISO 2768-m dimensional quality checks
    """

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.CNC_MILLING

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        """Validate that the intent is suitable for CNC milling."""
        errors = super().validate_intent(intent)
        mat = intent.material

        # CNC milling requires metallic or engineering polymer materials
        if mat.material_family.lower() not in {"ferrous", "non_ferrous", "polymer", "composite"}:
            errors.append(
                f"CNC_MILLING is not suitable for material family '{mat.material_family}'. "
                f"Supported families: ferrous, non_ferrous, polymer, composite."
            )

        # Check for unrealistically large batches
        if intent.target_quantity > 10_000:
            errors.append(
                f"Batch size of {intent.target_quantity} units is unusually high for "
                f"CNC milling. Consider die casting or stamping for high-volume production."
            )

        # Warn on raw powder material form
        if mat.form and mat.form.lower() in {"powder", "pellet"}:
            errors.append(
                f"Material form '{mat.form}' is not suitable for CNC milling. "
                f"Expected: bar_stock, billet, plate, or casting."
            )

        return errors

    # ------------------------------------------------------------------
    # Cycle time estimation
    # ------------------------------------------------------------------

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total cycle time in minutes for all units.

        Algorithm:
          base_time = (quantity / throughput_units_per_hour) * 60 * complexity
          Where complexity is read from intent.custom_metadata["complexity"] or defaults to 1.0.
        """
        mat = intent.material.normalized_name
        throughput = THROUGHPUT.get(mat, 3.0)
        complexity = float(intent.custom_metadata.get("complexity", 1.0))
        complexity = max(0.5, min(complexity, 5.0))

        hours = (intent.target_quantity / throughput) * complexity
        return round(hours * 60.0, 1)

    # ------------------------------------------------------------------
    # Cost estimation
    # ------------------------------------------------------------------

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total machining cost in USD (excludes setup).

        Components:
          1. Energy: base_power_kw × cycle_hours × rate
          2. Labor: cycle_hours × labor_rate
          3. Tooling wear: (cycle_hours / tool_life) × tool_cost
          4. Coolant: coolant_liters × coolant_cost_per_liter ($0.08/L avg)
        """
        mat = intent.material.normalized_name
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        cycle_hours = cycle_minutes / 60.0

        # Energy
        power_kw = MACHINE_POWER_KW.get(mat, MACHINE_POWER_KW["default"])
        energy_cost = power_kw * cycle_hours * ENERGY_RATE_USD_KWH

        # Labor
        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Tooling wear
        tool_life = TOOL_LIFE_HOURS.get(mat, 4.0)
        tooling_cost = (cycle_hours / tool_life) * TOOL_COST_USD

        # Coolant
        coolant_lph = COOLANT_LITERS_PER_HOUR.get(mat, 4.0)
        coolant_cost = coolant_lph * cycle_hours * 0.08  # $0.08/liter

        return round(energy_cost + labor_cost + tooling_cost + coolant_cost, 2)

    # ------------------------------------------------------------------
    # Setup sheet
    # ------------------------------------------------------------------

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        """Generate a machine operator setup sheet with CNC-specific parameters."""
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material.normalized_name

        tool_diameter_mm = self._select_tool_diameter(intent)

        # Adjust spindle speed for tool diameter: N = (1000 × Vc) / (π × D)
        vc = {"steel": 60, "aluminum": 200, "titanium": 40, "copper": 120}.get(mat, 80)
        spindle_rpm = max(100, int((1000 * vc) / (math.pi * tool_diameter_mm)))

        sheet["process_parameters"] = {
            "spindle_speed_rpm": spindle_rpm,
            "feed_rate_mm_min": FEED_RATE_MM_MIN.get(mat, 500.0),
            "depth_of_cut_mm": DEPTH_OF_CUT_MM.get(mat, 2.0),
            "tool_diameter_mm": tool_diameter_mm,
            "coolant_type": COOLANT_TYPE.get(mat, "mist_coolant"),
            "cutting_strategy": "climb",
            "number_of_passes": self._estimate_passes(intent),
            "material_hardness": intent.material.hardness,
        }
        return sheet

    # ------------------------------------------------------------------
    # Tooling
    # ------------------------------------------------------------------

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        """Return the CNC tooling list for this intent."""
        mat = intent.material.normalized_name
        tool_dia = self._select_tool_diameter(intent)

        tools = [
            ToolingSpec(
                tooling_type="end_mill",
                tool_id=f"EM-{int(tool_dia)}D-{mat.upper()[:2]}-4F",
                description=f"{tool_dia}mm 4-flute carbide end mill for {mat}",
                parameters={
                    "diameter_mm": tool_dia,
                    "flutes": 4,
                    "material": "carbide_TiAlN_coated" if mat in {"steel", "titanium"} else "carbide",
                    "reach_mm": tool_dia * 4,
                },
            ),
            ToolingSpec(
                tooling_type="face_mill",
                tool_id=f"FM-63D-{mat.upper()[:2]}",
                description=f"63mm face mill for {mat} facing operations",
                parameters={
                    "diameter_mm": 63,
                    "inserts": 5,
                    "insert_grade": "PVD_coated" if mat in {"steel", "titanium"} else "uncoated",
                },
            ),
        ]

        # Add drill if geometry hints at hole features
        if "drill" in str(intent.custom_metadata).lower() or "hole" in str(intent.description).lower():
            tools.append(
                ToolingSpec(
                    tooling_type="twist_drill",
                    tool_id=f"DR-8.5D-{mat.upper()[:2]}",
                    description=f"8.5mm carbide twist drill for {mat}",
                    parameters={"diameter_mm": 8.5, "point_angle_deg": 118},
                )
            )

        return tools

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        """Return fixtures based on material form and quantity."""
        mat_form = intent.material.form.lower() if intent.material.form else "bar_stock"

        if mat_form in {"plate", "sheet"}:
            return [
                FixtureSpec(
                    fixture_type="vacuum_table",
                    description="Vacuum workholding table for plate/sheet stock",
                    setup_time_minutes=10.0,
                    parameters={"max_plate_mm": (600, 400), "vacuum_zones": 4},
                )
            ]
        elif intent.target_quantity > 50:
            return [
                FixtureSpec(
                    fixture_type="tombstone",
                    description="4-sided tombstone fixture for high-volume milling",
                    setup_time_minutes=45.0,
                    parameters={"stations": 4, "material": "aluminum_6061"},
                )
            ]
        else:
            return [
                FixtureSpec(
                    fixture_type="vise",
                    description="Kurt-style precision machinist vise",
                    setup_time_minutes=15.0,
                    parameters={"jaw_width_mm": 152, "max_opening_mm": 165},
                )
            ]

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """CNC-specific QC: CMM dimensional + optional surface finish."""
        checks = super().get_quality_checks(intent)

        # Add surface finish check for tight-tolerance parts
        ra_required = None
        if intent.quality_requirements:
            ra_required = intent.quality_requirements[0].surface_finish_ra
        elif intent.custom_metadata.get("surface_finish_required"):
            ra_required = 1.6  # default fine finish for machined surfaces

        if ra_required is not None:
            checks.append(
                QualityRequirement(
                    inspection_method="profilometer",
                    tolerance_class="ISO_2768_f",
                    surface_finish_ra=ra_required,
                    standards=["ISO 4287", "ASME B46.1"],
                    acceptance_criteria={"ra_max_um": ra_required * 1.1},
                )
            )

        return checks

    # ------------------------------------------------------------------
    # Consumables
    # ------------------------------------------------------------------

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        """CNC milling consumables: raw stock + coolant + cutting oil."""
        consumables = super().get_consumables(intent)  # raw stock
        mat = intent.material.normalized_name
        cycle_hours = self.estimate_cycle_time(intent, _DUMMY_MACHINE) / 60.0

        coolant_lph = COOLANT_LITERS_PER_HOUR.get(mat, 4.0)
        total_coolant_kg = coolant_lph * cycle_hours * 0.9  # density ~0.9 kg/L
        if total_coolant_kg > 0:
            consumables["cutting_coolant_kg"] = round(total_coolant_kg, 3)

        # Carbide tooling wear (approximate fraction per job)
        tool_life = TOOL_LIFE_HOURS.get(mat, 4.0)
        tool_fraction = min(1.0, cycle_hours / tool_life)
        consumables["carbide_end_mill_ea"] = round(tool_fraction, 3)

        return consumables

    # ------------------------------------------------------------------
    # Energy profile
    # ------------------------------------------------------------------

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        """Return an energy profile based on material power draw constants."""
        mat = intent.material.normalized_name
        base_kw = MACHINE_POWER_KW.get(mat, MACHINE_POWER_KW["default"])

        return EnergyProfile(
            base_power_kw=base_kw,
            peak_power_kw=base_kw * 1.35,   # peak on spindle startup + heavy cuts
            idle_power_kw=base_kw * 0.10,   # servo drives + CNC controller
            power_curve_type="variable",
            duty_cycle=0.85,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _select_tool_diameter(self, intent: ManufacturingIntent) -> float:
        """Choose end mill diameter based on workpiece dimensions and material."""
        # If width is available, use 1/4 of it as tool diameter (rule of thumb)
        if intent.material.width_mm:
            return round(max(6.0, min(25.0, intent.material.width_mm / 4.0)), 1)
        # Otherwise fall back to material-specific defaults
        defaults = {"steel": 12.0, "aluminum": 16.0, "titanium": 10.0, "copper": 12.0}
        return defaults.get(intent.material.normalized_name, 12.0)

    def _estimate_passes(self, intent: ManufacturingIntent) -> int:
        """Estimate number of machining passes based on material and complexity."""
        complexity = float(intent.custom_metadata.get("complexity", 1.0))
        base_passes = {"steel": 3, "aluminum": 2, "titanium": 4, "copper": 2}
        base = base_passes.get(intent.material.normalized_name, 3)
        return max(1, round(base * complexity))


# ---------------------------------------------------------------------------
# Dummy machine for standalone consumables estimation
# ---------------------------------------------------------------------------

_DUMMY_MACHINE = MachineCapability(
    machine_id="_internal_dummy",
    machine_name="Dummy",
    machine_type="VMC",
    capabilities=[],
)
