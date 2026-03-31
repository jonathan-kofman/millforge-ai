"""
Inspection Process Adapters
==============================
Post-process quality inspection adapters. These are NOT manufacturing
operations — they consume no raw material and produce no geometry changes.
Their output is an inspection report.

Throughput is measured in parts/hour inspected. Each adapter encapsulates
the typical cycle time, required equipment, and output data format for
its inspection method.

Supported ProcessFamilies:
  - INSPECTION_CMM  — Coordinate Measuring Machine (contact probe)
  - INSPECTION_VISION — Camera + ML-based vision inspection
  - INSPECTION_XRAY — X-ray / CT volumetric NDT

All three can be chained after any manufacturing step and produce a
structured quality report as the setup sheet output.
"""

from __future__ import annotations

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
# Shared inspection constants
# ---------------------------------------------------------------------------

# Inspection throughput (parts/hour) by method and feature complexity
PARTS_PER_HOUR: Dict[str, Dict[str, float]] = {
    "cmm": {
        "simple": 8.0,      # <10 features, open tolerance (ISO 2768-m)
        "moderate": 4.0,    # 10–30 features, tight tolerance
        "complex": 1.5,     # 30+ features, GD&T full callout
    },
    "vision": {
        "simple": 120.0,    # go/no-go on flat parts
        "moderate": 60.0,   # 2D features, edge detection
        "complex": 30.0,    # 3D reconstruction, surface defects
    },
    "xray": {
        "simple": 20.0,     # basic void check
        "moderate": 8.0,    # dimensional + void
        "complex": 3.0,     # full CT reconstruction + measurement
    },
}

# Power draw (kW) by inspection type
INSPECTION_POWER_KW: Dict[str, Dict[str, float]] = {
    "cmm": {"base": 2.0, "peak": 4.0, "idle": 0.5},
    "vision": {"base": 5.0, "peak": 12.0, "idle": 1.0},    # lighting + compute
    "xray": {"base": 8.0, "peak": 20.0, "idle": 3.0},      # X-ray generator
}

# Setup time (minutes) by inspection type and first article vs production
SETUP_MINUTES: Dict[str, float] = {
    "cmm": 30.0,        # program and probe calibration
    "vision": 20.0,     # camera calibration, lighting setup, threshold tuning
    "xray": 45.0,       # geometry setup, exposure calibration, safety check
}

# Labor rate
LABOR_RATE_USD_HOUR = 70.0
ENERGY_RATE_USD_KWH = 0.12

# Equipment cost (USD/hour amortized) — high capital cost machines
EQUIPMENT_RATE_USD_HOUR: Dict[str, float] = {
    "cmm": 30.0,        # CMM amortized at ~$200k over 10 years, 2000h/yr
    "vision": 15.0,     # vision system ~$100k, more accessible
    "xray": 60.0,       # CT/X-ray ~$500k–$2M
}


# ---------------------------------------------------------------------------
# Base Inspection Adapter (internal)
# ---------------------------------------------------------------------------


class _BaseInspectionAdapter(BaseAdapter):
    """Shared logic for all inspection variants. Not registered directly."""

    _variant: str = "cmm"  # "cmm" | "vision" | "xray"

    @property
    def process_family(self) -> ProcessFamily:
        raise NotImplementedError

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        """
        Inspection adapters are broadly compatible — no material restrictions.
        Only X-ray has special requirements (conductive materials, safety shielding).
        """
        errors = super().validate_intent(intent)

        # X-ray works better on metallic parts (higher contrast)
        if self._variant == "xray":
            mat_family = intent.material.material_family.lower()
            if mat_family == "polymer" and not intent.custom_metadata.get("xray_polymer_ok"):
                errors.append(
                    "X-RAY inspection of polymer parts has limited contrast. "
                    "Consider INSPECTION_VISION or CMM for polymers. "
                    "Set custom_metadata['xray_polymer_ok'] = True to override."
                )

        # CMM cannot inspect very large parts without specialized bridge CMMs
        if self._variant == "cmm":
            l = intent.material.length_mm
            w = intent.material.width_mm
            if l is not None and l > 3000.0:
                errors.append(
                    f"Part length {l}mm exceeds typical CMM table size (3000mm). "
                    f"Consider laser tracker or portable CMM for large parts."
                )
            if w is not None and w > 2000.0:
                errors.append(
                    f"Part width {w}mm exceeds typical CMM table width (2000mm)."
                )

        return errors

    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total inspection cycle time in minutes.

        Uses parts_per_hour lookup by complexity, converts to minutes,
        adds setup time amortized over the batch.
        """
        complexity = str(intent.custom_metadata.get("inspection_complexity", "moderate"))
        pph_map = PARTS_PER_HOUR.get(self._variant, {})
        pph = pph_map.get(complexity, pph_map.get("moderate", 4.0))

        inspection_minutes = (intent.target_quantity / pph) * 60.0

        # Amortized setup time
        setup = SETUP_MINUTES.get(self._variant, 30.0)

        return round(inspection_minutes + setup, 1)

    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Inspection cost in USD.

        Components:
          1. Energy: machine power × hours
          2. Labor: hours × labor_rate
          3. Equipment amortization: hours × equipment_rate
        """
        cycle_minutes = self.estimate_cycle_time(intent, machine)
        cycle_hours = cycle_minutes / 60.0

        p = INSPECTION_POWER_KW.get(self._variant, {"base": 2.0, "idle": 0.5})
        avg_power = p["base"] * 0.70 + p["idle"] * 0.30
        energy_cost = avg_power * cycle_hours * ENERGY_RATE_USD_KWH

        labor_cost = cycle_hours * LABOR_RATE_USD_HOUR
        equipment_cost = cycle_hours * EQUIPMENT_RATE_USD_HOUR.get(self._variant, 30.0)

        return round(energy_cost + labor_cost + equipment_cost, 2)

    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        """
        Generate inspection plan / setup sheet.
        The 'setup sheet' for inspection is an inspection plan document.
        """
        sheet = super().generate_setup_sheet(intent, machine)
        complexity = str(intent.custom_metadata.get("inspection_complexity", "moderate"))
        pph_map = PARTS_PER_HOUR.get(self._variant, {})
        pph = pph_map.get(complexity, 4.0)

        sheet["process_parameters"] = {
            "method": self._variant.upper(),
            "complexity": complexity,
            "throughput_parts_per_hour": pph,
            "sample_rate": self._sample_rate(intent),
            "inspection_report_format": "ISO_2768_m_report",
            "is_destructive": self._variant == "xray" and intent.custom_metadata.get("ct_section", False),
            **self._method_specific_params(intent),
        }

        # Override quality_checks field to show output format
        sheet["inspection_output"] = {
            "report_type": f"{self._variant}_inspection_report",
            "format": "structured_json_plus_pdf",
            "traceability": "per_serial_number",
        }

        return sheet

    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        """Return the inspection tooling (probe, camera, X-ray head)."""
        tools: List[ToolingSpec] = []

        if self._variant == "cmm":
            tools.append(ToolingSpec(
                tooling_type="cmm_probe",
                tool_id="CMM-PROBE-RENISHAW-TP20",
                description="Renishaw TP20 touch-trigger probe with 3mm ruby stylus",
                parameters={
                    "stylus_diameter_mm": 3.0,
                    "stylus_length_mm": 50.0,
                    "repeatability_mm": 0.0005,
                    "qualification_sphere": "12mm_hardened",
                },
            ))
        elif self._variant == "vision":
            tools.append(ToolingSpec(
                tooling_type="vision_camera",
                tool_id="VISION-CAM-5MP-TELECENTRIC",
                description="5 MP telecentric vision camera with structured-light module",
                parameters={
                    "resolution_mp": 5.0,
                    "lens_type": "telecentric",
                    "illumination": "ring_LED_structured",
                    "field_of_view_mm": 100.0,
                    "depth_of_field_mm": 20.0,
                },
            ))
        elif self._variant == "xray":
            tools.append(ToolingSpec(
                tooling_type="xray_source",
                tool_id="XRAY-160KV-CONE-BEAM",
                description="160 kV cone-beam X-ray source for volumetric CT",
                parameters={
                    "voltage_kv": 160,
                    "focal_spot_um": 5,
                    "detector_size_mm": (200, 200),
                    "voxel_size_um": 50,
                    "scan_time_min_per_part": 15,
                },
            ))

        return tools

    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        """Inspection fixtures: rotary table, pallet, CT cradle."""
        fixture_types = {
            "cmm": ("cmm_pallet", "Precision CMM pallet for repeatable part location"),
            "vision": ("inspection_fixture", "Vision fixture for part orientation and backlit support"),
            "xray": ("ct_cradle", "CT cradle for rotational scanning"),
        }
        ft, desc = fixture_types.get(self._variant, ("inspection_table", "Generic inspection table"))
        return [
            FixtureSpec(
                fixture_type=ft,
                description=desc,
                setup_time_minutes=SETUP_MINUTES.get(self._variant, 20.0),
                parameters={"repeatability_mm": 0.010, "material": "granite" if self._variant == "cmm" else "aluminum"},
            )
        ]

    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """
        Inspection processes produce quality checks for other processes' outputs.
        This method returns the quality standard this inspection method enforces.
        """
        return [
            QualityRequirement(
                inspection_method=self._variant.replace("_", " ").upper(),
                tolerance_class="ISO_2768_m",
                standards=self._applicable_standards(),
                acceptance_criteria={
                    "inspection_method": self._variant,
                    "produces_report": True,
                },
            )
        ]

    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        """Inspection consumes no material."""
        return {}

    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        p = INSPECTION_POWER_KW.get(self._variant, {"base": 2.0, "peak": 4.0, "idle": 0.5})
        return EnergyProfile(
            base_power_kw=p["base"],
            peak_power_kw=p["peak"],
            idle_power_kw=p["idle"],
            power_curve_type="constant",
            duty_cycle=0.85,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _sample_rate(self, intent: ManufacturingIntent) -> str:
        """Return inspection sample rate as string."""
        qty = intent.target_quantity
        if self._variant == "cmm":
            if qty <= 10:
                return "100pct"
            elif qty <= 100:
                return "10pct"
            else:
                return "5pct_AQL_2.5"
        elif self._variant == "vision":
            return "100pct"  # vision is fast enough for 100%
        elif self._variant == "xray":
            if qty <= 20:
                return "100pct"
            else:
                return "10pct_AQL_1.0"
        return "10pct"

    def _applicable_standards(self) -> List[str]:
        """Return applicable inspection standards by method."""
        standards = {
            "cmm": ["ASME Y14.5", "ISO 10360", "ASME B89.4.22"],
            "vision": ["ISO 9001", "AIA-NAS-410", "ASTM E2738"],
            "xray": ["ASTM E1032", "EN 12543", "ASME BPVC V Art.22"],
        }
        return standards.get(self._variant, ["ISO 9001"])

    def _method_specific_params(self, intent: ManufacturingIntent) -> Dict[str, Any]:
        """Return method-specific process parameters for the setup sheet."""
        if self._variant == "cmm":
            return {
                "probe_path": "auto_generated",
                "datum_scheme": "3-2-1",
                "temperature_compensation": True,
                "cmm_software": "PC-DMIS",
                "feature_count_estimate": intent.custom_metadata.get("feature_count", 20),
            }
        elif self._variant == "vision":
            return {
                "algorithm": "edge_detection_plus_ml",
                "model_type": "defect_classification",
                "pass_threshold_confidence": 0.95,
                "lighting_type": "coaxial_plus_ring",
                "calibration_target": "NIST_traceable_calibration_plate",
            }
        elif self._variant == "xray":
            return {
                "mode": "2D_radiograph" if not intent.custom_metadata.get("ct") else "3D_CT",
                "voltage_kv": 160,
                "current_ua": 500,
                "exposure_ms": 1000,
                "detector_type": "flat_panel_amorphous_silicon",
                "voxel_size_um": 50,
                "reconstruction_software": "VGStudio_MAX",
            }
        return {}


# ---------------------------------------------------------------------------
# Concrete adapters
# ---------------------------------------------------------------------------


class CMMInspectionAdapter(_BaseInspectionAdapter):
    """
    Adapter for INSPECTION_CMM (Coordinate Measuring Machine).

    Characteristics:
      - Contact probe (touch-trigger or scanning) measures 3D point coordinates
      - Gold standard for dimensional inspection: ±0.001–0.005 mm typical
      - Suitable for all rigid materials (metals, hard plastics, ceramics)
      - Throughput: 1–8 parts/hour depending on feature count and tolerances
      - Produces fully traceable dimensional reports (PC-DMIS, Calypso, etc.)
      - Temperature-sensitive: requires 20±2°C environment
    """

    _variant = "cmm"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.INSPECTION_CMM

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """CMM setup: probe qualification, datum alignment, program verification."""
        feature_count = int(intent.custom_metadata.get("feature_count", 20))
        base = SETUP_MINUTES["cmm"]
        # Extra setup time for complex programs (>30 features)
        if feature_count > 30:
            base += 20.0
        return base


class VisionInspectionAdapter(_BaseInspectionAdapter):
    """
    Adapter for INSPECTION_VISION (camera and ML-based vision inspection).

    Characteristics:
      - 2D or 3D camera captures images; ML model classifies pass/fail
      - Fastest inspection method: 30–120 parts/hour
      - Best for surface defects, assembly verification, label presence
      - Limited to features visible by camera (line-of-sight)
      - Can run in-line (100% inspection on conveyor)
      - Requires training data and model calibration per part type
    """

    _variant = "vision"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.INSPECTION_VISION

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """Vision setup: camera positioning, lighting, threshold calibration."""
        base = SETUP_MINUTES["vision"]
        # First-article inspection requires model training/validation
        if intent.custom_metadata.get("first_article"):
            base += 60.0  # additional for model validation
        return base


class XRayInspectionAdapter(_BaseInspectionAdapter):
    """
    Adapter for INSPECTION_XRAY (X-ray / industrial CT inspection).

    Characteristics:
      - Volumetric NDT: detects internal voids, inclusions, cracks
      - Best for castings, welds, AM parts, honeycomb structures
      - 3D CT: full reconstruction of internal geometry, wall thickness maps
      - Slowest inspection: 3–20 parts/hour
      - Requires radiation safety shielding (interlocked cabinet or separate room)
      - Non-destructive: can re-inspect parts after rework
    """

    _variant = "xray"

    @property
    def process_family(self) -> ProcessFamily:
        return ProcessFamily.INSPECTION_XRAY

    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        errors = super().validate_intent(intent)

        # Parts must be within the CT field of view
        max_dim = max(
            intent.material.length_mm or 0.0,
            intent.material.width_mm or 0.0,
        )
        if max_dim > 500.0:
            errors.append(
                f"Part size ({max_dim}mm) exceeds typical micro-CT field of view (500mm). "
                f"Use a large-format industrial CT or radiograph panels instead of micro-CT."
            )

        return errors

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """X-ray setup: geometry positioning, exposure calibration, safety checks."""
        return SETUP_MINUTES["xray"]
