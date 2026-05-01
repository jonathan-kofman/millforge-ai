"""Closed-loop callback to ARIA-OS when MillForge needs a redo.

Until now, MillForge's QC feedback was a one-way write into
`Job.cam_metadata.aria_feedback`. ARIA had to *poll* for it via
`GET /api/bridge/feedback/{aria_job_id}`. That breaks the lights-out
story — when QC fails at 2 a.m., nothing wakes up the design side.

This module closes the loop: when MillForge observes a redo-worthy
event (QC fail with confident defect, lights-off escalation, missing
dimension, etc.), it POSTs an `aria_redo_intent` back to ARIA at
`ARIA_CALLBACK_URL`. ARIA decides what to do with it (often: re-enter
its build orchestrator at the appropriate stage).

Design constraints:
  * **Never blocks the request that triggered it.** Caller fires it
    async and forgets. We use a daemon thread because parts of the
    backend run inside non-async paths.
  * **Never raises.** A missing/down ARIA must not break MillForge.
  * **Always observable.** Every attempt logs a `pipeline_events.jsonl`
    entry under boundary `millforge→aria`.
  * **Configurable off.** If `ARIA_CALLBACK_URL` is unset, the function
    is a no-op (returns False) and the caller is none the wiser.

Public surface:
    notify_redo(intent)        # fire-and-forget
    is_enabled() -> bool
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional
from urllib import error, request

from services.pipeline_events import emit as _emit_event

logger = logging.getLogger(__name__)


_ENV_URL = "ARIA_CALLBACK_URL"
_ENV_KEY = "ARIA_CALLBACK_KEY"
_TIMEOUT_S = 4.0


# ---------------------------------------------------------------------------
# Public dataclass — explicit shape ARIA receives
# ---------------------------------------------------------------------------

@dataclass
class RedoIntent:
    """Payload posted to ARIA. Mirrors a small ARIA-OS schema we control
    on both sides — extend by adding fields here AND in the ARIA receiver."""
    aria_run_id: Optional[str]              # primary linkage
    aria_job_id: Optional[str]              # secondary if no run_id
    millforge_job_id: int
    reason: str                             # human-readable cause
    severity: str = "redo"                  # redo | escalate | abort
    stage_hint: Optional[str] = None        # e.g. "fea_self_heal", "cad",
                                            # "cam_emit", "tolerance_allocate"
    qc_passed: Optional[bool] = None
    defects_found: list[str] = field(default_factory=list)
    measurement_deltas: list[dict] = field(default_factory=list)
    feedback_notes: Optional[str] = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_enabled() -> bool:
    return bool(os.getenv(_ENV_URL, "").strip())


def notify_redo(intent: RedoIntent) -> bool:
    """Fire-and-forget redo callback. Returns True if dispatched, False
    if disabled. Network success/failure is logged via pipeline_events
    but not awaited."""
    if not is_enabled():
        _emit_event(
            "millforge→aria", "redo_callback_skipped",
            job_id=str(intent.millforge_job_id),
            trace_id=intent.aria_run_id or intent.aria_job_id,
            extra={"reason": "ARIA_CALLBACK_URL not set"},
        )
        return False

    threading.Thread(
        target=_post_intent, args=(intent,), daemon=True,
        name="aria-callback").start()
    return True


# ---------------------------------------------------------------------------
# Internal: do the POST
# ---------------------------------------------------------------------------

def _post_intent(intent: RedoIntent) -> None:
    url = os.getenv(_ENV_URL, "").strip()
    if not url:
        return
    started = time.time()
    body = json.dumps(asdict(intent)).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = os.getenv(_ENV_KEY, "").strip()
    if api_key:
        headers["X-API-Key"] = api_key

    req = request.Request(url, data=body, headers=headers, method="POST")

    status_code: Optional[int] = None
    error_category: Optional[str] = None
    try:
        with request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            status_code = resp.status
            # Drain the body so the connection releases — we don't need it.
            try:
                resp.read(8192)
            except Exception:
                pass
    except error.HTTPError as exc:
        status_code = exc.code
        error_category = f"http_{exc.code}"
    except error.URLError as exc:
        error_category = f"urlerror:{type(exc.reason).__name__}"
    except TimeoutError:
        error_category = "timeout"
    except Exception as exc:                    # belt-and-suspenders
        error_category = f"{type(exc).__name__}"

    duration_ms = (time.time() - started) * 1000.0
    _emit_event(
        "millforge→aria", "redo_callback_dispatched",
        job_id=str(intent.millforge_job_id),
        trace_id=intent.aria_run_id or intent.aria_job_id,
        status_code=status_code,
        duration_ms=duration_ms,
        error_category=error_category,
        extra={
            "url": url,
            "severity": intent.severity,
            "reason": intent.reason[:200],
            "stage_hint": intent.stage_hint,
        },
    )


# ---------------------------------------------------------------------------
# Convenience builder — pull a ready-to-fire RedoIntent from a Job
# ---------------------------------------------------------------------------

def build_intent_from_qc(
    *,
    millforge_job_id: int,
    cam_metadata: Optional[dict],
    qc_passed: Optional[bool],
    defects_found: list[str],
    feedback_notes: Optional[str] = None,
    measurement_deltas: Optional[list[dict]] = None,
) -> RedoIntent:
    """Translate a QC feedback record into a RedoIntent. Picks the
    severity and stage_hint based on what the defects look like."""
    meta = cam_metadata or {}
    aria_run_id = meta.get("aria_run_id") or (
        meta.get("extra", {}) or {}).get("aria_run_id")
    aria_job_id = meta.get("aria_job_id")

    # Severity heuristic — escalate for safety/dimensional, redo otherwise
    severity = "redo"
    if defects_found:
        flat = " ".join(d.lower() for d in defects_found)
        if any(k in flat for k in ("crack", "fracture", "out_of_tolerance",
                                    "dimensional")):
            severity = "escalate"

    # Stage-hint heuristic — point ARIA at the right re-entry point
    stage_hint = None
    if qc_passed is False:
        if any("dimens" in d.lower() for d in defects_found):
            stage_hint = "tolerance_allocate"
        elif any("surface" in d.lower() or "finish" in d.lower()
                 for d in defects_found):
            stage_hint = "cam_emit"
        elif any("crack" in d.lower() or "fracture" in d.lower()
                 for d in defects_found):
            stage_hint = "fea_self_heal"
        else:
            stage_hint = "dfm_check"

    return RedoIntent(
        aria_run_id=aria_run_id,
        aria_job_id=aria_job_id,
        millforge_job_id=millforge_job_id,
        reason=(
            f"QC failed with defects: {', '.join(defects_found)}"
            if defects_found else
            (feedback_notes or "QC failed")
        ),
        severity=severity,
        stage_hint=stage_hint,
        qc_passed=qc_passed,
        defects_found=list(defects_found or []),
        measurement_deltas=list(measurement_deltas or []),
        feedback_notes=feedback_notes,
    )
