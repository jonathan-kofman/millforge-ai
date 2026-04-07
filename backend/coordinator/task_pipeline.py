"""Typed contracts for the four-phase coordinator pipeline."""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class PipelinePhase(str, Enum):
    RESEARCH = "RESEARCH"
    SYNTHESIS = "SYNTHESIS"
    IMPLEMENTATION = "IMPLEMENTATION"
    VERIFICATION = "VERIFICATION"


@dataclass
class WorkerTask:
    task_id: str
    phase: PipelinePhase
    worker_type: str          # e.g. "SchedulingAgent", "SupplierAgent"
    description: str
    context: dict[str, Any]   # scoped data — only what this worker needs
    dependencies: list[str]   # task_ids that must complete first
    timeout_seconds: float
    created_at: datetime

    @classmethod
    def create(
        cls,
        phase: PipelinePhase,
        worker_type: str,
        description: str,
        context: dict[str, Any],
        *,
        dependencies: list[str] | None = None,
        timeout_seconds: float = 30.0,
    ) -> "WorkerTask":
        return cls(
            task_id=str(uuid.uuid4())[:8],
            phase=phase,
            worker_type=worker_type,
            description=description,
            context=context,
            dependencies=dependencies or [],
            timeout_seconds=timeout_seconds,
            created_at=datetime.now(timezone.utc),
        )


@dataclass
class WorkerResult:
    task_id: str
    worker_type: str
    phase: PipelinePhase
    success: bool
    findings: dict[str, Any]
    error: str | None = None
    duration_seconds: float = 0.0
    scratchpad_path: str | None = None
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class CoordinatorPlan:
    plan_id: str
    original_request: str
    research_tasks: list[WorkerTask]
    implementation_tasks: list[WorkerTask]
    verification_tasks: list[WorkerTask]
    max_concurrent_workers: int = 4
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def create(cls, request: str, max_concurrent: int = 4) -> "CoordinatorPlan":
        return cls(
            plan_id=str(uuid.uuid4())[:12],
            original_request=request,
            research_tasks=[],
            implementation_tasks=[],
            verification_tasks=[],
            max_concurrent_workers=max_concurrent,
        )
