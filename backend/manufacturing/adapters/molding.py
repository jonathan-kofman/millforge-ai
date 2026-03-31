"""
Molding Process Adapters
==========================
Covers injection molding for polymers and metal injection molding (MIM).

Key domain model:
  - High batch volume (minimum 50–100 units for economic mold amortization)
  - Long mold setup time (60–240 min for installation, warm-up, purge)
  - Fast cycle times once the mold is running (30 sec – 5 min per shot)
  - Consumables: polymer resin or metal powder + binder
  - Quality: dimensional, warpage, flash, sink marks, weld lines, gate vestige
  - Clamping force calculated from projected part area × material injection pressure

Supported ProcessFamilies:
  - INJECTION_MOLDING (thermoplastic, thermoset, and metal injection molding)
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
from .base_adapter import BaseAdapter


# ---------------------------------------------------------------------------
# Injection Molding constants
# ---------------------------------------------------------------------------

# Injection pressure (MPa) by material family — used for clamping force calc
INJECTION_PRESSURE_MPA: Dict[str, float] = {
    "polymer": 30.0,        # typical thermoplastic: 20–80 MPa
    "composite": 50.0,      # fiber-reinforced: higher viscosity
    "ferrous": 150.0,       # MIM: metal feedstock at high pressure
    "non_ferrous": 120.0,   # aluminum MIM or zinc die casting
    "default": 40.0,
}

# Cycle time (seconds/shot) by material and part complexity
CYCLE_TIME_SECS: Dict[str, float] = {
    "polymer": 30.0,        # thin-wall thermoplastic
    "composite": 60.0,      # filled/reinforced, slower cooling
    "ferrous": 45.0,        # MIM: similar to polymer (feedstock is ~60% polymer binder)
    "non_ferrous": 30.0,
    "default": 40.0,
}

# Mold setup time (minutes) by mold complexity
MOLD_SETUP_MINUTES: Dict[str, float] = {
    "simple": 60.0,        # 1-2 cavity, single action
    "moderate": 120.0,     # 4-8 cavity with side actions
    "complex": 240.0,      # hot runner, 16+ cavity, complex geometry
}

# Machine power draw (kW) — hydraulic vs electric injection machine
INJECTION_POWER_KW: Dict[str, float] = {
    "base": 30.0,
    "peak": 80.0,   # peak during injection phase (fraction of cycle)
    "idle": 4.0,
}

# Minimum batch sizes
MIN_BATCH_STANDARD = 50      # minimum for basic amortization
MIN_BATCH_MULTI_CAVITY = 100 # recommended for 4+ cavity tooling

# Labor
LABOR_RATE_USD_HOUR = 50.0
ENERGY_RATE_USD_KWH = 0.12

# Resin cost (USD/kg) by material family
RESIN_COST_USD_KG: Dict[str, float] = {
    "polymer": 3.50,        # commodity thermoplastic (ABS, PP, HDPE)
    "composite": 12.00,     # glass/carbon filled grades
    "ferrous": 35.0,        # MIM feedstock (iron powder + binder)
    "non_ferrous": 25.0,    # aluminum MIM
    "default": 5.0,
}

# Material density (kg/dm³ ≈ g/cm³) for shot weight calculation
DENSITY_KG_DM3: Dict[str, float] = {
    "polymer": 1.10,
    "composite": 1.40,
    "ferrous": 7.85,
    "non_ferrous": 2.70,
    "default": 1.10,
}

# Mold cost by complexity and cavities
MOLD_COST_USD: Dict[str, float] = {
    "simple": 8_000.0,
    "moderate": 40_000.0,
    "complex": 200_000.0,
}

# Mold life (shots) by material — polymer molds last longer than metal injection
MOLD_LIFE_SHOTS: Dict[str, float] = {
    "polymer": 1_000_000.0,
    "composite": 500_000.0,
    "ferrous": 100_000.0,
    "non_ferrous": 500_000.0,
    "default": 500_000.0,
}

# Scrap / runner waste as fraction of total shot weight
RUNNER_WASTE_FRACTION = 0.15  # ~15% lost to runner system (hot runner saves most)


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class InjectionMoldingAdapter(BaseAdapter):
    """
    Process adapter for INJECTION_MOLDING.

    Covers:
      - Thermoplastic injection molding (ABS, PP, PC, PEEK, Nylon, etc.)
      - Thermoset injection molding (epoxy, phenolic)
      - Metal injection molding (MIM) — iron, stainless steel, titanium alloys
      - Fiber-reinforced / filled polymers

    Key capabilities:
      - Clamping force calculation from projected area and injection pressure
      - Cycle time model: injection + hold + cool + eject
      - Multi-cavity mold efficiency scaling
      - Runner waste and shot weight calculation
      - Mold warm-up and purge time in setup
      - Warpage, sink, flash, and dimensional checks
    """

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.INJECTION_MOLDING

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat = intent.material
        mat_family = mat.material_family.lower()

        # Injection molding is primarily for polymers and composites (and MIM)
        if mat_family in {"ferrous", "non_ferrous"}:
            if not intent.custom_metadata.get("mim"):
                errors.append(
                    f"INJECTION_MOLDING with metallic material '{mat.normalized_name}' "
                    f"requires Metal Injection Molding (MIM) process. "
                    f"Set custom_metadata['mim'] = True to confirm MIM intent. "
                    f"For standard metal parts, use CNC_MILLING or DIE_CASTING."
                )

        # Minimum batch
        min_batch = MIN_BATCH_STANDARD
        if intent.target_quantity < min_batch:
            errors.append(
                f"INJECTION_MOLDING requires a minimum batch of {min_batch} units to "
                f"amortize tooling cost. Requested: {intent.target_quantity}. "
                f"Consider CNC machining or SLA/FDM printing for smaller runs."
            )

        # Wall thickness warning
        t = mat.thickness_mm
        if t is not None:
            if t < 0.5 and mat_family == "polymer":
                errors.append(
                    f"Wall thickness {t}mm is below typical injection molding minimum (0.5mm). "
                    f"Risk of short shots and fill issues."
                )
            if t > 8.0 and mat_family == "polymer":
                errors.append(
                    f"Wall thickness {t}mm may cause excessive sink marks and warpage. "
                    f"Design recommendation: max 4–6mm wall for most polymers."
                )

        # Ceramic materials
        if mat_family == "ceramic":
            errors.append(
                "INJECTION_MOLDING is not suitable for ceramic materials. "
                "Use CIM (Ceramic Injection Molding) which is a specialty variant."
            )

        return errors

    # ------------------------------------------------------------------
    # Cycle time
    # ------------------------------------------------------------------

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total molding cycle time in minutes.

        Model:
            cycle_time_per_shot = inject + hold + cool + eject
            parts_per_shot = num_cavities
            total_shots = ceil(quantity / num_cavities)
            total_time = total_shots × cycle_time_per_shot
        """
        mat_family = intent.material.material_family.lower()
        secs_per_shot = CYCLE_TIME_SECS.get(mat_family, CYCLE_TIME_SECS["default"])

        # Wall thickness affects cooling time (dominant phase)
        t = intent.material.thickness_mm or 2.0
        # Cooling time scales with t² (Fourier law approximation)
        cooling_factor = max(1.0, (t / 2.0) ** 2)  # normalized to 2mm baseline
        secs_per_shot *= min(cooling_factor, 4.0)   # cap at 4× for very thick parts

        # Cavities per mold (from metadata, default 4)
        num_cavities = int(intent.custom_metadata.get("num_cavities", 4))
        num_cavities = max(1, num_cavities)

        # Complexity factor
        complexity = float(intent.custom_metadata.get("complexity", 1.0))
        secs_per_shot *= max(0.8, min(complexity, 2.0))

        total_shots = math.ceil(intent.target_quantity / num_cavities)
        total_minutes = (total_shots * secs_per_shot) / 60.0

        return round(total_minutes, 1)

    # ------------------------------------------------------------------
    # Cost
    # ------------------------------------------------------------------

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Injection molding cost in USD.

        Components:
          1. Energy: machine power × cycle_hours × rate
          2. Labor: cycle_hours × labor_rate
          3. Resin / feedstock material cost
          4. Mold amortization
        """
        mat_family = intent.material.material_family.lower()
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        cycle_hours = cycle_minutes / 60.0

        # Energy
        avg_power = INJECTION_POWER_KW["base"] * 0.65 + INJECTION_POWER_KW["idle"] * 0.35
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH

        # Labor
        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Material (resin/feedstock)
        consumables = self.get_consumables(intent)
        resin_kg = consumables.get(f"resin_{mat_family}_kg", 0.0)
        resin_cost = resin_kg * RESIN_COST_USD_KG.get(mat_family, 5.0)

        # Mold amortization
        mold_type = str(intent.custom_metadata.get("mold_type", "moderate"))
        mold_cost = MOLD_COST_USD.get(mold_type, MOLD_COST_USD["moderate"])
        mold_life = MOLD_LIFE_SHOTS.get(mat_family, 500_000.0)
        num_cavities = int(intent.custom_metadata.get("num_cavities", 4))
        total_shots = math.ceil(intent.target_quantity / max(1, num_cavities))
        mold_amort = (total_shots / mold_life) * mold_cost

        return round(energy_cost + labor_cost + resin_cost + mold_amort, 2)

    # ------------------------------------------------------------------
    # Setup sheet
    # ------------------------------------------------------------------

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material
        mat_family = mat.material_family.lower()
        t = mat.thickness_mm or 2.0
        num_cavities = int(intent.custom_metadata.get("num_cavities", 4))
        mold_type = str(intent.custom_metadata.get("mold_type", "moderate"))

        # Clamping force: projected_area_cm2 × injection_pressure_MPa × 10 → tons
        area_mm2 = (mat.width_mm or 50.0) * (mat.length_mm or 80.0)
        clamp_force_tons = self._clamping_force_tons(mat_family, area_mm2)

        sheet["process_parameters"] = {
            "material_family": mat_family,
            "material": mat.normalized_name,
            "is_mim": bool(intent.custom_metadata.get("mim", False)),
            "wall_thickness_mm": t,
            "num_cavities": num_cavities,
            "mold_type": mold_type,
            "clamping_force_tons": round(clamp_force_tons, 1),
            "injection_pressure_mpa": INJECTION_PRESSURE_MPA.get(mat_family, 40.0),
            "melt_temperature_c": self._melt_temperature(mat.normalized_name, mat_family),
            "mold_temperature_c": self._mold_temperature(mat.normalized_name, mat_family),
            "cycle_time_secs": round(
                self.estimate_cycle_time(intent, machine) / math.ceil(intent.target_quantity / num_cavities) * 60, 1
            ),
            "cooling_time_fraction": 0.60,  # ~60% of cycle is cooling
            "runner_type": str(intent.custom_metadata.get("runner_type", "hot_runner")),
            "gate_type": str(intent.custom_metadata.get("gate_type", "submarine")),
        }
        return sheet

    # ------------------------------------------------------------------
    # Tooling
    # ------------------------------------------------------------------

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        mat_family = intent.material.material_family.lower()
        mold_type = str(intent.custom_metadata.get("mold_type", "moderate"))
        num_cavities = int(intent.custom_metadata.get("num_cavities", 4))

        tools = [
            ToolingSpec(
                tooling_type="injection_mold",
                tool_id=f"IM-{mold_type.upper()[:3]}-{num_cavities}C",
                description=f"{num_cavities}-cavity {mold_type} injection mold",
                parameters={
                    "num_cavities": num_cavities,
                    "mold_material": "P20_tool_steel" if mat_family == "polymer" else "H13_hot_work",
                    "surface_finish": "SPI_A2_optical" if intent.custom_metadata.get("optical") else "SPI_B1",
                    "runner_type": str(intent.custom_metadata.get("runner_type", "hot_runner")),
                    "cooling_lines": True,
                    "ejector_type": "pin",
                    "expected_life_shots": MOLD_LIFE_SHOTS.get(mat_family, 500_000),
                },
            )
        ]
        return tools

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        mold_type = str(intent.custom_metadata.get("mold_type", "moderate"))
        setup_time = MOLD_SETUP_MINUTES.get(mold_type, 120.0)
        return [
            FixtureSpec(
                fixture_type="mold_clamp_unit",
                description="Injection machine clamp unit — mold mounting and clamping",
                setup_time_minutes=setup_time,
                parameters={
                    "platen_size_mm": (600, 600),
                    "tie_bar_spacing_mm": (450, 450),
                    "hydraulic_pressure_bar": 150,
                },
            )
        ]

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        return [
            QualityRequirement(
                inspection_method="CMM",
                tolerance_class="ISO_2768_m",
                standards=["ISO 20457", "ASME Y14.5"],
                acceptance_criteria={
                    "warpage_max_mm": 0.5,
                    "flash_max_mm": 0.1,
                    "sink_marks_acceptable": False,
                    "weld_lines_acceptable": intent.custom_metadata.get("allow_weld_lines", True),
                    "gate_vestige_max_mm": 0.5,
                    "first_article_required": True,
                },
            ),
            QualityRequirement(
                inspection_method="visual_inspection",
                tolerance_class="ISO_2768_m",
                standards=["ISO 20457"],
                acceptance_criteria={
                    "surface_defects": "none_class_A",
                    "color_consistency": True,
                    "delamination": False,
                },
            ),
        ]

    # ------------------------------------------------------------------
    # Consumables
    # ------------------------------------------------------------------

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        mat = intent.material
        mat_family = mat.material_family.lower()
        t = mat.thickness_mm or 2.0
        w = mat.width_mm or 50.0
        l = mat.length_mm or 80.0

        # Shot weight = part volume × density + runner waste
        vol_cm3 = (t / 10.0) * (w / 10.0) * (l / 10.0)
        density = DENSITY_KG_DM3.get(mat_family, 1.10)
        part_kg = vol_cm3 * density / 1000.0
        # Add runner waste
        total_kg = part_kg * intent.target_quantity * (1 + RUNNER_WASTE_FRACTION)

        return {f"resin_{mat_family}_kg": round(total_kg, 3)}

    # ------------------------------------------------------------------
    # Energy profile
    # ------------------------------------------------------------------

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        return EnergyProfile(
            base_power_kw=INJECTION_POWER_KW["base"],
            peak_power_kw=INJECTION_POWER_KW["peak"],
            idle_power_kw=INJECTION_POWER_KW["idle"],
            power_curve_type="pulsed",
            duty_cycle=0.55,  # injection phase is brief but high-power
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _clamping_force_tons(self, mat_family: str, projected_area_mm2: float) -> float:
        """
        Clamping force = projected_area_cm2 × injection_pressure_MPa × 10 → tons
        (1 MPa = 10 bar; 1 cm² × 10 bar = 10 N; ÷ 9810 → metric tons)
        """
        area_cm2 = projected_area_mm2 / 100.0
        pressure_mpa = INJECTION_PRESSURE_MPA.get(mat_family, 40.0)
        # Force in kN = area_cm2 × pressure_MPa × 10 (unit conversion)
        force_kn = area_cm2 * pressure_mpa * 10.0
        return force_kn / 9.81  # kN → metric tons

    def _melt_temperature(self, mat_name: str, mat_family: str) -> int:
        """Return recommended melt temperature (°C)."""
        temp_map: Dict[str, int] = {
            "abs": 240, "polypropylene": 230, "nylon": 270, "peek": 380,
            "polycarbonate": 290, "hdpe": 210, "acetal": 200, "pvc": 185,
        }
        if mat_family == "ferrous":
            return 1540  # iron MIM feedstock
        if mat_family == "non_ferrous":
            return 680  # aluminum MIM
        return temp_map.get(mat_name.lower(), 240)

    def _mold_temperature(self, mat_name: str, mat_family: str) -> int:
        """Return recommended mold temperature (°C) for cooling."""
        if mat_family in {"ferrous", "non_ferrous"}:
            return 150
        temp_map: Dict[str, int] = {
            "abs": 50, "polypropylene": 30, "nylon": 80, "peek": 180,
            "polycarbonate": 90, "hdpe": 20, "acetal": 90,
        }
        return temp_map.get(mat_name.lower(), 50)
