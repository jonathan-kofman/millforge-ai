"""
Pipeline observability — unified JSONL event log for the
StructSight → ARIA-OS → MillForge boundary.

Usage (anywhere in the backend):
    from services.pipeline_events import emit, query_events

    emit("aria_bridge", "job_received", job_id="ARIA-123", status_code=200,
         duration_ms=142, trace_id="trace-abc")
"""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

_LOG_PATH = Path(os.getenv("PIPELINE_EVENTS_PATH", "pipeline_events.jsonl"))
_lock = threading.Lock()


def emit(
    boundary: str,
    event_type: str,
    *,
    job_id: Optional[str] = None,
    trace_id: Optional[str] = None,
    status_code: Optional[int] = None,
    duration_ms: Optional[float] = None,
    error_category: Optional[str] = None,
    project: str = "millforge",
    extra: Optional[dict] = None,
) -> None:
    """Append one event to the JSONL log. Thread-safe. Never raises."""
    event: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "project": project,
        "event_type": event_type,
        "boundary": boundary,
    }
    if job_id is not None:
        event["job_id"] = job_id
    if trace_id is not None:
        event["trace_id"] = trace_id
    if status_code is not None:
        event["status_code"] = status_code
    if duration_ms is not None:
        event["duration_ms"] = round(duration_ms, 2)
    if error_category is not None:
        event["error_category"] = error_category
    if extra:
        event["extra"] = extra

    try:
        line = json.dumps(event, default=str)
        with _lock:
            with _LOG_PATH.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
    except Exception:
        pass  # observability must never break the main path


def query_events(
    *,
    boundary: Optional[str] = None,
    event_type: Optional[str] = None,
    trace_id: Optional[str] = None,
    job_id: Optional[str] = None,
    limit: int = 200,
) -> list[dict]:
    """Read the last `limit` events, optionally filtered. Returns newest-first."""
    try:
        if not _LOG_PATH.exists():
            return []
        with _lock:
            lines = _LOG_PATH.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []

    results: list[dict] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if boundary and ev.get("boundary") != boundary:
            continue
        if event_type and ev.get("event_type") != event_type:
            continue
        if trace_id and ev.get("trace_id") != trace_id:
            continue
        if job_id and ev.get("job_id") != job_id:
            continue
        results.append(ev)
        if len(results) >= limit:
            break
    return results


class timed_emit:
    """Context manager that emits an event with duration_ms on exit.

    Usage:
        with timed_emit("aria→millforge", "job_submit", job_id="123", trace_id="t"):
            # ... do the HTTP call ...
    """

    def __init__(self, boundary: str, event_type: str, **kwargs: Any) -> None:
        self._boundary = boundary
        self._event_type = event_type
        self._kwargs = kwargs
        self._start: float = 0.0

    def __enter__(self) -> "timed_emit":
        self._start = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        duration_ms = (time.monotonic() - self._start) * 1000
        error_category: Optional[str] = None
        if exc_type is not None:
            error_category = type(exc_val).__name__
        emit(
            self._boundary,
            self._event_type,
            duration_ms=duration_ms,
            error_category=error_category,
            **self._kwargs,
        )
        return False  # do not suppress exceptions
