"""
Manufacturing Ontology — Core Schema and Type System
=====================================================
Defines the universal vocabulary for all manufacturing operations in MillForge AI.
Built on Pydantic v2 for schema validation, serialization, and JSON schema generation.

This module is the single source of truth for:
  - Process taxonomy (ProcessFamily + ProcessCategory)
  - Material, tooling, fixture, and quality specifications
  - Energy profiles and process constraints
  - Process step definitions, manufacturing intents, and process plans

Design goals:
  - Zero FastAPI dependency — usable in agents, CLI tools, Celery tasks, tests
  - Forward-compatible: every model has Dict[str, Any] escape hatches
  - Pydantic v2 model_config for strict validation where it matters
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
# Process Taxonomy
# ---------------------------------------------------------------------------


class ProcessFamily(str, Enum):
    """
    Enumeration of all discrete manufacturing process families supported
    by the MillForge ontology. Each value represents a distinct process
    with its own physics, tooling, and quality paradigm.
    """
    # CNC Machining
    CNC_MILLING = "CNC_MILLING"
    CNC_TURNING = "CNC_TURNING"
    CNC_DRILLING = "CNC_DRILLING"

    # Welding
    WELDING_ARC = "WELDING_ARC"
    WELDING_LASER = "WELDING_LASER"
    WELDING_EBW = "WELDING_EBW"                     # Electron Beam Welding
    WELDING_FRICTION_STIR = "WELDING_FRICTION_STIR"

    # Cutting
    CUTTING_LASER = "CUTTING_LASER"
    CUTTING_PLASMA = "CUTTING_PLASMA"
    CUTTING_WATERJET = "CUTTING_WATERJET"
    CUTTING_SHEAR = "CUTTING_SHEAR"

    # Forming
    BENDING_PRESS_BRAKE = "BENDING_PRESS_BRAKE"
    BENDING_ROLL = "BENDING_ROLL"
    STAMPING = "STAMPING"

    # Casting & Molding
    DIE_CASTING = "DIE_CASTING"
    DIE_FORGING = "DIE_FORGING"

    # EDM
    EDM_WIRE = "EDM_WIRE"
    EDM_SINKER = "EDM_SINKER"

    # Injection / Blow Molding
    INJECTION_MOLDING = "INJECTION_MOLDING"
    BLOW_MOLDING = "BLOW_MOLDING"

    # Inspection
    INSPECTION_CMM = "INSPECTION_CMM"
    INSPECTION_VISION = "INSPECTION_VISION"
    INSPECTION_XRAY = "INSPECTION_XRAY"

    # Robotics
    ROBOTICS_PICK_PLACE = "ROBOTICS_PICK_PLACE"
    ROBOTICS_MATERIAL_HANDLING = "ROBOTICS_MATERIAL_HANDLING"

    # Additive Manufacturing
    ADDITIVE_FDM = "ADDITIVE_FDM"                   # Fused Deposition Modeling
    ADDITIVE_SLS = "ADDITIVE_SLS"                   # Selective Laser Sintering
    ADDITIVE_DMLS = "ADDITIVE_DMLS"                 # Direct Metal Laser Sintering
    ADDITIVE_WIRE_ARC = "ADDITIVE_WIRE_ARC"         # Wire Arc Additive Mfg (WAAM)

    # Thermal / Post-processing
    HEAT_TREATMENT = "HEAT_TREATMENT"
    SURFACE_FINISHING = "SURFACE_FINISHING"

    # Assembly
    ASSEMBLY = "ASSEMBLY"


class ProcessCategory(str, Enum):
    """
    High-level grouping of process families. Used for coarse-grained
    routing and capability queries.
    """
    SUBTRACTIVE = "SUBTRACTIVE"
    ADDITIVE = "ADDITIVE"
    JOINING = "JOINING"
    FORMING = "FORMING"
    CASTING_MOLDING = "CASTING_MOLDING"
    INSPECTION = "INSPECTION"
    MATERIAL_HANDLING = "MATERIAL_HANDLING"
    THERMAL = "THERMAL"
    FINISHING = "FINISHING"
    ASSEMBLY = "ASSEMBLY"

    # ---------------------------------------------------------------------------
    # Category → ProcessFamily mapping
    # ---------------------------------------------------------------------------
    _FAMILY_MAP: Dict[str, str] = {}  # populated below after class definition

    @classmethod
    def for_process(cls, family: ProcessFamily) -> "ProcessCategory":
        """Return the ProcessCategory for a given ProcessFamily."""
        mapping: Dict[ProcessFamily, "ProcessCategory"] = {
            ProcessFamily.CNC_MILLING: cls.SUBTRACTIVE,
            ProcessFamily.CNC_TURNING: cls.SUBTRACTIVE,
            ProcessFamily.CNC_DRILLING: cls.SUBTRACTIVE,
            ProcessFamily.EDM_WIRE: cls.SUBTRACTIVE,
            ProcessFamily.EDM_SINKER: cls.SUBTRACTIVE,
            ProcessFamily.CUTTING_LASER: cls.SUBTRACTIVE,
            ProcessFamily.CUTTING_PLASMA: cls.SUBTRACTIVE,
            ProcessFamily.CUTTING_WATERJET: cls.SUBTRACTIVE,
            ProcessFamily.CUTTING_SHEAR: cls.SUBTRACTIVE,
            ProcessFamily.ADDITIVE_FDM: cls.ADDITIVE,
            ProcessFamily.ADDITIVE_SLS: cls.ADDITIVE,
            ProcessFamily.ADDITIVE_DMLS: cls.ADDITIVE,
            ProcessFamily.ADDITIVE_WIRE_ARC: cls.ADDITIVE,
            ProcessFamily.WELDING_ARC: cls.JOINING,
            ProcessFamily.WELDING_LASER: cls.JOINING,
            ProcessFamily.WELDING_EBW: cls.JOINING,
            ProcessFamily.WELDING_FRICTION_STIR: cls.JOINING,
            ProcessFamily.BENDING_PRESS_BRAKE: cls.FORMING,
            ProcessFamily.BENDING_ROLL: cls.FORMING,
            ProcessFamily.STAMPING: cls.FORMING,
            ProcessFamily.DIE_CASTING: cls.CASTING_MOLDING,
            ProcessFamily.DIE_FORGING: cls.CASTING_MOLDING,
            ProcessFamily.INJECTION_MOLDING: cls.CASTING_MOLDING,
            ProcessFamily.BLOW_MOLDING: cls.CASTING_MOLDING,
            ProcessFamily.INSPECTION_CMM: cls.INSPECTION,
            ProcessFamily.INSPECTION_VISION: cls.INSPECTION,
            ProcessFamily.INSPECTION_XRAY: cls.INSPECTION,
            ProcessFamily.ROBOTICS_PICK_PLACE: cls.MATERIAL_HANDLING,
            ProcessFamily.ROBOTICS_MATERIAL_HANDLING: cls.MATERIAL_HANDLING,
            ProcessFamily.HEAT_TREATMENT: cls.THERMAL,
            ProcessFamily.SURFACE_FINISHING: cls.FINISHING,
            ProcessFamily.ASSEMBLY: cls.ASSEMBLY,
        }
        return mapping.get(family, cls.SUBTRACTIVE)


# ---------------------------------------------------------------------------
# Material Specification
# ---------------------------------------------------------------------------


class MaterialSpec(BaseModel):
    """
    Describes the raw material or stock for a manufacturing operation.

    Attributes:
        material_name:      Human-readable name (e.g. "304 Stainless Steel")
        alloy_designation:  Standard alloy code (e.g. "SS304", "Al6061-T6")
        material_family:    Broad category: "ferrous", "non_ferrous", "polymer",
                            "composite", "ceramic", "other"
        form:               Stock form: "bar_stock", "sheet", "plate", "tube",
                            "wire", "powder", "pellet", "billet", "casting", "extrusion"
        thickness_mm:       Applicable to sheet/plate/tube
        width_mm:           Applicable to sheet/plate/bar
        length_mm:          Stock length
        density_kg_m3:      Material density in kg/m³
        yield_strength_mpa: 0.2% offset yield strength
        hardness:           Hardness specification (e.g. "58 HRC", "200 HB")
        custom_properties:  Catch-all for process-specific material properties
    """
    material_name: str
    alloy_designation: Optional[str] = None
    material_family: str = "ferrous"   # ferrous | non_ferrous | polymer | composite | ceramic | other
    form: str = "bar_stock"            # bar_stock | sheet | plate | tube | wire | powder | pellet | billet
    thickness_mm: Optional[float] = None
    width_mm: Optional[float] = None
    length_mm: Optional[float] = None
    density_kg_m3: Optional[float] = None
    yield_strength_mpa: Optional[float] = None
    hardness: Optional[str] = None
    custom_properties: Dict[str, Any] = Field(default_factory=dict)

    @property
    def normalized_name(self) -> str:
        """Lowercase, stripped name for registry lookups."""
        return self.material_name.lower().strip()


# ---------------------------------------------------------------------------
# Tooling and Fixture Specifications
# ---------------------------------------------------------------------------


class ToolingSpec(BaseModel):
    """
    Generic tooling descriptor. Covers CNC cutting tools, welding torches,
    press dies, mold sets, EDM electrodes, and inspection probes.

    Attributes:
        tooling_type:   Category string (e.g. "end_mill", "mig_torch", "press_die")
        tool_id:        Optional tool inventory ID or catalog number
        description:    Human-readable description
        parameters:     Process-specific parameters (diameter, flute count, etc.)
    """
    tooling_type: str
    tool_id: Optional[str] = None
    description: str
    parameters: Dict[str, Any] = Field(default_factory=dict)


class FixtureSpec(BaseModel):
    """
    Work-holding fixture specification.

    Attributes:
        fixture_type:       e.g. "vise", "chuck", "tombstone", "weld_jig", "vacuum_table"
        description:        Human-readable description
        setup_time_minutes: Time required to set up and indicate the fixture
        parameters:         Fixture-specific parameters (dimensions, clamping force, etc.)
    """
    fixture_type: str
    description: str
    setup_time_minutes: float = 0.0
    parameters: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Quality Requirements
# ---------------------------------------------------------------------------


class QualityRequirement(BaseModel):
    """
    Defines the quality acceptance criteria for an operation or final part.

    Attributes:
        inspection_method:  e.g. "CMM", "visual", "radiographic", "ultrasonic", "dye_penetrant"
        tolerance_class:    e.g. "ISO_2768_m", "ISO_2768_f", "AS9100_D"
        critical_dimensions: List of dimension dicts: [{"feature": "bore_dia", "nominal_mm": 25.0, "tol_mm": 0.01}]
        surface_finish_ra:  Required surface roughness Ra in µm
        standards:          Applicable standards (e.g. ["ASME Y14.5", "AWS D1.1", "AS9100"])
        acceptance_criteria: Pass/fail criteria beyond dimensional (e.g. {"porosity_pct_max": 0.5})
    """
    inspection_method: str
    tolerance_class: str = "ISO_2768_m"
    critical_dimensions: List[Dict[str, Any]] = Field(default_factory=list)
    surface_finish_ra: Optional[float] = None      # µm
    standards: List[str] = Field(default_factory=list)
    acceptance_criteria: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Energy Profile
# ---------------------------------------------------------------------------


class EnergyProfile(BaseModel):
    """
    Describes the electrical energy consumption profile of a process or machine.

    Attributes:
        base_power_kw:    Steady-state operating power draw
        peak_power_kw:    Maximum instantaneous power (e.g. spindle startup, arc strike)
        idle_power_kw:    Power draw when machine is energized but not cutting
        power_curve_type: Shape of the power draw: "constant" | "pulsed" | "ramped" | "variable"
        duty_cycle:       Fraction of time at base_power (1.0 = continuous)
    """
    base_power_kw: float
    peak_power_kw: float
    idle_power_kw: float = 0.0
    power_curve_type: str = "constant"   # constant | pulsed | ramped | variable
    duty_cycle: float = Field(default=1.0, ge=0.0, le=1.0)

    @property
    def average_power_kw(self) -> float:
        """Effective average power accounting for duty cycle."""
        return self.base_power_kw * self.duty_cycle + self.idle_power_kw * (1.0 - self.duty_cycle)


# ---------------------------------------------------------------------------
# Process Constraints
# ---------------------------------------------------------------------------


class ProcessConstraints(BaseModel):
    """
    Environmental and batch constraints for a manufacturing process.

    Attributes:
        min_batch_size:       Minimum economical batch (1 for bespoke, higher for molding)
        max_batch_size:       None = unlimited
        requires_atmosphere:  "vacuum" | "inert_argon" | "inert_nitrogen" | None
        temperature_range_c:  (min_C, max_C) ambient operating temperature
        humidity_range_pct:   (min_%, max_%) relative humidity
        vibration_sensitive:  True for EDM, precision grinding, etc.
        clean_room_class:     ISO cleanroom class (e.g. 7 for Class 10000); None = shop floor
    """
    min_batch_size: int = Field(default=1, ge=1)
    max_batch_size: Optional[int] = None
    requires_atmosphere: Optional[str] = None    # vacuum | inert_argon | inert_nitrogen | None
    temperature_range_c: Optional[Tuple[float, float]] = None
    humidity_range_pct: Optional[Tuple[float, float]] = None
    vibration_sensitive: bool = False
    clean_room_class: Optional[int] = None

    @model_validator(mode="after")
    def validate_batch_sizes(self) -> "ProcessConstraints":
        if self.max_batch_size is not None and self.max_batch_size < self.min_batch_size:
            raise ValueError(
                f"max_batch_size ({self.max_batch_size}) must be >= min_batch_size ({self.min_batch_size})"
            )
        return self


# ---------------------------------------------------------------------------
# Process Step Definition
# ---------------------------------------------------------------------------


class ProcessStepDefinition(BaseModel):
    """
    A fully specified discrete manufacturing operation.

    This is the core atomic unit of a ProcessPlan. Each step maps to
    exactly one ProcessFamily and can be executed on one or more machines.

    Attributes:
        step_id:                     Unique identifier within the plan
        process_family:              Which process this step uses
        description:                 Human-readable description of the operation
        material_input:              Input material for this step
        tooling:                     Required tooling list
        fixtures:                    Required fixtures
        energy:                      Expected energy draw profile
        constraints:                 Environmental / batch constraints
        quality_requirements:        QC requirements for this step's output
        estimated_cycle_time_minutes: Pure machining/process time (excludes setup)
        setup_time_minutes:          Fixture and tooling changeover time
        parameters:                  Process-specific parameters (feeds, speeds, temps, etc.)
    """
    step_id: str
    process_family: ProcessFamily
    description: str
    material_input: MaterialSpec
    tooling: List[ToolingSpec] = Field(default_factory=list)
    fixtures: List[FixtureSpec] = Field(default_factory=list)
    energy: EnergyProfile
    constraints: ProcessConstraints = Field(default_factory=ProcessConstraints)
    quality_requirements: List[QualityRequirement] = Field(default_factory=list)
    estimated_cycle_time_minutes: float = Field(ge=0.0)
    setup_time_minutes: float = Field(ge=0.0)
    parameters: Dict[str, Any] = Field(default_factory=dict)

    @property
    def total_time_minutes(self) -> float:
        """Sum of setup and cycle time."""
        return self.setup_time_minutes + self.estimated_cycle_time_minutes

    @property
    def category(self) -> ProcessCategory:
        """Derived category for this step."""
        return ProcessCategory.for_process(self.process_family)


# ---------------------------------------------------------------------------
# Manufacturing Intent
# ---------------------------------------------------------------------------


class ManufacturingIntent(BaseModel):
    """
    Captures the desired manufacturing outcome for a part or assembly.
    This is the customer-facing specification; the routing engine and
    process planner transform it into a ProcessPlan.

    Attributes:
        part_id:              Unique identifier (order ID, drawing number, etc.)
        part_name:            Human-readable part name
        description:          Engineering description / scope of work
        target_quantity:      Number of finished parts required
        material:             Stock material specification
        geometry_reference:   Optional path or URL to the CAD file (STL, STEP, etc.)
        required_processes:   Processes that MUST be used (hard constraint)
        preferred_processes:  Processes preferred if capability is available
        forbidden_processes:  Processes explicitly disallowed
        quality_requirements: Part-level quality requirements
        due_date:             Required completion timestamp
        priority:             1 (highest urgency) — 10 (lowest); default 5
        cost_target_usd:      Budget ceiling; None = no constraint
        custom_metadata:      Catch-all for ERP integration fields, customer data, etc.
    """
    part_id: str
    part_name: str
    description: str = ""
    target_quantity: int = Field(ge=1)
    material: MaterialSpec
    geometry_reference: Optional[str] = None
    required_processes: Optional[List[ProcessFamily]] = None
    preferred_processes: Optional[List[ProcessFamily]] = None
    forbidden_processes: Optional[List[ProcessFamily]] = None
    quality_requirements: List[QualityRequirement] = Field(default_factory=list)
    due_date: Optional[datetime] = None
    priority: int = Field(default=5, ge=1, le=10)
    cost_target_usd: Optional[float] = None
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_process_consistency(self) -> "ManufacturingIntent":
        """Ensure required and forbidden lists do not overlap."""
        if self.required_processes and self.forbidden_processes:
            overlap = set(self.required_processes) & set(self.forbidden_processes)
            if overlap:
                families = ", ".join(p.value for p in overlap)
                raise ValueError(
                    f"Processes appear in both required and forbidden lists: {families}"
                )
        return self


# ---------------------------------------------------------------------------
# Process Plan
# ---------------------------------------------------------------------------


class ProcessPlan(BaseModel):
    """
    A complete, ordered sequence of ProcessStepDefinitions that fulfills
    a ManufacturingIntent. Generated by the RoutingEngine or a planning agent.

    Attributes:
        plan_id:                       Unique plan identifier (UUID recommended)
        intent:                        The original manufacturing intent
        steps:                         Ordered list of process steps
        total_estimated_time_minutes:  Sum of all step setup + cycle times
        total_estimated_cost_usd:      Rolled-up cost estimate; None if not yet calculated
        created_at:                    Plan generation timestamp
        notes:                         Free-text planner notes / rationale
    """
    plan_id: str
    intent: ManufacturingIntent
    steps: List[ProcessStepDefinition]
    total_estimated_time_minutes: float = Field(ge=0.0)
    total_estimated_cost_usd: Optional[float] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    notes: str = ""

    @model_validator(mode="after")
    def reconcile_total_time(self) -> "ProcessPlan":
        """
        If total_estimated_time_minutes is 0 and steps are present,
        auto-compute from the step list. Allows callers to omit the field.
        """
        if self.total_estimated_time_minutes == 0.0 and self.steps:
            self.total_estimated_time_minutes = sum(
                s.total_time_minutes for s in self.steps
            )
        return self

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def get_step(self, step_id: str) -> Optional[ProcessStepDefinition]:
        """Look up a step by its step_id."""
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None
