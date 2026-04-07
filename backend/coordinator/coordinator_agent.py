"""CoordinatorAgent — orchestrates four-phase pipeline over worker agents.

The coordinator NEVER makes direct changes.
It delegates all work to workers, synthesizes their findings,
then issues detailed implementation specs.

Four phases:
  RESEARCH        — workers investigate in parallel
  SYNTHESIS       — coordinator reads ALL findings, builds a unified plan
  IMPLEMENTATION  — workers execute precise specs
  VERIFICATION    — workers validate results (tests, constraint checks)
"""
from __future__ import annotations
import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from coordinator.task_pipeline import (
    CoordinatorPlan,
    PipelinePhase,
    WorkerResult,
    WorkerTask,
)
from coordinator.scratchpad import Scratchpad
from coordinator.worker_pool import WorkerPool

logger = logging.getLogger(__name__)

# ── Built-in worker-type registry ────────────────────────────────────────────
# Maps worker_type strings → async callables that accept WorkerTask
# and return dict[str, Any] findings.
# Concrete MillForge agents register themselves here at startup.
_WORKER_REGISTRY: dict[str, Any] = {}


def register_worker(worker_type: str, executor) -> None:  # noqa: ANN001
    """Register a callable as a named worker type."""
    _WORKER_REGISTRY[worker_type] = executor
    logger.info("Registered worker type: %s", worker_type)


def list_worker_types() -> list[str]:
    return list(_WORKER_REGISTRY.keys())


# ── Built-in workers (lightweight; real agents registered separately) ─────────

async def _scheduling_research_worker(task: WorkerTask) -> dict[str, Any]:
    """Reads pending jobs and machine availability from context."""
    from agents.scheduler import Scheduler  # local import to avoid circular deps
    orders = task.context.get("orders", [])
    sched = Scheduler(orders=orders)
    schedule = sched.optimize()
    return {
        "pending_order_count": len(orders),
        "schedulable": len(schedule.scheduled_orders),
        "on_time_count": sum(1 for o in schedule.scheduled_orders if o.on_time),
        "makespan_minutes": schedule.makespan_minutes,
    }


async def _supplier_research_worker(task: WorkerTask) -> dict[str, Any]:
    """Checks supplier lead times from directory context."""
    materials = task.context.get("materials", [])
    return {
        "materials_checked": materials,
        "lead_times": {m: "2-5 business days" for m in materials},  # placeholder
        "preferred_suppliers": {},
    }


async def _energy_research_worker(task: WorkerTask) -> dict[str, Any]:
    from agents.energy_optimizer import EnergyOptimizer
    optimizer = EnergyOptimizer()
    windows = optimizer.get_negative_pricing_windows()
    return {
        "cheap_windows": len(windows.get("cheap_windows", [])),
        "data_source": windows.get("data_source", "unknown"),
    }


async def _inventory_research_worker(task: WorkerTask) -> dict[str, Any]:
    from agents.inventory_agent import InventoryAgent
    agent = InventoryAgent()
    status = agent.get_status()
    return {
        "total_materials": len(status.materials),
        "low_stock": [m for m, s in status.materials.items() if s.get("below_reorder", False)],
    }


async def _anomaly_verification_worker(task: WorkerTask) -> dict[str, Any]:
    from agents.anomaly_detector import AnomalyDetector
    orders = task.context.get("orders", [])
    detector = AnomalyDetector()
    report = detector.detect(orders)
    return {
        "anomaly_count": len(report.anomalies),
        "critical_count": sum(1 for a in report.anomalies if a.severity == "critical"),
        "held_count": len(report.held_orders),
    }


async def _noop_worker(task: WorkerTask) -> dict[str, Any]:
    """Fallback for unregistered worker types."""
    logger.warning("No executor for worker_type=%s — returning empty findings", task.worker_type)
    return {"note": f"No executor registered for {task.worker_type}"}


# Register built-in workers
register_worker("SchedulingAgent", _scheduling_research_worker)
register_worker("SupplierAgent", _supplier_research_worker)
register_worker("EnergyAgent", _energy_research_worker)
register_worker("InventoryAgent", _inventory_research_worker)
register_worker("AnomalyAgent", _anomaly_verification_worker)


# ── CoordinatorAgent ──────────────────────────────────────────────────────────

class CoordinatorAgent:
    """
    Orchestrates multi-agent pipelines.

    Usage::

        coordinator = CoordinatorAgent(max_concurrent_workers=4)
        result = await coordinator.run(request="Optimise schedule for next 48h", context={...})
    """

    def __init__(self, max_concurrent_workers: int = 4) -> None:
        self._max_concurrent = max_concurrent_workers
        logger.info(
            "CoordinatorAgent ready (max_concurrent=%d, workers=%s)",
            max_concurrent_workers,
            list_worker_types(),
        )

    # ── Public entry point ────────────────────────────────────────────────

    async def run(
        self,
        request: str,
        context: dict[str, Any] | None = None,
        *,
        cleanup_scratchpad: bool = True,
    ) -> dict[str, Any]:
        """Execute the full four-phase pipeline for the given request."""
        ctx = context or {}
        plan = CoordinatorPlan.create(request=request, max_concurrent=self._max_concurrent)
        scratchpad = Scratchpad(session_id=plan.plan_id)
        pool = WorkerPool(max_concurrent=self._max_concurrent)
        pipeline_start = datetime.now(timezone.utc)

        logger.info("=== Coordinator pipeline start [%s] ===", plan.plan_id)
        logger.info("Request: %s", request)

        try:
            # ── Phase 1: RESEARCH ────────────────────────────────────────
            research_results = await self._phase_research(plan, pool, scratchpad, ctx)

            # ── Phase 2: SYNTHESIS ───────────────────────────────────────
            synthesis = await self._phase_synthesis(plan, scratchpad)

            # ── Phase 3: IMPLEMENTATION ──────────────────────────────────
            impl_results = await self._phase_implementation(plan, pool, scratchpad, synthesis, ctx)

            # ── Phase 4: VERIFICATION ────────────────────────────────────
            verify_results = await self._phase_verification(plan, pool, scratchpad, ctx)

            elapsed = (datetime.now(timezone.utc) - pipeline_start).total_seconds()
            logger.info("=== Coordinator pipeline complete [%s] (%.2fs) ===", plan.plan_id, elapsed)

            return {
                "plan_id": plan.plan_id,
                "request": request,
                "status": "completed",
                "phases_completed": [p.value for p in PipelinePhase],
                "research_count": len(research_results),
                "implementation_count": len(impl_results),
                "verification_count": len(verify_results),
                "synthesis_summary": synthesis.get("summary", ""),
                "failed_tasks": [r.task_id for r in pool.failed_tasks()],
                "elapsed_seconds": elapsed,
                "scratchpad_summary": scratchpad.summary(),
            }

        finally:
            if cleanup_scratchpad:
                scratchpad.cleanup()

    # ── Phase implementations ─────────────────────────────────────────────

    async def _phase_research(
        self,
        plan: CoordinatorPlan,
        pool: WorkerPool,
        scratchpad: Scratchpad,
        ctx: dict[str, Any],
    ) -> list[WorkerResult]:
        logger.info("[RESEARCH] Dispatching research workers in parallel")

        # Build research tasks based on available context
        tasks: list[WorkerTask] = [
            WorkerTask.create(
                phase=PipelinePhase.RESEARCH,
                worker_type="SchedulingAgent",
                description="Read pending jobs and compute baseline schedule metrics",
                context={"orders": ctx.get("orders", [])},
            ),
        ]
        if ctx.get("check_suppliers"):
            tasks.append(WorkerTask.create(
                phase=PipelinePhase.RESEARCH,
                worker_type="SupplierAgent",
                description="Retrieve supplier lead times for required materials",
                context={"materials": ctx.get("materials", [])},
            ))
        if ctx.get("check_energy", True):
            tasks.append(WorkerTask.create(
                phase=PipelinePhase.RESEARCH,
                worker_type="EnergyAgent",
                description="Identify cheap energy windows for production scheduling",
                context={},
            ))
        if ctx.get("check_inventory", True):
            tasks.append(WorkerTask.create(
                phase=PipelinePhase.RESEARCH,
                worker_type="InventoryAgent",
                description="Check material stock levels and reorder status",
                context={},
            ))

        plan.research_tasks = tasks
        results = await pool.run_parallel(tasks, self._dispatch_worker)

        # Write all findings to scratchpad
        for result in results:
            if result.success:
                path = scratchpad.write(
                    worker_id=result.task_id,
                    phase=PipelinePhase.RESEARCH.value,
                    data={"worker_type": result.worker_type, "findings": result.findings},
                )
                result.scratchpad_path = path

        failed = [r for r in results if not r.success]
        if failed:
            logger.warning("[RESEARCH] %d/%d workers failed", len(failed), len(results))
        else:
            logger.info("[RESEARCH] All %d workers succeeded", len(results))

        return results

    async def _phase_synthesis(
        self,
        plan: CoordinatorPlan,
        scratchpad: Scratchpad,
    ) -> dict[str, Any]:
        """Coordinator reads ALL worker findings and creates a unified plan.

        The coordinator does this itself — it never delegates synthesis.
        """
        logger.info("[SYNTHESIS] Reading all research findings")
        research_findings = scratchpad.read_phase(PipelinePhase.RESEARCH.value)

        synthesis: dict[str, Any] = {
            "plan_id": plan.plan_id,
            "research_sources": len(research_findings),
            "findings_by_worker": {},
            "action_items": [],
            "constraints": [],
            "summary": "",
        }

        for doc in research_findings:
            wtype = doc.get("worker_type", "unknown")
            findings = doc.get("findings", {})
            synthesis["findings_by_worker"][wtype] = findings

            # Derive action items from findings
            if wtype == "SchedulingAgent":
                on_time = findings.get("on_time_count", 0)
                total = findings.get("schedulable", 0)
                if total > 0 and on_time / total < 0.8:
                    synthesis["action_items"].append(
                        f"On-time rate {on_time}/{total} below 80% — switch to SA algorithm"
                    )
            elif wtype == "InventoryAgent":
                low = findings.get("low_stock", [])
                if low:
                    synthesis["action_items"].append(
                        f"Low stock alert for: {', '.join(low)} — generate reorder POs"
                    )
            elif wtype == "EnergyAgent":
                windows = findings.get("cheap_windows", 0)
                if windows > 0:
                    synthesis["constraints"].append(
                        f"Schedule energy-intensive jobs in {windows} cheap grid windows"
                    )

        synthesis["summary"] = (
            f"Synthesised {len(research_findings)} research reports. "
            f"Action items: {len(synthesis['action_items'])}. "
            f"Constraints: {len(synthesis['constraints'])}."
        )
        logger.info("[SYNTHESIS] %s", synthesis["summary"])

        # Write synthesis to scratchpad
        scratchpad.write(
            worker_id="coordinator",
            phase=PipelinePhase.SYNTHESIS.value,
            data=synthesis,
        )
        return synthesis

    async def _phase_implementation(
        self,
        plan: CoordinatorPlan,
        pool: WorkerPool,
        scratchpad: Scratchpad,
        synthesis: dict[str, Any],
        ctx: dict[str, Any],
    ) -> list[WorkerResult]:
        logger.info("[IMPLEMENTATION] Dispatching implementation tasks")

        # Build implementation tasks from synthesis action items
        tasks: list[WorkerTask] = []
        for item in synthesis.get("action_items", []):
            if "SA algorithm" in item:
                tasks.append(WorkerTask.create(
                    phase=PipelinePhase.IMPLEMENTATION,
                    worker_type="SchedulingAgent",
                    description=f"Re-run schedule with SA algorithm: {item}",
                    context={"orders": ctx.get("orders", []), "algorithm": "sa"},
                    timeout_seconds=60.0,
                ))
            elif "reorder POs" in item:
                tasks.append(WorkerTask.create(
                    phase=PipelinePhase.IMPLEMENTATION,
                    worker_type="InventoryAgent",
                    description=f"Generate purchase orders: {item}",
                    context={"action": "reorder"},
                ))

        if not tasks:
            logger.info("[IMPLEMENTATION] No implementation tasks needed")
            return []

        plan.implementation_tasks = tasks
        results = await pool.run_parallel(tasks, self._dispatch_worker)

        for result in results:
            scratchpad.write(
                worker_id=result.task_id,
                phase=PipelinePhase.IMPLEMENTATION.value,
                data={"worker_type": result.worker_type, "success": result.success, "findings": result.findings},
            )

        logger.info("[IMPLEMENTATION] %d/%d tasks succeeded", sum(r.success for r in results), len(results))
        return results

    async def _phase_verification(
        self,
        plan: CoordinatorPlan,
        pool: WorkerPool,
        scratchpad: Scratchpad,
        ctx: dict[str, Any],
    ) -> list[WorkerResult]:
        logger.info("[VERIFICATION] Running constraint checks")

        tasks = [
            WorkerTask.create(
                phase=PipelinePhase.VERIFICATION,
                worker_type="AnomalyAgent",
                description="Validate final order set for anomalies and constraint violations",
                context={"orders": ctx.get("orders", [])},
            )
        ]

        plan.verification_tasks = tasks
        results = await pool.run_parallel(tasks, self._dispatch_worker)

        for result in results:
            scratchpad.write(
                worker_id=result.task_id,
                phase=PipelinePhase.VERIFICATION.value,
                data={"worker_type": result.worker_type, "passed": result.success, "findings": result.findings},
            )

        all_passed = all(r.success for r in results)
        logger.info("[VERIFICATION] All checks passed: %s", all_passed)
        return results

    # ── Dispatcher ─────────────────────────────────────────────────────────

    async def _dispatch_worker(self, task: WorkerTask) -> dict[str, Any]:
        """Route a task to its registered executor. Falls back to _noop_worker."""
        executor = _WORKER_REGISTRY.get(task.worker_type, _noop_worker)
        return await executor(task)
