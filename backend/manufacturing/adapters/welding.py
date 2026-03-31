"""
Welding Process Adapter
=========================
Covers arc (MIG/TIG/SMAW), laser, and electron beam welding (EBW).
Each process variant has its own throughput model, consumables, and QC requirements.

Key domain model differences from CNC milling:
  - Throughput: mm/min travel speed (weld bead length), not units/hour
  - Consumables: filler wire (kg) + shielding gas (m³) + tungsten electrodes
  - Quality: AWS D1.1 structural weld, radiographic (RT), ultrasonic (UT), dye penetrant (PT)
  - Energy: arc welding has pulsed power curve; laser has high peak vs low average
  - Setup: includes pre-heat for thick carbon steel, purge time for stainless

Supported ProcessFamilies:
  - WELDING_ARC (MIG, TIG, SMAW combined under one adapter)
  - WELDING_LASER
  - WELDING_EBW

Each has a separate concrete class; a factory function `get_welding_adapter` returns
the correct instance by ProcessFamily.
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
# Shared welding constants
# ---------------------------------------------------------------------------

# Weld travel speed (mm/min) by process and material
TRAVEL_SPEED_MM_MIN: Dict[str, Dict[str, float]] = {
    "arc": {
        "steel": 350.0,
        "aluminum": 500.0,
        "stainless_steel": 250.0,
        "titanium": 200.0,
        "default": 300.0,
    },
    "laser": {
        "steel": 3000.0,
        "aluminum": 4000.0,
        "stainless_steel": 2500.0,
        "titanium": 2000.0,
        "default": 2500.0,
    },
    "ebw": {
        "steel": 1500.0,
        "aluminum": 2500.0,
        "titanium": 1200.0,
        "default": 1500.0,
    },
}

# Filler wire consumption (kg/meter of weld) by material and process
FILLER_WIRE_KG_PER_M: Dict[str, Dict[str, float]] = {
    "arc": {
        "steel": 0.08,       # ER70S-6
        "aluminum": 0.04,    # ER4043
        "stainless_steel": 0.09,  # ER308L
        "titanium": 0.05,    # ERTi-2
        "default": 0.07,
    },
    "laser": {
        "steel": 0.0,        # autogenous laser weld (usually no filler)
        "aluminum": 0.02,
        "default": 0.0,
    },
    "ebw": {
        "steel": 0.0,        # EBW is always autogenous
        "default": 0.0,
    },
}

# Shielding gas consumption (m³/hour) by process
GAS_M3_PER_HOUR: Dict[str, float] = {
    "arc": 0.6,        # typical MIG/TIG flow rate 10 L/min → 0.6 m³/hr
    "laser": 0.2,      # cross-jet shielding
    "ebw": 0.0,        # EBW is in vacuum — no shielding gas
}

# Pre-heat temperatures for thick-section carbon steel (°C)
PREHEAT_TEMP_C = 150

# Welding power draw (kW)
WELDING_POWER_KW: Dict[str, Dict[str, float]] = {
    "arc": {"base": 8.0, "peak": 15.0, "idle": 1.0},
    "laser": {"base": 3.0, "peak": 25.0, "idle": 0.5},   # laser has very high peak
    "ebw": {"base": 15.0, "peak": 30.0, "idle": 3.0},    # vacuum chamber + e-beam
}

# Labor rate
LABOR_RATE_USD_HOUR = 80.0
ENERGY_RATE_USD_KWH = 0.12

# Wire cost (USD/kg) by filler type
FILLER_WIRE_COST_USD_KG: Dict[str, float] = {
    "er70s6": 3.5,
    "er4043": 6.0,
    "er308l": 12.0,
    "erti2": 45.0,
    "default": 8.0,
}

# Shielding gas cost (USD/m³)
GAS_COST_USD_M3 = 0.85   # argon mix


# ---------------------------------------------------------------------------
# Base Welding Adapter (internal)
# ---------------------------------------------------------------------------


class _BaseWeldingAdapter(BaseAdapter):
    """Shared logic for all welding variants. Not registered directly."""

    _variant: str = "arc"  # "arc" | "laser" | "ebw"

    @property
    def process_family(self) -> ProcessFamily:
        raise NotImplementedError

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat_family = intent.material.material_family.lower()

        if mat_family not in {"ferrous", "non_ferrous"}:
            errors.append(
                f"Welding requires metallic materials. "
                f"Material family '{mat_family}' is not weldable."
            )

        # EBW requires vacuum — check for clean room or vacuum chamber
        if self._variant == "ebw" and not intent.custom_metadata.get("vacuum_chamber"):
            errors.append(
                "WELDING_EBW requires a vacuum chamber environment. "
                "Set custom_metadata['vacuum_chamber'] = True or use WELDING_LASER."
            )

        # Thick section check for arc welding
        if self._variant == "arc":
            t = intent.material.thickness_mm
            if t is not None and t > 50.0:
                errors.append(
                    f"Thickness {t}mm exceeds typical single-pass arc weld capability (50mm max). "
                    f"Consider multipass welding procedure or SAW (submerged arc)."
                )

        return errors

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate weld cycle time in minutes.

        Uses travel speed (mm/min) and weld length (from intent metadata or
        derived from geometry). Adds pre-heat time for thick carbon steel.
        """
        weld_length_mm = float(intent.custom_metadata.get("weld_length_mm", 500.0))
        speed_map = TRAVEL_SPEED_MM_MIN.get(self._variant, {})
        mat = intent.material.normalized_name
        speed = speed_map.get(mat, speed_map.get("default", 300.0))

        # Per-joint travel time (minutes)
        joint_time = weld_length_mm / speed

        # Number of weld passes (more for thick material)
        t = intent.material.thickness_mm or 6.0
        passes = max(1, math.ceil(t / 6.0))  # ~6mm per pass max

        # Pre-heat time for carbon steel > 12mm
        preheat_time = 0.0
        if (
            self._variant == "arc"
            and "steel" in mat
            and "stainless" not in mat
            and t > 12.0
        ):
            preheat_time = 20.0  # 20 min torch preheat

        total_per_unit = (joint_time * passes) + preheat_time
        return round(total_per_unit * intent.target_quantity, 1)

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Weld cost: labor + energy + filler wire + shielding gas.
        """
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        cycle_hours = cycle_minutes / 60.0

        power = WELDING_POWER_KW.get(self._variant, {"base": 8.0, "peak": 15.0, "idle": 1.0})
        avg_power = power["base"] * 0.7 + power["idle"] * 0.3
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH
        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Consumables
        consumables = self.get_consumables(intent)
        wire_kg = consumables.get("filler_wire_kg", 0.0)
        gas_m3 = consumables.get("shielding_gas_m3", 0.0)

        wire_cost = wire_kg * FILLER_WIRE_COST_USD_KG.get("default", 8.0)
        gas_cost = gas_m3 * GAS_COST_USD_M3

        return round(energy_cost + labor_cost + wire_cost + gas_cost, 2)

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material.normalized_name
        t = intent.material.thickness_mm or 6.0

        speed_map = TRAVEL_SPEED_MM_MIN.get(self._variant, {})
        travel_speed = speed_map.get(mat, speed_map.get("default", 300.0))

        sheet["process_parameters"] = {
            "variant": self._variant.upper(),
            "travel_speed_mm_min": travel_speed,
            "thickness_mm": t,
            "joint_type": intent.custom_metadata.get("joint_type", "butt"),
            "weld_length_mm": intent.custom_metadata.get("weld_length_mm", 500.0),
            "passes": max(1, math.ceil(t / 6.0)),
            "preheat_temp_c": PREHEAT_TEMP_C if (
                self._variant == "arc" and t > 12.0 and "stainless" not in mat
            ) else None,
            "post_weld_heat_treat": intent.custom_metadata.get("pwht", False),
            "shielding_gas": self._shielding_gas(mat),
            "filler_designation": self._filler_designation(mat),
        }
        return sheet

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        mat = intent.material.normalized_name
        tools: List[ToolingSpec] = []

        if self._variant == "arc":
            tools.append(
                ToolingSpec(
                    tooling_type="mig_torch" if "steel" in mat or "aluminum" in mat else "tig_torch",
                    tool_id=f"TORCH-{self._variant.upper()}-{mat.upper()[:3]}",
                    description=f"MIG/TIG torch for {mat}",
                    parameters={
                        "wire_diameter_mm": 0.9 if "aluminum" in mat else 1.2,
                        "contact_tip_size": "1.2mm",
                        "liner": "teflon" if "aluminum" in mat else "steel",
                    },
                )
            )
        elif self._variant == "laser":
            tools.append(
                ToolingSpec(
                    tooling_type="laser_head",
                    tool_id="LASER-HEAD-YAG",
                    description="Nd:YAG / fiber laser welding head",
                    parameters={
                        "wavelength_nm": 1064,
                        "spot_diameter_um": 200,
                        "focal_length_mm": 150,
                    },
                )
            )
        elif self._variant == "ebw":
            tools.append(
                ToolingSpec(
                    tooling_type="electron_beam_gun",
                    tool_id="EBW-GUN-150KV",
                    description="150 kV electron beam gun assembly",
                    parameters={"accelerating_voltage_kv": 150, "beam_current_ma": 100},
                )
            )

        return tools

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        joint_type = intent.custom_metadata.get("joint_type", "butt")
        return [
            FixtureSpec(
                fixture_type="weld_jig",
                description=f"Weld jig for {joint_type} joint fixture and fit-up",
                setup_time_minutes=25.0,
                parameters={
                    "joint_type": joint_type,
                    "clamps": 4,
                    "backing_bar": joint_type == "butt",
                },
            )
        ]

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """Weld quality checks per AWS D1.1 and radiographic/ultrasonic inspection."""
        checks = [
            QualityRequirement(
                inspection_method="visual_weld_inspection",
                tolerance_class="AWS_D1_1",
                standards=["AWS D1.1", "ISO 5817"],
                acceptance_criteria={
                    "undercut_max_mm": 0.5,
                    "porosity_pct_max": 1.0,
                    "crack_acceptable": False,
                },
            )
        ]

        # Add RT or UT for structural / pressure-bearing welds
        if intent.custom_metadata.get("structural") or intent.custom_metadata.get("pressure_bearing"):
            checks.append(
                QualityRequirement(
                    inspection_method="radiographic" if self._variant in {"arc", "ebw"} else "ultrasonic",
                    tolerance_class="AWS_D1_1",
                    standards=["AWS D1.1", "ASME VIII Div.1"],
                    acceptance_criteria={
                        "indication_length_max_mm": 6.0,
                        "linear_indication_acceptable": False,
                    },
                )
            )

        # Add dye penetrant for titanium and stainless
        mat = intent.material.normalized_name
        if "titanium" in mat or "stainless" in mat:
            checks.append(
                QualityRequirement(
                    inspection_method="dye_penetrant",
                    tolerance_class="ISO_2768_m",
                    standards=["ASTM E165", "NAS 999"],
                    acceptance_criteria={"linear_indication_acceptable": False},
                )
            )

        return checks

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        mat = intent.material.normalized_name
        cycle_hours = self.estimate_cycle_time(intent, _DUMMY_MACHINE) / 60.0
        weld_m = float(intent.custom_metadata.get("weld_length_mm", 500.0)) / 1000.0 * intent.target_quantity

        wire_map = FILLER_WIRE_KG_PER_M.get(self._variant, {})
        wire_kg_per_m = wire_map.get(mat, wire_map.get("default", 0.0))
        filler_kg = wire_kg_per_m * weld_m

        gas_m3 = GAS_M3_PER_HOUR.get(self._variant, 0.0) * cycle_hours

        consumables: Dict[str, float] = {}
        if filler_kg > 0:
            consumables["filler_wire_kg"] = round(filler_kg, 3)
        if gas_m3 > 0:
            consumables["shielding_gas_m3"] = round(gas_m3, 3)

        return consumables

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        p = WELDING_POWER_KW.get(self._variant, {"base": 8.0, "peak": 15.0, "idle": 1.0})
        curve = "pulsed" if self._variant == "arc" else "constant"
        return EnergyProfile(
            base_power_kw=p["base"],
            peak_power_kw=p["peak"],
            idle_power_kw=p["idle"],
            power_curve_type=curve,
            duty_cycle=0.60 if self._variant == "arc" else 0.80,
        )

    def _shielding_gas(self, mat: str) -> str:
        if self._variant == "ebw":
            return "none_vacuum"
        if "aluminum" in mat:
            return "argon_100pct"
        if "titanium" in mat:
            return "argon_100pct"
        if "stainless" in mat:
            return "argon_co2_98_2"
        return "argon_co2_75_25_c25"

    def _filler_designation(self, mat: str) -> str:
        if self._variant == "ebw":
            return "none_autogenous"
        if "aluminum" in mat:
            return "ER4043"
        if "titanium" in mat:
            return "ERTi-2"
        if "stainless" in mat:
            return "ER308L"
        return "ER70S-6"


# ---------------------------------------------------------------------------
# Public concrete adapters
# ---------------------------------------------------------------------------


class ArcWeldingAdapter(_BaseWeldingAdapter):
    """Adapter for WELDING_ARC (MIG, TIG, SMAW)."""

    _variant = "arc"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.WELDING_ARC


class LaserWeldingAdapter(_BaseWeldingAdapter):
    """Adapter for WELDING_LASER (fiber / Nd:YAG)."""

    _variant = "laser"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.WELDING_LASER

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat = intent.material.normalized_name

        # Laser does not work well on highly reflective materials
        if mat in {"copper", "brass", "gold", "silver"}:
            errors.append(
                f"WELDING_LASER is not suitable for highly reflective material '{mat}'. "
                f"Consider WELDING_ARC or WELDING_EBW."
            )
        return errors


class EBWeldingAdapter(_BaseWeldingAdapter):
    """Adapter for WELDING_EBW (electron beam welding)."""

    _variant = "ebw"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.WELDING_EBW

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        # EBW requires small batch — chamber loading is expensive
        if intent.target_quantity > 100:
            errors.append(
                f"WELDING_EBW batch size of {intent.target_quantity} is unusually high. "
                f"EBW is best suited for prototype and small-batch production (< 100 units)."
            )
        return errors


# ---------------------------------------------------------------------------
# Factory function
# ---------------------------------------------------------------------------


def get_welding_adapter(family: ProcessFamily) -> Optional[_BaseWeldingAdapter]:
    """Return the welding adapter for the given ProcessFamily, or None."""
    mapping = {
        ProcessFamily.WELDING_ARC: ArcWeldingAdapter,
        ProcessFamily.WELDING_LASER: LaserWeldingAdapter,
        ProcessFamily.WELDING_EBW: EBWeldingAdapter,
    }
    cls = mapping.get(family)
    return cls() if cls else None


# ---------------------------------------------------------------------------
# Dummy machine for standalone consumables estimation
# ---------------------------------------------------------------------------

from ..registry import MachineCapability as _MC  # noqa: E402

_DUMMY_MACHINE = _MC(
    machine_id="_internal_weld_dummy",
    machine_name="Dummy",
    machine_type="WELDER",
    capabilities=[],
)
