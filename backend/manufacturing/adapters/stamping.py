"""
Stamping Process Adapter
==========================
Adapter for STAMPING (progressive die stamping, blanking, drawing, coining).

Key domain model:
  - High volume, die-based production
  - Inputs: sheet thickness, blank size, die geometry, tonnage requirement
  - Constraints: minimum batch ~1000 units (die amortization), setup 30–120 min
  - Throughput: strokes per minute (SPM), typically 20–60 for progressive dies
  - Consumables: lubricant (stamping oil), blank material (sheet coil)
  - Quality: dimensional check, springback, surface finish, burr height

Physics:
  Blanking force: F = π × d × t × τ_shear
  Draw force: F = π × d × t × σ_UTS × (OD/d - C)
  Tonnage requirement is the maximum of all stations in the die.

  Material hardness is the main driver: harder materials require more tonnage
  and show more springback.
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
# Stamping constants
# ---------------------------------------------------------------------------

# Shear strength (MPa) — approximately 0.6–0.8 × UTS for most metals
SHEAR_STRENGTH_MPA: Dict[str, float] = {
    "steel": 300.0,          # mild steel
    "aluminum": 170.0,       # Al6061-T6
    "stainless_steel": 380.0,
    "titanium": 600.0,       # Ti-6Al-4V
    "copper": 140.0,
    "brass": 210.0,
    "default": 250.0,
}

# Strokes per minute (SPM) by die type and material
# Progressive dies achieve higher SPM than transfer or single-station
SPM_BY_MATERIAL: Dict[str, float] = {
    "steel": 40.0,
    "aluminum": 60.0,
    "stainless_steel": 25.0,
    "titanium": 15.0,
    "copper": 50.0,
    "brass": 45.0,
    "default": 35.0,
}

# Springback (degrees or fraction) by material — affects secondary coin/restrike ops
SPRINGBACK_FACTOR: Dict[str, float] = {
    "steel": 0.03,           # 3% over-bend
    "aluminum": 0.05,
    "stainless_steel": 0.06,
    "titanium": 0.10,
    "copper": 0.02,
    "brass": 0.04,
    "default": 0.05,
}

# Die setup time range (minutes) by die complexity
DIE_SETUP_MINUTES: Dict[str, float] = {
    "simple": 30.0,           # blanking die, single station
    "moderate": 60.0,         # 4–8 station progressive
    "complex": 120.0,         # 12+ station progressive with forming
}

# Minimum economical batch size
MIN_BATCH = 1000

# Press power draw (kW)
PRESS_POWER_KW: Dict[str, float] = {
    "base": 45.0,
    "peak": 120.0,  # high at bottom of stroke, full tonnage
    "idle": 5.0,
}

# Labor rate
LABOR_RATE_USD_HOUR = 60.0
ENERGY_RATE_USD_KWH = 0.12

# Lubricant consumption (liters/1000 strokes)
LUBRICANT_L_PER_1K_STROKES: Dict[str, float] = {
    "steel": 1.2,
    "aluminum": 0.8,
    "stainless_steel": 2.0,
    "titanium": 2.5,
    "copper": 0.6,
    "default": 1.0,
}

# Die cost for amortization (approximate)
DIE_COST_USD: Dict[str, float] = {
    "simple": 10_000.0,
    "moderate": 50_000.0,
    "complex": 200_000.0,
}

# Amortization life (parts)
DIE_LIFE_PARTS: Dict[str, float] = {
    "steel": 500_000.0,
    "aluminum": 2_000_000.0,
    "stainless_steel": 200_000.0,
    "titanium": 100_000.0,
    "default": 500_000.0,
}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class StampingAdapter(BaseAdapter):
    """
    Process adapter for STAMPING (progressive die / single-station stamping).

    Handles:
      - Blanking, piercing, bending, and drawing operations within a die
      - Tonnage calculation from material, thickness, and part geometry
      - Die setup time based on die complexity
      - Springback prediction (drives restrike or coining requirements)
      - High-volume economics: die amortization cost model
      - Quality: dimensional check, springback, burr height

    Typical applications:
      - Automotive brackets (1M+ runs)
      - Appliance panels
      - Electronic chassis and enclosures
      - Precision small parts (watch components, connectors)
    """

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.STAMPING

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat = intent.material

        # Stamping requires sheet or strip stock
        if mat.form and mat.form.lower() not in {"sheet", "plate", "strip", "coil", "blank"}:
            errors.append(
                f"STAMPING requires sheet, plate, strip, or coil stock. "
                f"Got form: '{mat.form}'."
            )

        # Minimum batch enforcement
        if intent.target_quantity < MIN_BATCH:
            errors.append(
                f"STAMPING requires a minimum batch of {MIN_BATCH} units to amortize "
                f"die cost. Requested: {intent.target_quantity}. "
                f"Consider BENDING_PRESS_BRAKE or CNC_MILLING for smaller runs."
            )

        # Polymers typically require injection molding
        if mat.material_family.lower() == "polymer":
            errors.append(
                "STAMPING is not suitable for polymer materials. "
                "Use INJECTION_MOLDING for plastic parts."
            )

        # Thickness limits: very thick plate is not stampable
        t = mat.thickness_mm or 3.0
        if t > 12.0 and mat.normalized_name not in {"aluminum", "copper", "brass"}:
            errors.append(
                f"Material thickness {t}mm is above typical stamping limits for "
                f"'{mat.normalized_name}'. Maximum recommended: 12mm. "
                f"Consider press brake or die forming."
            )

        # Titanium requires special dies and is slow
        if "titanium" in mat.normalized_name and intent.target_quantity < 5000:
            errors.append(
                "Titanium stamping requires D2 or carbide dies with extra polishing. "
                "This is only economical at batches ≥ 5,000 units."
            )

        return errors

    # ------------------------------------------------------------------
    # Cycle time
    # ------------------------------------------------------------------

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total cycle time in minutes.

        Model:
            cycle_time = (quantity / SPM) in minutes
            No coil feed stops for normal progressive runs.
        """
        mat = intent.material.normalized_name
        spm = SPM_BY_MATERIAL.get(mat, SPM_BY_MATERIAL["default"])
        total_strokes = intent.target_quantity

        # Progressive die: one stroke = one part
        run_minutes = total_strokes / spm

        # Coil changeover: assume ~10 min per 500 strokes for continuous feed
        coil_changes = math.ceil(total_strokes / 500)
        changeover_minutes = coil_changes * 10.0

        return round(run_minutes + changeover_minutes, 1)

    # ------------------------------------------------------------------
    # Cost
    # ------------------------------------------------------------------

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total stamping cost in USD.

        Components:
          1. Energy: press power × cycle_hours × rate
          2. Labor: cycle_hours × labor_rate
          3. Die amortization: die_cost / die_life × quantity
          4. Lubricant: liters × lubricant_cost
        """
        mat = intent.material.normalized_name
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        cycle_hours = cycle_minutes / 60.0

        # Energy
        avg_power = PRESS_POWER_KW["base"] * 0.6 + PRESS_POWER_KW["idle"] * 0.4
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH

        # Labor
        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Die amortization
        die_type = str(intent.custom_metadata.get("die_type", "moderate"))
        die_cost = DIE_COST_USD.get(die_type, DIE_COST_USD["moderate"])
        die_life = DIE_LIFE_PARTS.get(mat, DIE_LIFE_PARTS["default"])
        die_amort = (intent.target_quantity / die_life) * die_cost

        # Lubricant
        spm = SPM_BY_MATERIAL.get(mat, 35.0)
        total_strokes = intent.target_quantity
        lubricant_liters = (total_strokes / 1000.0) * LUBRICANT_L_PER_1K_STROKES.get(
            mat, 1.0
        )
        lubricant_cost = lubricant_liters * 2.50  # $2.50/L stamping oil

        return round(energy_cost + labor_cost + die_amort + lubricant_cost, 2)

    # ------------------------------------------------------------------
    # Setup sheet
    # ------------------------------------------------------------------

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material.normalized_name
        t = intent.material.thickness_mm or 3.0
        spm = SPM_BY_MATERIAL.get(mat, 35.0)

        # Estimate required tonnage from blank perimeter
        perimeter_mm = 2 * (
            (intent.material.width_mm or 100.0) + (intent.material.length_mm or 150.0)
        )
        tonnage = self._calculate_blanking_tonnage(mat, t, perimeter_mm)
        springback = SPRINGBACK_FACTOR.get(mat, 0.05)
        die_type = str(intent.custom_metadata.get("die_type", "moderate"))
        setup_min = DIE_SETUP_MINUTES.get(die_type, 60.0)

        sheet["process_parameters"] = {
            "material": mat,
            "thickness_mm": t,
            "strokes_per_minute": spm,
            "estimated_tonnage_tons": round(tonnage, 1),
            "die_type": die_type,
            "die_setup_time_minutes": setup_min,
            "springback_factor": springback,
            "lubrication": "stamping_oil",
            "coil_width_mm": intent.material.width_mm or 100.0,
            "feed_length_mm": intent.material.length_mm or 150.0,
            "total_strokes": intent.target_quantity,
        }
        return sheet

    # ------------------------------------------------------------------
    # Tooling
    # ------------------------------------------------------------------

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        mat = intent.material.normalized_name
        t = intent.material.thickness_mm or 3.0
        die_type = str(intent.custom_metadata.get("die_type", "moderate"))

        tools = [
            ToolingSpec(
                tooling_type="progressive_die",
                tool_id=f"PD-{die_type.upper()[:3]}-{mat.upper()[:3]}-{int(t*10)}T",
                description=f"{die_type.title()} progressive die for {t}mm {mat}",
                parameters={
                    "die_material": "D2_tool_steel" if mat not in {"aluminum", "copper"} else "A2_tool_steel",
                    "stations": {"simple": 2, "moderate": 6, "complex": 14}.get(die_type, 6),
                    "clearance_pct": 0.05 * t,  # 5% clearance per side
                    "expected_life_parts": DIE_LIFE_PARTS.get(mat, 500_000),
                },
            ),
            ToolingSpec(
                tooling_type="coil_feeder",
                tool_id="CF-200MM-SERVO",
                description="Servo-driven coil feeder and straightener",
                parameters={
                    "max_coil_width_mm": 300,
                    "feed_accuracy_mm": 0.05,
                    "max_coil_weight_kg": 2000,
                },
            ),
        ]
        return tools

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        return [
            FixtureSpec(
                fixture_type="die_bolster",
                description="Press bolster plate for die mounting and alignment",
                setup_time_minutes=DIE_SETUP_MINUTES.get(
                    str(intent.custom_metadata.get("die_type", "moderate")), 60.0
                ),
                parameters={
                    "t_slot_spacing_mm": 50,
                    "surface_flatness_mm": 0.025,
                    "pneumatic_die_cushion": True,
                },
            )
        ]

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        mat = intent.material.normalized_name
        t = intent.material.thickness_mm or 3.0
        springback = SPRINGBACK_FACTOR.get(mat, 0.05)

        return [
            QualityRequirement(
                inspection_method="optical_comparator",
                tolerance_class="ISO_2768_m",
                standards=["ASME Y14.5", "ISO 2768-1"],
                acceptance_criteria={
                    "burr_height_max_mm": t * 0.05,  # 5% of material thickness
                    "springback_pct": springback * 100,
                    "edge_rollover_max_mm": t * 0.10,
                    "surface_finish_ra_um": 1.6,
                },
            ),
            QualityRequirement(
                inspection_method="statistical_process_control",
                tolerance_class="ISO_2768_m",
                standards=["ISO 7966"],
                acceptance_criteria={
                    "cpk_min": 1.33,
                    "sample_size": max(30, intent.target_quantity // 100),
                    "inspection_frequency": "per_1000_parts",
                },
            ),
        ]

    # ------------------------------------------------------------------
    # Consumables
    # ------------------------------------------------------------------

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        mat = intent.material.normalized_name
        total_strokes = intent.target_quantity
        lub_per_k = LUBRICANT_L_PER_1K_STROKES.get(mat, 1.0)
        lubricant_liters = (total_strokes / 1000.0) * lub_per_k

        # Sheet material (coil) — whole blank weight
        t = intent.material.thickness_mm or 3.0
        w = intent.material.width_mm or 100.0
        l = intent.material.length_mm or 150.0
        # Material density
        density: Dict[str, float] = {
            "steel": 7.85, "aluminum": 2.70, "stainless_steel": 7.93,
            "titanium": 4.51, "copper": 8.94, "brass": 8.53,
        }
        rho = density.get(mat, 7.85)  # g/cm³
        vol_cm3 = (t / 10.0) * (w / 10.0) * (l / 10.0)
        blank_kg = vol_cm3 * rho / 1000.0  # g → kg
        # Scrap ~20% (skeleton)
        sheet_kg = blank_kg * intent.target_quantity * 1.2

        return {
            f"sheet_{mat}_kg": round(sheet_kg, 2),
            "stamping_lubricant_liters": round(lubricant_liters, 3),
        }

    # ------------------------------------------------------------------
    # Energy profile
    # ------------------------------------------------------------------

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        return EnergyProfile(
            base_power_kw=PRESS_POWER_KW["base"],
            peak_power_kw=PRESS_POWER_KW["peak"],
            idle_power_kw=PRESS_POWER_KW["idle"],
            power_curve_type="pulsed",  # peak at bottom of stroke
            duty_cycle=0.50,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _calculate_blanking_tonnage(
        self, mat_name: str, thickness_mm: float, perimeter_mm: float
    ) -> float:
        """
        Blanking force (tons):
          F = perimeter_mm × thickness_mm × shear_strength_MPa / 1000
          Convert kN → metric tons: ÷ 9.81
        """
        tau = SHEAR_STRENGTH_MPA.get(mat_name, 250.0)
        force_kn = perimeter_mm * thickness_mm * tau / 1000.0
        return force_kn / 9.81
