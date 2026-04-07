"""
Validation utilities shared between ARIA-OS and MillForge.

Both sides run validate_aria_job() — ARIA before sending, MillForge after
receiving. If MillForge rejects a job that ARIA thought was valid, the delta
surfaces a schema drift that needs a normalizer bump.
"""

from __future__ import annotations

import hashlib
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ARIAToMillForgeJob

_SUPPORTED_SCHEMA_VERSIONS = {"1.0"}
_VALID_MATERIALS = {"steel", "aluminum", "titanium", "copper"}
_MAX_QUANTITY = 100_000
_MAX_PRIORITY = 10
_MIN_PRIORITY = 1
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$", re.IGNORECASE)


class ValidationError(Exception):
    """One or more validation failures on an ARIAToMillForgeJob payload."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


def validate_aria_job(job: "ARIAToMillForgeJob") -> None:
    """
    Validate an ARIAToMillForgeJob.

    Raises ValidationError with a list of all errors found (not fail-fast)
    so ARIA can surface all problems in one round-trip.
    """
    errors: list[str] = []

    # Schema version
    if job.schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        errors.append(
            f"Unsupported schema_version '{job.schema_version}'. "
            f"Supported: {sorted(_SUPPORTED_SCHEMA_VERSIONS)}"
        )

    # Identity
    if not job.aria_job_id or not job.aria_job_id.strip():
        errors.append("aria_job_id must not be empty")

    if not job.part_name or not job.part_name.strip():
        errors.append("part_name must not be empty")

    if not _SHA256_RE.match(job.geometry_hash):
        errors.append(
            f"geometry_hash must be a 64-character hex SHA-256, got: '{job.geometry_hash[:16]}…'"
        )

    # Files
    if not job.geometry_file:
        errors.append("geometry_file must not be empty")
    if not job.toolpath_file:
        errors.append("toolpath_file must not be empty")

    # Material
    if job.material not in _VALID_MATERIALS:
        errors.append(
            f"material '{job.material}' is not a MillForge MaterialType. "
            f"Valid values: {sorted(_VALID_MATERIALS)}"
        )

    # material_spec consistency
    if job.material_spec:
        normalised = job.material_spec.to_millforge_material()
        if normalised != job.material:
            errors.append(
                f"material_spec.material_family '{job.material_spec.material_family}' "
                f"normalises to '{normalised}' but material field is '{job.material}'"
            )

    # Simulation results
    if job.simulation_results.collision_detected:
        errors.append(
            "simulation_results.collision_detected is True — "
            "fix toolpath before submitting"
        )
    if not (0.0 <= job.simulation_results.simulation_confidence <= 1.0):
        errors.append(
            "simulation_results.simulation_confidence must be 0.0–1.0"
        )
    if job.simulation_results.estimated_cycle_time_minutes <= 0:
        errors.append(
            "simulation_results.estimated_cycle_time_minutes must be > 0"
        )

    # Cycle time consistency
    if abs(job.estimated_cycle_time_minutes - job.simulation_results.estimated_cycle_time_minutes) > 0.01:
        errors.append(
            "estimated_cycle_time_minutes must equal "
            "simulation_results.estimated_cycle_time_minutes"
        )

    # Scheduling hints
    if job.quantity < 1 or job.quantity > _MAX_QUANTITY:
        errors.append(f"quantity must be 1–{_MAX_QUANTITY}, got {job.quantity}")

    if not (_MIN_PRIORITY <= job.priority <= _MAX_PRIORITY):
        errors.append(
            f"priority must be {_MIN_PRIORITY}–{_MAX_PRIORITY}, got {job.priority}"
        )

    # Validation gate
    if not job.validation_passed:
        errors.append(
            "validation_passed is False — ARIA pre-flight checks failed; "
            "do not submit until all checks pass"
        )

    if errors:
        raise ValidationError(errors)


def compute_geometry_hash(file_bytes: bytes) -> str:
    """SHA-256 of raw STL bytes — use to populate geometry_hash before sending."""
    return hashlib.sha256(file_bytes).hexdigest()
