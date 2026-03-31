"""
Press Brake Bending Process Adapter
=====================================
Adapter for BENDING_PRESS_BRAKE (air bending and bottoming).

Key domain model:
  - Throughput: bends/minute, converted to parts/hour
  - Tonnage: required force calculated from material, thickness, die opening, length
  - Springback: material-specific angle compensation
  - Bend deduction: flat blank length calculation
  - Tools: punch + die, with V-die opening chosen from thickness
  - Quality: angle tolerance, flatness, bend radius check

Physics:
  Bending force (tons):  F = (k × σ_UTS × t² × L) / (V × 1000)
    k = 1.33 (air bend factor)
    σ_UTS = ultimate tensile strength (MPa)
    t = material thickness (mm)
    L = bend length (mm)
    V = die opening (mm), typically 8×t

  Springback angle (°): depends on material yield strength and elastic modulus.
    For most sheet metals, program 2-5° of over-bend and allow springback.

  Bend deduction (mm): BD = 2 × (BA/2 - (R + t) × tan(θ/2))
    Where BA = bend allowance, R = inside radius, θ = bend angle.
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
# Material properties for bending calculations
# ---------------------------------------------------------------------------

# Ultimate tensile strength (MPa) — used for tonnage calculation
UTS_MPA: Dict[str, float] = {
    "steel": 500.0,          # mild steel / A36
    "aluminum": 280.0,       # Al6061-T6
    "stainless_steel": 620.0,
    "titanium": 1000.0,      # Ti-6Al-4V
    "copper": 220.0,
    "brass": 350.0,
    "default": 400.0,
}

# Elastic modulus (GPa) — used for springback calculation
ELASTIC_MODULUS_GPA: Dict[str, float] = {
    "steel": 200.0,
    "aluminum": 70.0,
    "stainless_steel": 195.0,
    "titanium": 110.0,
    "copper": 115.0,
    "brass": 105.0,
    "default": 150.0,
}

# Yield strength (MPa) — used for springback factor
YIELD_STRENGTH_MPA: Dict[str, float] = {
    "steel": 250.0,
    "aluminum": 270.0,
    "stainless_steel": 310.0,
    "titanium": 880.0,
    "copper": 70.0,
    "brass": 200.0,
    "default": 200.0,
}

# Minimum inside bend radius (× thickness) by material
MIN_BEND_RADIUS_FACTOR: Dict[str, float] = {
    "steel": 1.0,            # 1t minimum
    "aluminum": 1.5,
    "stainless_steel": 1.5,
    "titanium": 3.0,         # titanium springs back a lot
    "copper": 1.0,
    "default": 1.5,
}

# Springback compensation angle (degrees) — over-bend required
SPRINGBACK_DEG: Dict[str, float] = {
    "steel": 2.0,
    "aluminum": 3.0,
    "stainless_steel": 4.0,
    "titanium": 6.0,
    "copper": 1.5,
    "default": 3.0,
}

# Bends per minute achievable (typical press brake production rate)
BENDS_PER_MINUTE: Dict[str, float] = {
    "steel": 2.0,
    "aluminum": 3.0,
    "stainless_steel": 1.5,
    "titanium": 1.0,
    "copper": 2.5,
    "default": 2.0,
}

# Press brake power consumption (kW)
PRESS_BRAKE_POWER_KW = {
    "base": 18.0,
    "peak": 45.0,   # peak on full tonnage stroke
    "idle": 2.5,
}

LABOR_RATE_USD_HOUR = 65.0
ENERGY_RATE_USD_KWH = 0.12


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class PressBrakeAdapter(BaseAdapter):
    """
    Process adapter for BENDING_PRESS_BRAKE.

    Handles air bending and bottoming. Provides:
      - Tonnage calculation (determines if the machine can handle the job)
      - Springback compensation angles
      - Bend deduction / flat blank calculations
      - V-die selection from thickness
      - Angle tolerance quality checks
    """

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.BENDING_PRESS_BRAKE

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat = intent.material

        # Bending requires sheet or plate form
        if mat.form and mat.form.lower() not in {"sheet", "plate", "flat_bar", "strip"}:
            errors.append(
                f"BENDING_PRESS_BRAKE requires sheet, plate, or flat bar stock. "
                f"Got form: '{mat.form}'."
            )

        # Polymer bending needs special consideration
        if mat.material_family.lower() == "polymer":
            if not intent.custom_metadata.get("pre_heated"):
                errors.append(
                    "BENDING_PRESS_BRAKE of polymer materials typically requires "
                    "pre-heating. Set custom_metadata['pre_heated'] = True if "
                    "pre-heating is planned."
                )

        # Check minimum bend radius
        t = mat.thickness_mm or 3.0
        mat_name = mat.normalized_name
        min_radius_factor = MIN_BEND_RADIUS_FACTOR.get(mat_name, 1.5)
        bend_radius = float(intent.custom_metadata.get("inside_radius_mm", t * min_radius_factor))
        min_radius_mm = t * min_radius_factor
        if bend_radius < min_radius_mm:
            errors.append(
                f"Inside bend radius {bend_radius}mm is below minimum for {mat_name} "
                f"at {t}mm thickness (min: {min_radius_mm:.1f}mm). "
                f"Risk of cracking or edge breakage."
            )

        # Thickness limit check
        if t > 25.0 and mat_name in {"titanium", "stainless_steel"}:
            errors.append(
                f"Thickness {t}mm for {mat_name} may exceed typical press brake capacity. "
                f"Consider die forming or hot pressing."
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

        Uses bends_per_minute for the material and total number of bends.
        Number of bends defaults to 4 (simple box part) unless specified
        in custom_metadata["bends_per_part"].
        """
        mat = intent.material.normalized_name
        bpm = BENDS_PER_MINUTE.get(mat, 2.0)
        bends_per_part = int(intent.custom_metadata.get("bends_per_part", 4))
        total_bends = bends_per_part * intent.target_quantity

        # Handling and repositioning time (seconds per bend)
        handling_secs = float(intent.custom_metadata.get("handling_secs_per_bend", 30.0))

        # Total time = press cycle time + handling time
        press_time_minutes = total_bends / bpm
        handling_minutes = (total_bends * handling_secs) / 60.0

        return round(press_time_minutes + handling_minutes, 1)

    # ------------------------------------------------------------------
    # Cost
    # ------------------------------------------------------------------

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Press brake cost: labor + energy + tooling amortization."""
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        cycle_hours = cycle_minutes / 60.0

        # Energy (press brakes have relatively modest power vs machining centers)
        avg_power = PRESS_BRAKE_POWER_KW["base"] * 0.4 + PRESS_BRAKE_POWER_KW["idle"] * 0.6
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH

        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Tooling amortization — punch/die sets cost ~$500–$1500; amortize over 50k bends
        bends_per_part = int(intent.custom_metadata.get("bends_per_part", 4))
        total_bends = bends_per_part * intent.target_quantity
        tooling_amortization = (total_bends / 50_000.0) * 800.0  # $800 mid-range tooling set

        return round(energy_cost + labor_cost + tooling_amortization, 2)

    # ------------------------------------------------------------------
    # Setup sheet
    # ------------------------------------------------------------------

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material.normalized_name
        t = intent.material.thickness_mm or 3.0
        bend_angle = float(intent.custom_metadata.get("bend_angle_deg", 90.0))
        bend_length_mm = intent.material.width_mm or 200.0
        inside_radius = float(intent.custom_metadata.get("inside_radius_mm", t * 1.0))

        # Calculate tooling requirements
        v_die_mm = self._select_v_die(t)
        tonnage = self._calculate_tonnage(mat, t, bend_length_mm, v_die_mm)
        springback = SPRINGBACK_DEG.get(mat, 3.0)
        bend_deduction = self._bend_deduction(t, inside_radius, bend_angle)

        sheet["process_parameters"] = {
            "material": mat,
            "thickness_mm": t,
            "bend_angle_deg": bend_angle,
            "program_angle_deg": bend_angle + springback,   # over-bend to account for springback
            "springback_compensation_deg": springback,
            "bend_length_mm": bend_length_mm,
            "v_die_opening_mm": v_die_mm,
            "inside_bend_radius_mm": inside_radius,
            "required_tonnage_tons": round(tonnage, 1),
            "bend_deduction_mm": round(bend_deduction, 2),
            "bends_per_part": intent.custom_metadata.get("bends_per_part", 4),
            "flat_blank_length_mm": self._flat_blank_length(intent),
            "back_gauge_position_mm": self._back_gauge_mm(intent),
        }
        return sheet

    # ------------------------------------------------------------------
    # Tooling
    # ------------------------------------------------------------------

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        """Return punch and V-die based on material thickness."""
        t = intent.material.thickness_mm or 3.0
        v_die_mm = self._select_v_die(t)
        punch_radius = max(0.5, t * 0.5)  # punch nose radius ≈ 0.5 × thickness

        return [
            ToolingSpec(
                tooling_type="press_brake_punch",
                tool_id=f"PBP-90-{int(punch_radius * 10)}R",
                description=f"90° acute punch, {punch_radius}mm nose radius",
                parameters={
                    "angle_deg": 88,     # 88° to allow air bending spring-back
                    "nose_radius_mm": punch_radius,
                    "length_mm": 835,    # standard segment length
                    "material": "D2_tool_steel",
                },
            ),
            ToolingSpec(
                tooling_type="press_brake_v_die",
                tool_id=f"VD-{int(v_die_mm)}V-{int(t)}T",
                description=f"{v_die_mm}mm V-die for {t}mm stock",
                parameters={
                    "v_opening_mm": v_die_mm,
                    "die_angle_deg": 86,
                    "radius_mm": v_die_mm * 0.1,
                    "length_mm": 835,
                },
            ),
        ]

    # ------------------------------------------------------------------
    # Fixtures
    # ------------------------------------------------------------------

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        """Back gauge and front support arm for press brake."""
        return [
            FixtureSpec(
                fixture_type="back_gauge",
                description="CNC back gauge for part positioning",
                setup_time_minutes=5.0,
                parameters={
                    "axes": "X_R",
                    "repeatability_mm": 0.1,
                    "max_reach_mm": 750,
                },
            ),
            FixtureSpec(
                fixture_type="front_support_arm",
                description="Front support arm to prevent deflection on long parts",
                setup_time_minutes=10.0,
                parameters={"max_part_weight_kg": 80.0},
            ),
        ]

    # ------------------------------------------------------------------
    # Quality checks
    # ------------------------------------------------------------------

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """Bending quality: angle tolerance + flatness + minimum bend radius."""
        t = intent.material.thickness_mm or 3.0
        checks = [
            QualityRequirement(
                inspection_method="angle_gauge",
                tolerance_class="ISO_2768_m",
                standards=["ASME Y14.5", "ISO 2768-1"],
                acceptance_criteria={
                    "angle_tolerance_deg": 1.0,    # ±1° for ISO 2768 medium
                    "flatness_mm": t * 0.5,
                    "edge_crack_acceptable": False,
                },
            )
        ]

        # For tight-tolerance bends (aerospace / precision sheet metal)
        if intent.custom_metadata.get("tight_tolerance"):
            checks.append(
                QualityRequirement(
                    inspection_method="CMM",
                    tolerance_class="ISO_2768_f",
                    standards=["ASME Y14.5"],
                    acceptance_criteria={
                        "angle_tolerance_deg": 0.25,
                        "flatness_mm": 0.5,
                    },
                )
            )

        return checks

    # ------------------------------------------------------------------
    # Consumables
    # ------------------------------------------------------------------

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        """Press brake consumables: raw sheet/plate (minimal waste — bend, not cut)."""
        mat = intent.material.normalized_name
        # Bending doesn't remove material but we account for scrap/offcuts (~3%)
        t = intent.material.thickness_mm or 3.0
        w = intent.material.width_mm or 200.0
        l = intent.material.length_mm or 300.0
        volume_m3 = (t / 1000.0) * (w / 1000.0) * (l / 1000.0)

        # Material density fallback by family
        density_kg_m3 = intent.material.density_kg_m3 or _DENSITY_KG_M3.get(mat, 7850.0)
        part_kg = volume_m3 * density_kg_m3

        return {
            f"sheet_{mat}_kg": round(part_kg * intent.target_quantity * 1.03, 3)  # 3% scrap
        }

    # ------------------------------------------------------------------
    # Energy profile
    # ------------------------------------------------------------------

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        return EnergyProfile(
            base_power_kw=PRESS_BRAKE_POWER_KW["base"],
            peak_power_kw=PRESS_BRAKE_POWER_KW["peak"],
            idle_power_kw=PRESS_BRAKE_POWER_KW["idle"],
            power_curve_type="pulsed",    # intermittent ram strokes
            duty_cycle=0.40,              # ~40% of time is actual press stroke
        )

    # ------------------------------------------------------------------
    # Calculation helpers
    # ------------------------------------------------------------------

    def _select_v_die(self, thickness_mm: float) -> float:
        """
        Select V-die opening based on material thickness.
        Industry rule of thumb: V = 6–8× thickness.
        """
        if thickness_mm <= 1.5:
            return 8.0
        elif thickness_mm <= 3.0:
            return 16.0
        elif thickness_mm <= 6.0:
            return 40.0
        elif thickness_mm <= 10.0:
            return 60.0
        elif thickness_mm <= 16.0:
            return 100.0
        else:
            return thickness_mm * 8.0

    def _calculate_tonnage(
        self,
        mat_name: str,
        thickness_mm: float,
        bend_length_mm: float,
        v_die_mm: float,
    ) -> float:
        """
        Air bending force formula (metric tons):
        F = (1.33 × σ_UTS × t² × L) / (V × 1000)

        Returns force in tons.
        """
        uts = UTS_MPA.get(mat_name, UTS_MPA["default"])
        k = 1.33
        force_kn = (k * uts * thickness_mm**2 * bend_length_mm) / (v_die_mm * 1000.0)
        return force_kn / 9.81  # kN to metric tons (1 ton ≈ 9.81 kN)

    def _bend_deduction(self, t: float, inside_radius: float, angle_deg: float) -> float:
        """
        Bend deduction (BD) = 2 × outside setback - bend allowance.

        Uses the K-factor method with K = 0.33 for sharp bends.
        """
        k_factor = 0.33
        angle_rad = math.radians(angle_deg)
        ba = (inside_radius + k_factor * t) * angle_rad
        ossb = (inside_radius + t) * math.tan(angle_rad / 2.0)
        bd = 2.0 * ossb - ba
        return bd

    def _flat_blank_length(self, intent: ManufacturingIntent) -> Optional[float]:
        """Compute flat blank length if material length and bend data are available."""
        mat = intent.material
        if mat.length_mm is None or mat.thickness_mm is None:
            return None

        bends = int(intent.custom_metadata.get("bends_per_part", 4))
        inside_radius = float(
            intent.custom_metadata.get("inside_radius_mm", mat.thickness_mm * 1.0)
        )
        bend_angle = float(intent.custom_metadata.get("bend_angle_deg", 90.0))
        bd = self._bend_deduction(mat.thickness_mm, inside_radius, bend_angle)

        # Flat blank = (leg1 + leg2 + ... + legN) - (N-1) × BD
        # Approximation: equal legs
        leg = mat.length_mm / bends if bends > 0 else mat.length_mm
        flat_length = (leg * bends) - ((bends - 1) * bd)
        return round(flat_length, 1)

    def _back_gauge_mm(self, intent: ManufacturingIntent) -> Optional[float]:
        """Compute back gauge setback for the first bend."""
        mat = intent.material
        if mat.length_mm is None or mat.thickness_mm is None:
            return None
        inside_radius = float(
            intent.custom_metadata.get("inside_radius_mm", mat.thickness_mm * 1.0)
        )
        flange_length = float(intent.custom_metadata.get("flange_length_mm", 50.0))
        # Back gauge position = flange length - (inside radius + thickness/2)
        return round(flange_length - (inside_radius + mat.thickness_mm / 2.0), 1)


# ---------------------------------------------------------------------------
# Material density fallback (kg/m³)
# ---------------------------------------------------------------------------

_DENSITY_KG_M3: Dict[str, float] = {
    "steel": 7850.0,
    "aluminum": 2700.0,
    "stainless_steel": 7900.0,
    "titanium": 4510.0,
    "copper": 8940.0,
    "brass": 8530.0,
    "default": 7850.0,
}
