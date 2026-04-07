"""Shared scratchpad directory for inter-worker communication.

Workers write JSON findings here; the coordinator reads all findings
before Synthesis. Each file is named: {worker_id}_{ISO-timestamp}.json
"""
from __future__ import annotations
import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_BASE = Path("data/scratchpad")


class Scratchpad:
    """One scratchpad per coordinator session (session_id = plan_id)."""

    def __init__(self, session_id: str, base_dir: Path = _DEFAULT_BASE) -> None:
        self.session_id = session_id
        self.dir = base_dir / session_id
        self.dir.mkdir(parents=True, exist_ok=True)
        logger.debug("Scratchpad ready: %s", self.dir)

    # ── Write ──────────────────────────────────────────────────────────────

    def write(self, worker_id: str, phase: str, data: dict[str, Any]) -> str:
        """Persist worker findings. Returns the file path."""
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        filename = f"{worker_id}_{ts}.json"
        path = self.dir / filename
        payload = {"worker_id": worker_id, "phase": phase, "written_at": ts, **data}
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        logger.debug("Scratchpad write: %s", filename)
        return str(path)

    # ── Read ───────────────────────────────────────────────────────────────

    def read_all(self, *, worker_id: str | None = None, phase: str | None = None) -> list[dict[str, Any]]:
        """Read all findings, optionally filtered by worker or phase."""
        pattern = f"{worker_id}_*.json" if worker_id else "*.json"
        results: list[dict[str, Any]] = []
        for f in sorted(self.dir.glob(pattern)):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
                if phase is None or doc.get("phase") == phase:
                    results.append(doc)
            except Exception as exc:
                logger.warning("Scratchpad: could not read %s — %s", f.name, exc)
        return results

    def read_phase(self, phase: str) -> list[dict[str, Any]]:
        return self.read_all(phase=phase)

    def summary(self) -> dict[str, Any]:
        all_docs = self.read_all()
        by_phase: dict[str, int] = {}
        by_worker: dict[str, int] = {}
        for doc in all_docs:
            by_phase[doc.get("phase", "unknown")] = by_phase.get(doc.get("phase", "unknown"), 0) + 1
            by_worker[doc.get("worker_id", "unknown")] = by_worker.get(doc.get("worker_id", "unknown"), 0) + 1
        return {"total_entries": len(all_docs), "by_phase": by_phase, "by_worker": by_worker}

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def cleanup(self) -> None:
        """Remove the session scratchpad after pipeline completes."""
        shutil.rmtree(self.dir, ignore_errors=True)
        logger.debug("Scratchpad cleaned: %s", self.dir)
