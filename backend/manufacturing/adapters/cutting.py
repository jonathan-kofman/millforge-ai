"""
Cutting Process Adapters
==========================
Covers laser cutting, plasma cutting, and waterjet cutting.

All three are 2D profile cutting operations from sheet/plate stock.
Throughput is measured in mm/min cutting speed on a given material thickness.
Setup involves nesting parts on a sheet, defining kerf, and setting up the
cutting table or fixture.

Key domain model differences:
  - LaserCutting:  tight kerf (0.1–0.3 mm), gas-assist, excellent edge quality,
                   cannot cut highly reflective metals (copper, brass)
  - PlasmaCutting: wider kerf (1–3 mm), lower precision, thicker plate capability,
                   produces HAZ and dross that requires post-process cleanup
  - WaterjetCutting: abrasive-based (garnet), no HAZ, slowest, highest material
                     flexibility (metals, composites, glass, stone)

Supported ProcessFamilies:
  - CUTTING_LASER
  - CUTTING_PLASMA
  - CUTTING_WATERJET
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
# Shared cutting constants
# ---------------------------------------------------------------------------

# Cutting speed (mm/min) by process and material thickness band
# Keyed by (process_variant, material) — falls back to "default"
CUTTING_SPEED_MM_MIN: Dict[str, Dict[str, float]] = {
    "laser": {
        "steel": 3000.0,           # 3mm mild steel, 2 kW fiber
        "aluminum": 6000.0,        # aluminum cuts faster at same power
        "stainless_steel": 2000.0,
        "titanium": 1500.0,
        "copper": 0.0,             # laser cannot cut copper effectively
        "default": 2500.0,
    },
    "plasma": {
        "steel": 4000.0,           # plasma is fast on mild steel
        "aluminum": 3500.0,
        "stainless_steel": 2500.0,
        "titanium": 2000.0,
        "default": 3000.0,
    },
    "waterjet": {
        "steel": 200.0,            # waterjet is slow but universal
        "aluminum": 400.0,
        "stainless_steel": 150.0,
        "titanium": 100.0,
        "copper": 300.0,
        "composite": 500.0,
        "default": 250.0,
    },
}

# Kerf width (mm) by cutting process
KERF_MM: Dict[str, float] = {
    "laser": 0.2,
    "plasma": 2.0,
    "waterjet": 1.0,
}

# Nesting efficiency (fraction of sheet used) — accounting for kerf and layout
NESTING_EFFICIENCY: Dict[str, float] = {
    "laser": 0.78,
    "plasma": 0.72,
    "waterjet": 0.75,
}

# Power draw (kW) by process variant
CUTTING_POWER_KW: Dict[str, Dict[str, float]] = {
    "laser": {"base": 4.0, "peak": 8.0, "idle": 0.8},      # fiber laser + chiller
    "plasma": {"base": 15.0, "peak": 30.0, "idle": 2.0},   # plasma power supply
    "waterjet": {"base": 35.0, "peak": 55.0, "idle": 5.0}, # high-pressure pump
}

# Assist gas consumption (m³/hour) — laser only
ASSIST_GAS_M3_PER_HOUR: Dict[str, float] = {
    "nitrogen": 2.0,   # for stainless / aluminum (no oxide edge)
    "oxygen": 1.5,     # for mild steel (exothermic cut, faster)
    "air": 3.0,        # low-cost option, lower quality edge
}

# Abrasive consumption (kg/hour) — waterjet only
ABRASIVE_KG_PER_HOUR = 0.35  # garnet #80 mesh

# Labor rate ($/hour)
LABOR_RATE_USD_HOUR = 65.0
ENERGY_RATE_USD_KWH = 0.12

# Gas cost ($/m³)
GAS_COST_USD_M3 = {
    "nitrogen": 0.60,
    "oxygen": 0.30,
    "air": 0.02,
}

# Abrasive cost ($/kg)
ABRASIVE_COST_USD_KG = 0.55  # garnet


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _thickness(intent: ManufacturingIntent) -> float:
    """Return material thickness in mm, defaulting to 6mm if unknown."""
    return intent.material.thickness_mm or 6.0


def _cut_length(intent: ManufacturingIntent) -> float:
    """
    Estimate total cut path length in mm.
    Reads 'cut_length_mm' from custom_metadata or derives from geometry.
    """
    if "cut_length_mm" in intent.custom_metadata:
        return float(intent.custom_metadata["cut_length_mm"]) * intent.target_quantity

    # Heuristic: perimeter of a rectangular part
    w = intent.material.width_mm or 200.0
    l = intent.material.length_mm or 300.0
    perimeter = 2 * (w + l)
    # Add interior features (slots, holes) — add 50% for typical part
    internal_features = perimeter * 0.5
    return (perimeter + internal_features) * intent.target_quantity


# ---------------------------------------------------------------------------
# Base Cutting Adapter (internal)
# ---------------------------------------------------------------------------


class _BaseCuttingAdapter(BaseAdapter):
    """Shared logic for all 2D cutting variants. Not registered directly."""

    _variant: str = "laser"  # "laser" | "plasma" | "waterjet"

    @property
    def process_family(self) -> ProcessFamily:
        raise NotImplementedError

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat = intent.material
        mat_family = mat.material_family.lower()

        # All cutting processes require sheet or plate stock
        if mat.form and mat.form.lower() not in {"sheet", "plate", "strip", "blank"}:
            errors.append(
                f"{self.process_family.value} requires sheet or plate stock. "
                f"Got form: '{mat.form}'. "
                "Set material.form to 'sheet' or 'plate'."
            )

        # Laser cannot cut highly reflective metals
        if self._variant == "laser":
            _reflective = {"copper", "brass", "gold", "silver", "bronze"}
            if mat.normalized_name in _reflective:
                errors.append(
                    f"CUTTING_LASER cannot effectively cut highly reflective material "
                    f"'{mat.normalized_name}'. Use CUTTING_WATERJET or CUTTING_PLASMA."
                )

        # Waterjet cannot cut materials that react with water
        if self._variant == "waterjet":
            _water_reactive = {"magnesium", "sodium", "potassium", "lithium"}
            if mat.normalized_name in _water_reactive:
                errors.append(
                    f"CUTTING_WATERJET cannot cut water-reactive material "
                    f"'{mat.normalized_name}'."
                )

        # Plasma has thickness limits (min 1mm, practical max ~80mm)
        t = _thickness(intent)
        if self._variant == "plasma":
            if t < 1.0:
                errors.append(
                    f"Thickness {t}mm is below practical plasma cutting minimum (1mm)."
                )
            if t > 80.0:
                errors.append(
                    f"Thickness {t}mm may exceed plasma cutting capacity for this process. "
                    f"Consider oxy-fuel cutting for thicker plate."
                )

        # Laser max thickness practical limit ~25mm for most CO2/fiber lasers
        if self._variant == "laser" and t > 25.0:
            errors.append(
                f"Thickness {t}mm may exceed laser cutting capability (typically ≤25mm). "
                f"Consider CUTTING_PLASMA or CUTTING_WATERJET for thick plate."
            )

        return errors

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total cutting cycle time in minutes.

        Model:
            cut_time = total_cut_length_mm / cutting_speed_mm_min
            + pierce_time per part
            + repositioning time
        """
        mat = intent.material.normalized_name
        speed_map = CUTTING_SPEED_MM_MIN.get(self._variant, {})
        speed = speed_map.get(mat, speed_map.get("default", 2500.0))

        if speed <= 0:
            # Process cannot cut this material (e.g., laser on copper)
            return 9999.0

        total_cut_mm = _cut_length(intent)
        cut_time_min = total_cut_mm / speed

        # Pierce time: laser/plasma ~5 sec per pierce, waterjet ~30 sec
        pierce_secs = {"laser": 5.0, "plasma": 5.0, "waterjet": 30.0}.get(self._variant, 10.0)
        # Estimate ~4 pierces per part (for interior features)
        pierce_time_min = (4 * intent.target_quantity * pierce_secs) / 60.0

        # Sheet repositioning between nested parts
        reposition_min = intent.target_quantity * 0.5

        return round(cut_time_min + pierce_time_min + reposition_min, 1)

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate cutting cost in USD.

        Components:
          1. Energy: power × cycle_hours × rate
          2. Labor: cycle_hours × labor_rate
          3. Consumables: gas (laser) or abrasive (waterjet)
          4. Tooling amortization (nozzles, electrodes, cutting heads)
        """
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        if cycle_minutes >= 9999.0:
            return 0.0
        cycle_hours = cycle_minutes / 60.0

        power = CUTTING_POWER_KW.get(self._variant, {"base": 10.0, "idle": 2.0})
        avg_power = power["base"] * 0.75 + power["idle"] * 0.25
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH

        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR

        # Consumables
        consumables = self.get_consumables(intent)
        cons_cost = 0.0

        if self._variant == "laser":
            gas_m3 = consumables.get("assist_gas_nitrogen_m3", 0.0)
            cons_cost = gas_m3 * GAS_COST_USD_M3.get("nitrogen", 0.60)
        elif self._variant == "waterjet":
            abrasive_kg = consumables.get("abrasive_garnet_kg", 0.0)
            cons_cost = abrasive_kg * ABRASIVE_COST_USD_KG

        # Tooling amortization (nozzles, electrodes, lenses)
        tooling_amort = {
            "laser": cycle_hours * 3.50,    # focusing lens + nozzle wear ~$3.50/hr
            "plasma": cycle_hours * 8.00,   # electrode + nozzle set ~$8/hr
            "waterjet": cycle_hours * 5.00, # nozzle wear + mixing tube ~$5/hr
        }.get(self._variant, cycle_hours * 5.0)

        return round(energy_cost + labor_cost + cons_cost + tooling_amort, 2)

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        sheet = super().generate_setup_sheet(intent, machine)
        mat = intent.material.normalized_name
        t = _thickness(intent)
        speed_map = CUTTING_SPEED_MM_MIN.get(self._variant, {})
        speed = speed_map.get(mat, speed_map.get("default", 2500.0))
        kerf = KERF_MM.get(self._variant, 0.2)
        efficiency = NESTING_EFFICIENCY.get(self._variant, 0.75)

        sheet["process_parameters"] = {
            "variant": self._variant.upper(),
            "material": mat,
            "thickness_mm": t,
            "cutting_speed_mm_min": speed,
            "kerf_width_mm": kerf,
            "nesting_efficiency": efficiency,
            "has_haz": self._variant in {"laser", "plasma"},
            **self._process_specific_params(intent, mat, t),
        }
        return sheet

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        mat = intent.material.normalized_name
        t = _thickness(intent)

        tools: List[ToolingSpec] = []

        if self._variant == "laser":
            tools.append(ToolingSpec(
                tooling_type="laser_cutting_head",
                tool_id=f"LCH-FIBER-{int(t*10)}T",
                description=f"Fiber laser cutting head with {self._nozzle_diameter(t)}mm nozzle",
                parameters={
                    "focal_length_mm": 150,
                    "nozzle_diameter_mm": self._nozzle_diameter(t),
                    "standoff_mm": 1.5,
                    "assist_gas": self._assist_gas(mat),
                },
            ))
        elif self._variant == "plasma":
            tools.append(ToolingSpec(
                tooling_type="plasma_torch",
                tool_id=f"PT-HD3070-{int(t)}T",
                description=f"Hypertherm-style plasma torch for {t}mm {mat}",
                parameters={
                    "amperage": self._plasma_amperage(t),
                    "nozzle": f"{int(t)}-{int(t + 5)}mm plate nozzle",
                    "electrode": "hafnium",
                    "swirl_gas": "air",
                },
            ))
        elif self._variant == "waterjet":
            tools.append(ToolingSpec(
                tooling_type="waterjet_cutting_head",
                tool_id="WJ-HEAD-ABRASIVE-50K",
                description="50,000 PSI abrasive waterjet cutting head",
                parameters={
                    "water_pressure_psi": 50_000,
                    "orifice_diameter_mm": 0.35,
                    "mixing_tube_diameter_mm": 1.02,
                    "abrasive": "garnet_80_mesh",
                    "abrasive_flow_g_min": 350,
                },
            ))

        return tools

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        """Cutting fixtures: slat table (laser/plasma) or grated table (waterjet)."""
        fixture_type = {
            "laser": "slat_table",
            "plasma": "slat_table",
            "waterjet": "grated_table",
        }.get(self._variant, "slat_table")

        return [
            FixtureSpec(
                fixture_type=fixture_type,
                description=f"{fixture_type.replace('_', ' ').title()} for 2D {self._variant} cutting",
                setup_time_minutes=10.0,
                parameters={
                    "sheet_support_size_mm": (1500, 3000),
                    "clamps": 4,
                    "requires_water_drain": self._variant == "waterjet",
                },
            )
        ]

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """Quality checks for cut parts: dimensional, edge quality, HAZ check."""
        checks = [
            QualityRequirement(
                inspection_method="dimensional_gauge",
                tolerance_class="ISO_2768_m",
                standards=["ISO 9013", "ASME Y14.5"],
                acceptance_criteria={
                    "kerf_consistency_mm": KERF_MM.get(self._variant, 0.5),
                    "squareness_deg_max": 2.0 if self._variant == "plasma" else 0.5,
                    "edge_roughness_ra_um": self._edge_ra(),
                },
            )
        ]

        # HAZ inspection for laser and plasma
        if self._variant in {"laser", "plasma"}:
            checks.append(
                QualityRequirement(
                    inspection_method="visual_inspection",
                    tolerance_class="ISO_2768_m",
                    standards=["ISO 9013"],
                    acceptance_criteria={
                        "haz_depth_max_mm": 0.5 if self._variant == "laser" else 2.0,
                        "dross_acceptable": self._variant == "laser",
                        "discoloration_acceptable": True,
                    },
                )
            )

        return checks

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        """Return consumables: gas (laser), or abrasive (waterjet)."""
        cycle_hours = self.estimate_cycle_time(intent, _DUMMY_MACHINE) / 60.0

        consumables: Dict[str, float] = {}

        if self._variant == "laser":
            gas_type = self._assist_gas(intent.material.normalized_name)
            gas_m3 = ASSIST_GAS_M3_PER_HOUR.get(gas_type, 2.0) * cycle_hours
            consumables[f"assist_gas_{gas_type}_m3"] = round(gas_m3, 3)
        elif self._variant == "plasma":
            # Plasma uses consumable electrodes + nozzles (cost accounted in tooling)
            consumables["plasma_electrode_fraction"] = round(
                min(1.0, cycle_hours / 4.0), 3  # electrode life ~4h per unit
            )
        elif self._variant == "waterjet":
            abrasive_kg = ABRASIVE_KG_PER_HOUR * cycle_hours
            consumables["abrasive_garnet_kg"] = round(abrasive_kg, 3)
            # Water consumption
            water_liters = 8.0 * cycle_hours  # ~8 L/min at 50k PSI
            consumables["water_liters"] = round(water_liters, 1)

        return consumables

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        p = CUTTING_POWER_KW.get(self._variant, {"base": 10.0, "peak": 20.0, "idle": 2.0})
        return EnergyProfile(
            base_power_kw=p["base"],
            peak_power_kw=p["peak"],
            idle_power_kw=p["idle"],
            power_curve_type="variable",
            duty_cycle=0.80,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _nozzle_diameter(self, thickness_mm: float) -> float:
        """Select laser nozzle diameter based on material thickness."""
        if thickness_mm <= 3.0:
            return 1.0
        elif thickness_mm <= 8.0:
            return 1.5
        elif thickness_mm <= 16.0:
            return 2.0
        return 2.5

    def _plasma_amperage(self, thickness_mm: float) -> int:
        """Select plasma amperage based on thickness."""
        if thickness_mm <= 6.0:
            return 45
        elif thickness_mm <= 12.0:
            return 65
        elif thickness_mm <= 25.0:
            return 100
        return 200

    def _assist_gas(self, mat: str) -> str:
        """Choose laser assist gas by material."""
        if "stainless" in mat or "aluminum" in mat or "titanium" in mat:
            return "nitrogen"  # no oxide edge
        return "oxygen"  # exothermic, faster for mild steel

    def _edge_ra(self) -> float:
        """Return expected cut edge roughness Ra (µm)."""
        return {"laser": 3.2, "plasma": 12.5, "waterjet": 6.3}.get(self._variant, 6.3)

    def _process_specific_params(
        self, intent: ManufacturingIntent, mat: str, t: float
    ) -> Dict[str, Any]:
        """Return process-specific parameters for the setup sheet."""
        if self._variant == "laser":
            return {
                "assist_gas": self._assist_gas(mat),
                "assist_gas_bar": 10 if self._assist_gas(mat) == "oxygen" else 16,
                "focus_offset_mm": 0.0,
                "laser_power_pct": min(100, max(60, int(t * 5))),
            }
        elif self._variant == "plasma":
            return {
                "amperage": self._plasma_amperage(t),
                "arc_voltage_v": 120,
                "cut_height_mm": 3.8,
                "initial_pierce_height_mm": 6.0,
                "pierce_delay_ms": max(200, int(t * 50)),
            }
        else:  # waterjet
            return {
                "water_pressure_psi": 50_000,
                "abrasive_flow_g_min": 350,
                "standoff_mm": 4.0,
                "taper_compensation_deg": 0.5,
                "cut_quality": intent.custom_metadata.get("cut_quality", "Q3"),
            }


# ---------------------------------------------------------------------------
# Dummy machine for standalone consumables estimation
# ---------------------------------------------------------------------------

_DUMMY_MACHINE = MachineCapability(
    machine_id="_cutting_dummy",
    machine_name="Dummy",
    machine_type="CUTTER",
    capabilities=[],
)


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class LaserCuttingAdapter(_BaseCuttingAdapter):
    """
    Adapter for CUTTING_LASER (CO2 or fiber laser cutting).

    Characteristics:
      - Kerf width: 0.1–0.3 mm (very tight)
      - Gas assist: N2 for stainless/aluminum, O2 for mild steel
      - HAZ: minimal (0.05–0.5 mm heat-affected zone)
      - Max thickness: ~25 mm (material-dependent)
      - Cannot cut highly reflective metals (copper, brass)
      - Nesting efficiency: ~78%
    """

    _variant = "laser"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.CUTTING_LASER

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Laser setup: nesting program + gas purge + focus calibration."""
        base = 20.0  # nesting program + focus calibration
        if intent.target_quantity > 100:
            base += 10.0  # multi-sheet setup
        return base


class PlasmaCuttingAdapter(_BaseCuttingAdapter):
    """
    Adapter for CUTTING_PLASMA (high-definition plasma arc cutting).

    Characteristics:
      - Kerf width: 1–3 mm (wider than laser)
      - Works on conductive metals only
      - HAZ: significant (1–3 mm), dross requires grinding
      - Excellent for thick plate (up to 80 mm)
      - Lower capital cost than laser; lower precision
      - Nesting efficiency: ~72%
    """

    _variant = "plasma"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.CUTTING_PLASMA

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat_family = intent.material.material_family.lower()

        # Plasma requires electrically conductive materials
        if mat_family == "polymer":
            errors.append(
                "CUTTING_PLASMA requires electrically conductive materials. "
                "Polymers cannot be plasma cut."
            )
        if mat_family == "composite":
            errors.append(
                "CUTTING_PLASMA is not suitable for composite materials due to "
                "delamination risk from the HAZ."
            )

        return errors

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        checks = super().get_quality_checks(intent)
        # Plasma always requires dross removal check
        checks.append(
            QualityRequirement(
                inspection_method="visual_inspection",
                tolerance_class="ISO_2768_c",
                standards=["ISO 9013"],
                acceptance_criteria={
                    "dross_height_max_mm": 1.5,
                    "dross_removable": True,
                    "secondary_grinding_required": True,
                },
            )
        )
        return checks

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Plasma setup: electrode/nozzle change + height calibration + nesting."""
        return 25.0


class WaterjetCuttingAdapter(_BaseCuttingAdapter):
    """
    Adapter for CUTTING_WATERJET (abrasive waterjet cutting).

    Characteristics:
      - Abrasive: garnet #80 mesh at 50,000 PSI
      - No HAZ: cold process, no thermal effects
      - Cuts any material: metals, composites, glass, stone, rubber, foam
      - Kerf width: 0.8–1.2 mm
      - Slowest of the three cutting methods
      - No secondary finishing needed for edge quality (smooth cut)
      - Nesting efficiency: ~75%
    """

    _variant = "waterjet"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.CUTTING_WATERJET

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)
        mat = intent.material

        # Waterjet can handle very thick materials, but very thin (<0.5mm) risks vibration
        t = _thickness(intent)
        if t < 0.5:
            errors.append(
                f"Thickness {t}mm may cause vibration issues during waterjet cutting. "
                f"Minimum recommended thickness is 0.5mm. Use fixturing or support tabs."
            )

        return errors

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """Waterjet quality: no HAZ, smooth edge, taper check."""
        return [
            QualityRequirement(
                inspection_method="dimensional_gauge",
                tolerance_class="ISO_2768_m",
                standards=["ISO 9013"],
                acceptance_criteria={
                    "edge_taper_deg_max": 1.0,
                    "surface_roughness_ra_um": 6.3,
                    "no_haz": True,
                    "edge_condition": "smooth_no_grinding_required",
                },
            )
        ]

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Waterjet setup: nesting program + pressure ramp-up + calibration."""
        return 30.0
