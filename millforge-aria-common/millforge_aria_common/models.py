"""
Shared data models for the ARIA-OS ↔ MillForge bridge.

These types are the contract between autonomous CAM generation (ARIA) and
autonomous production scheduling (MillForge). Both sides validate against
these schemas — ARIA before submission, MillForge before queueing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ToleranceClass(str, Enum):
    """ISO 2768 tolerance grades used in MillForge routing decisions."""
    FINE = "fine"           # IT5-IT7 — tight tolerances, slower feeds
    MEDIUM = "medium"       # IT8-IT11 — standard machining
    COARSE = "coarse"       # IT12-IT16 — rough/semi-rough ops


class OperationType(str, Enum):
    """Manufacturing operation types that ARIA can request."""
    MILLING = "milling"
    TURNING = "turning"
    DRILLING = "drilling"
    TAPPING = "tapping"
    BORING = "boring"
    GRINDING = "grinding"
    REAMING = "reaming"
    THREAD_MILLING = "thread_milling"
    CONTOUR_MILLING = "contour_milling"
    POCKET_MILLING = "pocket_milling"
    FACE_MILLING = "face_milling"
    INSPECTION = "inspection"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

@dataclass
class ARIAMaterialSpec:
    """
    Material specification from ARIA CAM system.

    Carries more detail than MillForge's MaterialType string enum —
    the bridge normalizes to MaterialType for the scheduler.
    """
    material_name: str                  # e.g. "6061-T6 Aluminum"
    material_family: str                # "aluminum" | "steel" | "titanium" | "copper"
    hardness_hrc: Optional[float] = None
    tensile_strength_mpa: Optional[float] = None
    notes: Optional[str] = None

    def to_millforge_material(self) -> str:
        """Normalise to MillForge MaterialType.value string."""
        fam = self.material_family.lower()
        mapping = {
            "aluminum": "aluminum",
            "aluminium": "aluminum",
            "steel": "steel",
            "stainless": "steel",
            "titanium": "titanium",
            "copper": "copper",
            "brass": "copper",
        }
        return mapping.get(fam, "steel")  # steel as safe default


@dataclass
class ARIASimulationResults:
    """
    Results from ARIA's pre-submission toolpath simulation.

    MillForge stores these in cam_metadata and uses estimated_cycle_time_minutes
    to calibrate the scheduling twin's setup time predictions.
    """
    estimated_cycle_time_minutes: float
    estimated_material_removal_cm3: Optional[float] = None
    max_chip_load_mm: Optional[float] = None
    tool_wear_index: Optional[float] = None     # 0.0–1.0; 1.0 = tool change needed
    collision_detected: bool = False
    simulation_confidence: float = 1.0          # 0.0–1.0


# ---------------------------------------------------------------------------
# Primary bridge payload: ARIA → MillForge
# ---------------------------------------------------------------------------

@dataclass
class ARIAToMillForgeJob:
    """
    Job submission from ARIA-OS to MillForge.

    ARIA sends this after successful CAM generation + toolpath simulation.
    MillForge receives it at POST /api/jobs/from-aria and queues the job
    for autonomous scheduling — no human translates the geometry.
    """
    # Identity
    aria_job_id: str                            # UUID from ARIA, used for feedback loop
    part_name: str                              # human-readable part label
    geometry_hash: str                          # SHA-256 of the STL file — integrity check

    # Geometry & toolpath references (paths on a shared volume or presigned URLs)
    geometry_file: str                          # e.g. "s3://aria-jobs/abc123.stl"
    toolpath_file: str                          # e.g. "s3://aria-jobs/abc123.nc"

    # Material
    material: str                               # normalized MaterialType.value string
    material_spec: ARIAMaterialSpec

    # Process requirements
    required_operations: list[OperationType]
    tolerance_class: ToleranceClass

    # Simulation results from ARIA (used for twin calibration)
    simulation_results: ARIASimulationResults
    validation_passed: bool                     # True if ARIA's pre-flight checks passed

    # Scheduling hints (MillForge may override based on floor state)
    estimated_cycle_time_minutes: float         # from simulation_results, duplicated for convenience
    quantity: int = 1
    priority: int = 5                           # 1=urgent, 10=low; matches MillForge Order.priority
    due_date: Optional[datetime] = None

    # Metadata
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    schema_version: str = "1.0"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to JSON-safe dict for HTTP transmission."""
        return {
            "schema_version": self.schema_version,
            "aria_job_id": self.aria_job_id,
            "part_name": self.part_name,
            "geometry_hash": self.geometry_hash,
            "geometry_file": self.geometry_file,
            "toolpath_file": self.toolpath_file,
            "material": self.material,
            "material_spec": {
                "material_name": self.material_spec.material_name,
                "material_family": self.material_spec.material_family,
                "hardness_hrc": self.material_spec.hardness_hrc,
                "tensile_strength_mpa": self.material_spec.tensile_strength_mpa,
                "notes": self.material_spec.notes,
            },
            "required_operations": [op.value for op in self.required_operations],
            "tolerance_class": self.tolerance_class.value,
            "simulation_results": {
                "estimated_cycle_time_minutes": self.simulation_results.estimated_cycle_time_minutes,
                "estimated_material_removal_cm3": self.simulation_results.estimated_material_removal_cm3,
                "max_chip_load_mm": self.simulation_results.max_chip_load_mm,
                "tool_wear_index": self.simulation_results.tool_wear_index,
                "collision_detected": self.simulation_results.collision_detected,
                "simulation_confidence": self.simulation_results.simulation_confidence,
            },
            "validation_passed": self.validation_passed,
            "estimated_cycle_time_minutes": self.estimated_cycle_time_minutes,
            "quantity": self.quantity,
            "priority": self.priority,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "generated_at": self.generated_at.isoformat(),
            "extra": self.extra,
        }


# ---------------------------------------------------------------------------
# Acknowledgement: MillForge → ARIA
# ---------------------------------------------------------------------------

@dataclass
class MillForgeJobAck:
    """
    MillForge's response after queueing an ARIA job.

    ARIA stores millforge_job_id to poll status and receive feedback.
    """
    aria_job_id: str
    millforge_job_id: int               # Job.id primary key
    status: str                         # "queued" | "rejected"
    queue_position: Optional[int] = None
    estimated_start_time: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "aria_job_id": self.aria_job_id,
            "millforge_job_id": self.millforge_job_id,
            "status": self.status,
            "queue_position": self.queue_position,
            "estimated_start_time": (
                self.estimated_start_time.isoformat() if self.estimated_start_time else None
            ),
            "rejection_reason": self.rejection_reason,
            "received_at": self.received_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# Feedback: MillForge → ARIA (learning loop)
# ---------------------------------------------------------------------------

@dataclass
class ARIAJobFeedback:
    """
    Post-completion feedback from MillForge back to ARIA.

    ARIA uses actual_cycle_time_minutes vs ARIA's estimate to calibrate
    future simulation models. Quality results feed back into ARIA's
    tolerance confidence scoring.
    """
    aria_job_id: str
    millforge_job_id: int
    part_name: str

    # Completion data
    completed_at: datetime
    actual_cycle_time_minutes: Optional[float]  # None if job was cancelled

    # Deltas (positive = ARIA over-estimated)
    cycle_time_delta_minutes: Optional[float]   # estimated - actual
    cycle_time_accuracy_pct: Optional[float]    # actual / estimated * 100

    # Quality outcome from MillForge's vision inspection
    qc_passed: Optional[bool] = None
    defects_found: list[str] = field(default_factory=list)
    defect_confidence_scores: list[float] = field(default_factory=list)

    # Stage it reached before feedback was generated
    final_stage: str = "complete"               # "complete" | "qc_failed" | "cancelled"

    feedback_generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "aria_job_id": self.aria_job_id,
            "millforge_job_id": self.millforge_job_id,
            "part_name": self.part_name,
            "completed_at": self.completed_at.isoformat(),
            "actual_cycle_time_minutes": self.actual_cycle_time_minutes,
            "cycle_time_delta_minutes": self.cycle_time_delta_minutes,
            "cycle_time_accuracy_pct": self.cycle_time_accuracy_pct,
            "qc_passed": self.qc_passed,
            "defects_found": self.defects_found,
            "defect_confidence_scores": self.defect_confidence_scores,
            "final_stage": self.final_stage,
            "feedback_generated_at": self.feedback_generated_at.isoformat(),
        }
