"""
EDM (Electrical Discharge Machining) Process Adapters
======================================================
Covers wire EDM and sinker (ram/die-sinking) EDM.

Both processes use electrical spark erosion to remove material from
electrically conductive workpieces. The workpiece is always submerged
in dielectric fluid (deionized water or oil).

Key domain model:
  - Only electrically conductive materials can be machined (metals, graphite)
  - Throughput measured in mm²/min MRR (Material Removal Rate)
  - No cutting force → zero tool deflection → excellent for fragile parts
  - Surface finish Ra improves with finer spark settings (slower MRR)
  - Heat-affected zone (HAZ) is minimal compared to conventional cutting

Wire EDM (WEDM):
  - Thin wire electrode (0.1–0.3 mm brass wire) cuts a 2D profile
  - Extremely tight tolerances: ±0.002–0.005 mm typical
  - Limited to through-cuts (no pockets)
  - Throughput: 20–100 mm²/min depending on material and thickness

Sinker EDM (Die Sinking / Ram EDM):
  - Shaped graphite or copper electrode burns 3D cavity into workpiece
  - Used for complex mold cavities, blind keyways, non-machinable shapes
  - Slower than wire but enables 3D features
  - Electrode wear: 5–15% of workpiece removal volume

Supported ProcessFamilies:
  - EDM_WIRE
  - EDM_SINKER
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
# Shared EDM constants
# ---------------------------------------------------------------------------

# Material Removal Rate (mm²/min) by process and material
# Wire EDM: area cut per minute in cross-section
# Sinker EDM: volume removal rate (mm³/min) ÷ typical depth (mm) → area/min equivalent
MRR_MM2_MIN: Dict[str, Dict[str, float]] = {
    "wire": {
        "steel": 35.0,             # tool steel, 40 mm thick
        "aluminum": 80.0,
        "stainless_steel": 25.0,
        "titanium": 15.0,
        "copper": 45.0,
        "brass": 60.0,
        "tungsten": 5.0,           # very slow on refractory metals
        "default": 30.0,
    },
    "sinker": {
        "steel": 8.0,              # tool steel, rough setting
        "aluminum": 25.0,
        "stainless_steel": 6.0,
        "titanium": 4.0,
        "copper": 15.0,
        "graphite": 30.0,          # graphite electrode burns into itself too
        "default": 8.0,
    },
}

# Surface finish (Ra µm) achievable — depends on spark energy setting
SURFACE_FINISH_RA_UM: Dict[str, Dict[str, float]] = {
    "wire": {
        "rough": 3.2,      # skim cut 1: stock removal
        "medium": 1.6,     # skim cut 2: semi-finish
        "fine": 0.4,       # skim cut 3: finish
    },
    "sinker": {
        "rough": 6.3,
        "medium": 1.6,
        "fine": 0.4,
    },
}

# Power draw (kW) by EDM type
EDM_POWER_KW: Dict[str, Dict[str, float]] = {
    "wire": {"base": 3.0, "peak": 8.0, "idle": 0.8},
    "sinker": {"base": 5.0, "peak": 15.0, "idle": 1.5},
}

# Dielectric fluid consumption (liters/hour)
DIELECTRIC_L_PER_HOUR: Dict[str, float] = {
    "wire": 0.5,     # water losses from ionization
    "sinker": 1.0,   # oil losses from vaporization
}

# Wire electrode consumption (meters/hour) — wire EDM
WIRE_CONSUMPTION_M_PER_HOUR = 5.0  # typical for 0.25mm brass wire
WIRE_COST_USD_PER_KG = 12.0        # 0.25mm brass wire
WIRE_MASS_KG_PER_M = 0.000045      # 0.25mm wire: 45 mg/m

# Electrode wear (sinker) — fraction of workpiece MRR
ELECTRODE_WEAR_FRACTION: Dict[str, float] = {
    "graphite": 0.05,   # 5% wear (graphite is best)
    "copper": 0.10,
    "default": 0.08,
}

LABOR_RATE_USD_HOUR = 75.0
ENERGY_RATE_USD_KWH = 0.12


# ---------------------------------------------------------------------------
# Base EDM Adapter (internal)
# ---------------------------------------------------------------------------


class _BaseEDMAdapter(BaseAdapter):
    """Shared logic for wire and sinker EDM. Not registered directly."""

    _variant: str = "wire"  # "wire" | "sinker"

    @property
    def process_family(self) -> ProcessFamily:
        raise NotImplementedError

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat_family = intent.material.material_family.lower()

        # EDM requires electrically conductive materials
        if mat_family in {"polymer", "composite", "ceramic"}:
            errors.append(
                f"EDM requires electrically conductive materials. "
                f"Material family '{mat_family}' is not suitable for EDM. "
                f"Consider CNC milling or laser cutting."
            )

        # Wire EDM only cuts through-cuts
        if self._variant == "wire":
            if intent.custom_metadata.get("blind_feature"):
                errors.append(
                    "WIRE EDM can only perform through-cuts. For blind pockets "
                    "and 3D cavities, use SINKER EDM or CNC milling."
                )

        # Sinker EDM large batches are slow and expensive
        if self._variant == "sinker" and intent.target_quantity > 50:
            errors.append(
                f"SINKER EDM for {intent.target_quantity} units is likely uneconomical. "
                f"Consider die casting or CNC milling for quantities > 50. "
                f"Sinker EDM is best for prototype cavities and small tooling runs."
            )

        # Material thickness check for wire EDM
        if self._variant == "wire":
            t = intent.material.thickness_mm
            if t is not None and t > 300.0:
                errors.append(
                    f"Wire EDM workpiece height {t}mm exceeds practical limits (~300mm). "
                    f"Accuracy degrades on tall workpieces due to wire deflection."
                )

        return errors

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total EDM cycle time in minutes.

        Wire EDM:   cut_area_mm2 / MRR × quantity
        Sinker EDM: volume_mm3 / MRR × quantity (approximated as depth × cross-section)
        """
        mat = intent.material.normalized_name
        mrr_map = MRR_MM2_MIN.get(self._variant, {})
        mrr = mrr_map.get(mat, mrr_map.get("default", 20.0))

        if self._variant == "wire":
            # Cut area = thickness × cut_path_length
            thickness = intent.material.thickness_mm or 30.0
            cut_path_mm = float(intent.custom_metadata.get("cut_path_mm", 200.0))
            cut_area_mm2 = thickness * cut_path_mm
            # Allow for skim cuts (finish passes)
            skim_cuts = int(intent.custom_metadata.get("skim_cuts", 2))
            total_area = cut_area_mm2 * (1 + skim_cuts * 0.5)
        else:
            # Sinker: cavity volume ≈ depth × width × length of feature
            depth_mm = float(intent.custom_metadata.get("cavity_depth_mm", 15.0))
            feature_w = intent.material.width_mm or 30.0
            feature_l = intent.material.length_mm or 40.0
            total_area = depth_mm * max(feature_w, feature_l)

        time_per_unit = total_area / mrr if mrr > 0 else 9999.0

        # Add electrode setup and re-positioning time
        setup_per_unit = {"wire": 15.0, "sinker": 30.0}.get(self._variant, 20.0)

        return round((time_per_unit + setup_per_unit) * intent.target_quantity, 1)

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """EDM cost: energy + labor + wire or electrode + dielectric."""
        cycle_hours = self.estimate_cycle_time(intent, machine) / 60.0

        p = EDM_POWER_KW.get(self._variant, {"base": 3.0, "idle": 0.8})
        avg_power = p["base"] * 0.70 + p["idle"] * 0.30
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH
        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Wire or electrode cost
        consumables = self.get_consumables(intent)
        cons_cost = 0.0
        if self._variant == "wire":
            wire_m = consumables.get("edm_wire_m", 0.0)
            cons_cost = wire_m * WIRE_MASS_KG_PER_M * WIRE_COST_USD_PER_KG
        else:
            # Electrode cost: graphite electrode ~$50–$200 each
            electrodes = consumables.get("graphite_electrode_fraction", 0.0)
            cons_cost = electrodes * 120.0  # $120 per electrode

        return round(energy_cost + labor_cost + cons_cost, 2)

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material.normalized_name

        if self._variant == "wire":
            sheet["process_parameters"] = {
                "variant": "WIRE_EDM",
                "wire_diameter_mm": float(intent.custom_metadata.get("wire_diameter_mm", 0.25)),
                "wire_material": "brass",
                "dielectric": "deionized_water",
                "tension_n": 20.0,
                "cut_speed_mm_min": MRR_MM2_MIN["wire"].get(mat, 30.0) / (intent.material.thickness_mm or 30.0),
                "skim_cuts": int(intent.custom_metadata.get("skim_cuts", 2)),
                "achievable_tolerance_mm": 0.003,
                "achievable_ra_um": SURFACE_FINISH_RA_UM["wire"]["fine"],
                "material": mat,
                "workpiece_height_mm": intent.material.thickness_mm or 30.0,
            }
        else:
            electrode_material = str(intent.custom_metadata.get("electrode_material", "graphite"))
            sheet["process_parameters"] = {
                "variant": "SINKER_EDM",
                "electrode_material": electrode_material,
                "dielectric": str(intent.custom_metadata.get("dielectric", "edm_oil")),
                "polarity": "normal" if electrode_material == "graphite" else "reverse",
                "peak_current_a": int(intent.custom_metadata.get("peak_current_a", 40)),
                "pulse_on_us": 200,
                "pulse_off_us": 50,
                "achievable_tolerance_mm": 0.010,
                "achievable_ra_um": SURFACE_FINISH_RA_UM["sinker"]["medium"],
                "electrode_wear_pct": ELECTRODE_WEAR_FRACTION.get(electrode_material, 0.08) * 100,
                "material": mat,
                "cavity_depth_mm": intent.custom_metadata.get("cavity_depth_mm", 15.0),
            }

        return sheet

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        tools: List[ToolingSpec] = []

        if self._variant == "wire":
            wire_dia = float(intent.custom_metadata.get("wire_diameter_mm", 0.25))
            tools.append(ToolingSpec(
                tooling_type="edm_wire",
                tool_id=f"EDM-WIRE-BRASS-{int(wire_dia * 100)}",
                description=f"{wire_dia}mm diameter brass EDM wire spool (8 kg)",
                parameters={
                    "diameter_mm": wire_dia,
                    "material": "brass_65Cu_35Zn",
                    "tensile_strength_mpa": 900,
                    "spool_kg": 8.0,
                    "consumption_m_per_hour": WIRE_CONSUMPTION_M_PER_HOUR,
                },
            ))
        else:
            electrode_mat = str(intent.custom_metadata.get("electrode_material", "graphite"))
            tools.append(ToolingSpec(
                tooling_type="edm_electrode",
                tool_id=f"EDM-ELEC-{electrode_mat.upper()[:4]}",
                description=f"{electrode_mat.title()} EDM electrode (custom-machined to cavity shape)",
                parameters={
                    "material": electrode_mat,
                    "grade": "EDM-3 fine grain" if electrode_mat == "graphite" else "CuW70",
                    "wear_ratio": ELECTRODE_WEAR_FRACTION.get(electrode_mat, 0.08),
                    "surface_finish_ra_um": 0.8,
                    "oversize_mm": 0.10,  # undersize to account for gap
                },
            ))

        return tools

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        return [
            FixtureSpec(
                fixture_type="edm_vise",
                description="Precision EDM vise (non-magnetic, corrosion resistant)",
                setup_time_minutes=20.0 if self._variant == "wire" else 35.0,
                parameters={
                    "material": "stainless_steel",
                    "jaw_width_mm": 100,
                    "repeatability_mm": 0.002,
                    "magnetic_base": False,
                },
            )
        ]

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        finish_setting = str(intent.custom_metadata.get("finish", "medium"))
        ra_um = SURFACE_FINISH_RA_UM.get(self._variant, {}).get(finish_setting, 1.6)

        checks = [
            QualityRequirement(
                inspection_method="CMM",
                tolerance_class="ISO_2768_f",
                standards=["ISO 2768-1", "ASME Y14.5"],
                acceptance_criteria={
                    "position_tolerance_mm": 0.005 if self._variant == "wire" else 0.010,
                    "surface_finish_ra_um": ra_um,
                    "no_recast_layer": True,
                },
            )
        ]

        # For aerospace / tool steel parts, require recast layer check
        if intent.custom_metadata.get("aerospace") or intent.custom_metadata.get("check_recast"):
            checks.append(
                QualityRequirement(
                    inspection_method="metallographic_section",
                    tolerance_class="ISO_2768_f",
                    standards=["AMS 2753"],
                    acceptance_criteria={
                        "recast_layer_max_um": 10,
                        "haz_depth_max_um": 50,
                    },
                )
            )

        return checks

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        cycle_hours = self.estimate_cycle_time(intent, _DUMMY_MACHINE) / 60.0

        consumables: Dict[str, float] = {}

        if self._variant == "wire":
            wire_m = WIRE_CONSUMPTION_M_PER_HOUR * cycle_hours
            consumables["edm_wire_m"] = round(wire_m, 1)
            di_water_liters = DIELECTRIC_L_PER_HOUR["wire"] * cycle_hours
            consumables["deionized_water_liters"] = round(di_water_liters, 2)
        else:
            electrode_wear = ELECTRODE_WEAR_FRACTION.get(
                str(intent.custom_metadata.get("electrode_material", "graphite")), 0.08
            )
            # Fraction of one electrode consumed per job
            consumables["graphite_electrode_fraction"] = round(
                min(1.0, electrode_wear * intent.target_quantity), 3
            )
            edm_oil_liters = DIELECTRIC_L_PER_HOUR["sinker"] * cycle_hours
            consumables["edm_dielectric_oil_liters"] = round(edm_oil_liters, 2)

        return consumables

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        p = EDM_POWER_KW.get(self._variant, {"base": 3.0, "peak": 8.0, "idle": 0.8})
        return EnergyProfile(
            base_power_kw=p["base"],
            peak_power_kw=p["peak"],
            idle_power_kw=p["idle"],
            power_curve_type="pulsed",  # spark discharges are pulsed
            duty_cycle=0.70,
        )


# ---------------------------------------------------------------------------
# Dummy machine
# ---------------------------------------------------------------------------

_DUMMY_MACHINE = MachineCapability(
    machine_id="_edm_dummy",
    machine_name="Dummy",
    machine_type="EDM",
    capabilities=[],
)


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class WireEDMAdapter(_BaseEDMAdapter):
    """
    Adapter for EDM_WIRE (wire electrical discharge machining).

    Characteristics:
      - Uses 0.1–0.3 mm brass wire electrode
      - Produces 2D profile cuts through full material thickness
      - Achievable tolerance: ±0.002–0.005 mm
      - Surface finish Ra: 0.4–3.2 µm (depending on skim passes)
      - No cutting force: ideal for fragile and hardened materials
      - Materials: any electrically conductive metal including hardened tool steel,
        tungsten carbide, inconel
      - Cannot produce blind features (pockets)
    """

    _variant = "wire"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.EDM_WIRE

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Wire EDM setup: program, thread wire, locate part, calibrate."""
        base = 30.0  # EDM program + part location + wire threading
        if intent.target_quantity > 1:
            # Batch: palletize or tombstone, add 15 min per additional setup
            base += min(60.0, (intent.target_quantity - 1) * 5.0)
        return base


class SinkerEDMAdapter(_BaseEDMAdapter):
    """
    Adapter for EDM_SINKER (die-sinking / ram EDM).

    Characteristics:
      - Shaped electrode (graphite or copper-tungsten) burns 3D cavity
      - Achievable tolerance: ±0.005–0.015 mm on feature location
      - Surface finish Ra: 0.4–6.3 µm
      - Electrode wear: 5–15% of workpiece removal volume
      - Required for complex mold cavities, blind keyways, gear forms
      - Slow process: best for prototype and small tooling runs (≤ 50 parts)
      - Requires custom electrode machined from graphite or CuW
    """

    _variant = "sinker"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.EDM_SINKER

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Sinker EDM setup: electrode alignment, depth setting, program."""
        return 45.0
