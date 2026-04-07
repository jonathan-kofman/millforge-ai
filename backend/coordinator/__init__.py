"""Coordinator package — four-phase multi-agent pipeline for MillForge."""
from coordinator.coordinator_agent import CoordinatorAgent, register_worker, list_worker_types
from coordinator.task_pipeline import CoordinatorPlan, PipelinePhase, WorkerResult, WorkerTask
from coordinator.scratchpad import Scratchpad
from coordinator.worker_pool import WorkerPool

__all__ = [
    "CoordinatorAgent",
    "register_worker",
    "list_worker_types",
    "CoordinatorPlan",
    "PipelinePhase",
    "WorkerResult",
    "WorkerTask",
    "Scratchpad",
    "WorkerPool",
]
