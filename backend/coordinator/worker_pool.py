"""Async worker pool with bounded concurrency and dependency resolution.

Parallelism rules:
- Independent tasks run concurrently up to max_concurrent_workers.
- Tasks with dependencies wait for all dependency task_ids to finish
  before being dispatched.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from coordinator.task_pipeline import WorkerTask, WorkerResult, PipelinePhase

logger = logging.getLogger(__name__)

WorkerExecutor = Callable[[WorkerTask], Awaitable[dict[str, Any]]]


class WorkerPool:
    def __init__(self, max_concurrent: int = 4) -> None:
        self._sem = asyncio.Semaphore(max_concurrent)
        self._results: dict[str, WorkerResult] = {}
        self._events: dict[str, asyncio.Event] = {}

    # ── Internal: run one task ─────────────────────────────────────────────

    async def _run_one(self, task: WorkerTask, executor: WorkerExecutor) -> WorkerResult:
        # Wait for dependencies first
        if task.dependencies:
            dep_events = [self._events[d] for d in task.dependencies if d in self._events]
            if dep_events:
                logger.info("Task %s waiting for deps: %s", task.task_id, task.dependencies)
                await asyncio.gather(*[e.wait() for e in dep_events])

        async with self._sem:
            start = datetime.now(timezone.utc)
            logger.info("[%s] %s › %s", task.phase.value, task.task_id, task.description[:60])
            try:
                findings = await asyncio.wait_for(executor(task), timeout=task.timeout_seconds)
                result = WorkerResult(
                    task_id=task.task_id,
                    worker_type=task.worker_type,
                    phase=task.phase,
                    success=True,
                    findings=findings,
                    duration_seconds=(datetime.now(timezone.utc) - start).total_seconds(),
                )
            except asyncio.TimeoutError:
                logger.warning("Task %s timed out after %.1fs", task.task_id, task.timeout_seconds)
                result = WorkerResult(
                    task_id=task.task_id,
                    worker_type=task.worker_type,
                    phase=task.phase,
                    success=False,
                    findings={},
                    error=f"Timed out after {task.timeout_seconds}s",
                    duration_seconds=task.timeout_seconds,
                )
            except Exception as exc:
                logger.exception("Task %s failed: %s", task.task_id, exc)
                result = WorkerResult(
                    task_id=task.task_id,
                    worker_type=task.worker_type,
                    phase=task.phase,
                    success=False,
                    findings={},
                    error=str(exc),
                    duration_seconds=(datetime.now(timezone.utc) - start).total_seconds(),
                )

        self._results[task.task_id] = result
        self._events[task.task_id].set()
        logger.info("Task %s done — success=%s (%.2fs)", task.task_id, result.success, result.duration_seconds)
        return result

    # ── Public API ─────────────────────────────────────────────────────────

    def register_tasks(self, tasks: list[WorkerTask]) -> None:
        """Pre-register completion events for dependency tracking."""
        for task in tasks:
            self._events.setdefault(task.task_id, asyncio.Event())

    async def run_parallel(
        self, tasks: list[WorkerTask], executor: WorkerExecutor
    ) -> list[WorkerResult]:
        """Run all tasks concurrently (bounded by semaphore). Dependencies respected."""
        self.register_tasks(tasks)
        return list(await asyncio.gather(*[self._run_one(t, executor) for t in tasks]))

    async def run_serial(
        self, tasks: list[WorkerTask], executor: WorkerExecutor
    ) -> list[WorkerResult]:
        """Run tasks strictly in order (for explicitly serialised phases)."""
        self.register_tasks(tasks)
        results: list[WorkerResult] = []
        for task in tasks:
            results.append(await self._run_one(task, executor))
        return results

    def get_result(self, task_id: str) -> WorkerResult | None:
        return self._results.get(task_id)

    def all_results(self) -> list[WorkerResult]:
        return list(self._results.values())

    def failed_tasks(self) -> list[WorkerResult]:
        return [r for r in self._results.values() if not r.success]
