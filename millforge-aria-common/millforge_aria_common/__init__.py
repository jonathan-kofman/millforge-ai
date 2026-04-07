"""
millforge-aria-common — shared types between ARIA-OS and MillForge AI.

Install in both repos:
    pip install -e /path/to/millforge-aria-common

Or pin the git ref:
    pip install git+https://github.com/your-org/millforge-aria-common.git@main
"""

from .models import (
    ARIAToMillForgeJob,
    ARIAJobFeedback,
    MillForgeJobAck,
    ToleranceClass,
    OperationType,
    ARIAMaterialSpec,
    ARIASimulationResults,
)
from .validation import validate_aria_job, ValidationError

__all__ = [
    "ARIAToMillForgeJob",
    "ARIAJobFeedback",
    "MillForgeJobAck",
    "ToleranceClass",
    "OperationType",
    "ARIAMaterialSpec",
    "ARIASimulationResults",
    "validate_aria_job",
    "ValidationError",
]
