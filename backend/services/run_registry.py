"""Cross-stack run registry — single source of truth for "what happened
to part X end-to-end."

Three data sources, one timeline:

  1. **aria-os filesystem** at `ARIA_OUTPUTS_PATH/runs/<run_id>/`
     - `run_manifest.json` → per-run metadata (goal, spec, artifacts,
       agent stats, pipeline_stats, mesh_stats)
     - any other files in the dir → artifacts (`part.step`, `part.stl`,
       `part.glb`, drawings, renders, FEA outputs, gcode)

  2. **MillForge DB** — `Job` row whose `cam_metadata.aria_run_id` (or
     `aria_job_id`) matches. Carries the production-side state machine.

  3. **aria_os.floor events log** at `ARIA_FLOOR_DB_PATH` — every floor
     event carrying the run_id in payload, OR tied to a job_id we know
     from #2.

  4. **MillForge pipeline events** — `pipeline_events.jsonl` entries
     with matching trace_id/job_id.

Public surface:

    list_runs(limit=50)              -> list of run summaries
    get_run(run_id)                  -> {manifest, artifacts, job, events}
    timeline(run_id)                 -> ordered list of timeline entries

If `ARIA_OUTPUTS_PATH` isn't set we fall back to a sensible default
relative to the workspace layout. If neither file system nor floor DB
are configured the registry still works — it just returns the
MillForge-side fragments.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from db_models import Job
from services import floor_state_reader as floor

logger = logging.getLogger(__name__)


# Reasonable defaults so dev environments don't need extra config.
_DEFAULT_OUTPUTS = Path(__file__).resolve().parents[3] / "aria-os" / "outputs"

# Manifest filename inside each run dir (set by aria_os/run_manifest.py)
_MANIFEST_FILENAME = "run_manifest.json"


def _outputs_path() -> Optional[Path]:
    p = os.getenv("ARIA_OUTPUTS_PATH", "").strip()
    if p:
        return Path(p)
    if _DEFAULT_OUTPUTS.is_dir():
        return _DEFAULT_OUTPUTS
    return None


def _runs_dir() -> Optional[Path]:
    base = _outputs_path()
    if base is None:
        return None
    candidate = base / "runs"
    return candidate if candidate.is_dir() else None


# ---------------------------------------------------------------------------
# Filesystem side
# ---------------------------------------------------------------------------

def _read_manifest(run_dir: Path) -> Optional[dict]:
    f = run_dir / _MANIFEST_FILENAME
    if not f.is_file():
        return None
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("manifest read failed at %s: %s", f, exc)
        return None


def _list_artifacts(run_dir: Path) -> list[dict]:
    """List every file in the run dir (skip the manifest itself).
    Categorize by extension so the UI knows which viewer to use."""
    out: list[dict] = []
    try:
        for p in sorted(run_dir.iterdir()):
            if not p.is_file() or p.name == _MANIFEST_FILENAME:
                continue
            ext = p.suffix.lower()
            kind = _ARTIFACT_KINDS.get(ext, "other")
            try:
                size = p.stat().st_size
            except OSError:
                size = None
            out.append({
                "name": p.name,
                "path": str(p),
                "ext": ext,
                "kind": kind,
                "size_bytes": size,
            })
    except OSError as exc:
        logger.warning("artifact scan failed at %s: %s", run_dir, exc)
    return out


_ARTIFACT_KINDS: dict[str, str] = {
    ".step": "mcad", ".stp": "mcad",
    ".stl":  "mesh", ".glb":  "mesh", ".gltf": "mesh",
    ".dwg":  "drawing", ".dxf":  "drawing", ".pdf":  "drawing",
    ".sldprt": "mcad_native", ".sldasm": "mcad_native",
    ".kicad_pcb": "ecad", ".kicad_sch": "ecad",
    ".gerber": "ecad_fab", ".gbr": "ecad_fab", ".drl": "ecad_fab",
    ".nc": "gcode", ".gcode": "gcode", ".tap": "gcode", ".cnc": "gcode",
    ".vtu": "fea", ".vtk": "fea", ".frd": "fea",
    ".png": "render", ".jpg": "render", ".jpeg": "render",
    ".webp": "render", ".gif": "render",
    ".json": "metadata", ".md": "doc", ".txt": "doc", ".log": "doc",
}


# ---------------------------------------------------------------------------
# Reading run lists
# ---------------------------------------------------------------------------

def list_runs(*, limit: int = 50) -> list[dict]:
    """Walk `outputs/runs/` newest-first, return brief summaries.
    Each summary keeps the run_dir small so the UI can build a list view
    without parsing every manifest field."""
    rd = _runs_dir()
    if rd is None:
        return []
    try:
        entries = [p for p in rd.iterdir() if p.is_dir()]
    except OSError:
        return []

    # Sort by mtime newest-first (run_id is also lexically sortable but
    # mtime survives manual renames).
    try:
        entries.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        pass

    summaries: list[dict] = []
    for run_dir in entries[: int(limit)]:
        manifest = _read_manifest(run_dir) or {}
        # `timestamp_utc` is the canonical run-start field written by
        # aria_os.run_manifest.create_run; accept legacy aliases too.
        started = (manifest.get("started_at")
                   or manifest.get("timestamp_utc"))
        completed = (manifest.get("completed_at")
                     or (manifest.get("pipeline_stats") or {}).get(
                         "completed_at"))
        # Success: prefer explicit `success`, else infer from
        # pipeline_stats.success_agent
        success = manifest.get("success")
        if success is None:
            success = (manifest.get("pipeline_stats") or {}).get(
                "success_agent")
        summaries.append({
            "run_id": run_dir.name,
            "goal": manifest.get("goal"),
            "part_name": manifest.get("part_name") or manifest.get("part_id"),
            "schema_version": manifest.get("schema_version"),
            "started_at": started,
            "completed_at": completed,
            "success": success,
            "agent_iterations": (manifest.get("pipeline_stats") or {})
                                .get("agent_iterations"),
            "artifact_count": sum(
                1 for p in run_dir.iterdir()
                if p.is_file() and p.name != _MANIFEST_FILENAME
            ),
        })
    return summaries


def get_run(run_id: str) -> Optional[dict]:
    """Full filesystem-side view of one run. Returns None if the run
    directory is missing."""
    rd = _runs_dir()
    if rd is None:
        return None
    run_dir = rd / run_id
    if not run_dir.is_dir():
        return None
    manifest = _read_manifest(run_dir)
    return {
        "run_id": run_id,
        "run_dir": str(run_dir),
        "manifest": manifest,
        "artifacts": _list_artifacts(run_dir),
    }


# ---------------------------------------------------------------------------
# Cross-stack joins
# ---------------------------------------------------------------------------

def find_millforge_job(db: Session, run_id: str) -> Optional[Job]:
    """Look up the MillForge Job that ARIA registered with this run_id.
    Tries `aria_run_id` (bundle path) first, then `aria_job_id` (full
    submission path) since either may carry the linkage."""
    from sqlalchemy import func

    job = (
        db.query(Job)
        .filter(func.json_extract(Job.cam_metadata, "$.aria_run_id") == run_id)
        .first()
    )
    if job is not None:
        return job
    job = (
        db.query(Job)
        .filter(func.json_extract(Job.cam_metadata, "$.aria_job_id") == run_id)
        .first()
    )
    return job


def floor_events_for_run(run_id: str, *,
                         job_id: Optional[int] = None,
                         limit: int = 200) -> list[dict]:
    """Pull events from aria_os.floor whose payload carries the run_id,
    OR whose job_id column matches (when a job has been registered on
    the floor and tagged with this run)."""
    out: list[dict] = []
    if floor.db_status()["state"] != "ok":
        return out
    try:
        with floor._ro_conn() as c:
            # The floor jobs table has a run_id column we can join on.
            cur = c.execute(
                "SELECT id FROM jobs WHERE run_id=?", (run_id,)
            )
            floor_job_ids = [int(r["id"]) for r in cur.fetchall()]
            params: list[Any] = []
            clauses: list[str] = []
            if floor_job_ids:
                placeholders = ",".join("?" for _ in floor_job_ids)
                clauses.append(f"job_id IN ({placeholders})")
                params.extend(floor_job_ids)
            if job_id is not None:
                clauses.append("job_id=?")
                params.append(int(job_id))
            # Also match if the run_id appears anywhere in payload_json
            clauses.append("payload_json LIKE ?")
            params.append(f'%{run_id}%')
            where = " OR ".join(clauses)
            params.append(int(limit))
            rows = c.execute(
                f"SELECT id, ts, kind, job_id, payload_json FROM events "
                f"WHERE {where} ORDER BY ts ASC LIMIT ?",
                params,
            ).fetchall()
            for r in rows:
                out.append({
                    "id": int(r["id"]),
                    "ts": float(r["ts"]),
                    "kind": r["kind"],
                    "job_id": r["job_id"],
                    "payload": _safe_json(r["payload_json"]),
                    "_source": "aria_floor",
                })
    except sqlite3.Error as exc:
        logger.warning("floor_events_for_run failed: %s", exc)
    except floor.FloorReaderUnavailable:
        pass
    return out


def millforge_pipeline_events(*, run_id: str,
                              job_id: Optional[str] = None,
                              limit: int = 200) -> list[dict]:
    """Read the MillForge JSONL pipeline log, filter to events that
    reference this run_id or job_id."""
    from services.pipeline_events import _LOG_PATH  # private but stable

    out: list[dict] = []
    if not _LOG_PATH.exists():
        return out
    try:
        with _LOG_PATH.open("r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return out

    needles = [run_id]
    if job_id:
        needles.append(str(job_id))

    for line in lines[-5000:]:                       # bounded scan
        if not any(n in line for n in needles):
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        # Convert ISO timestamp → epoch for unified ordering
        ts = _iso_to_epoch(ev.get("timestamp"))
        out.append({
            "ts": ts,
            "kind": ev.get("event_type"),
            "boundary": ev.get("boundary"),
            "trace_id": ev.get("trace_id"),
            "job_id": ev.get("job_id"),
            "status_code": ev.get("status_code"),
            "duration_ms": ev.get("duration_ms"),
            "extra": ev.get("extra") or {},
            "_source": "millforge_pipeline",
        })
        if len(out) >= int(limit):
            break
    return out


# ---------------------------------------------------------------------------
# Timeline assembly
# ---------------------------------------------------------------------------

def timeline(db: Session, run_id: str, *,
             event_limit: int = 200) -> dict:
    """Single composite timeline for one run.

    Output shape:
      {
        run_id, manifest, artifacts,
        millforge_job: {...} | None,
        events: [ {ts, source, kind, payload, ...} ]   sorted ascending
      }
    """
    fs = get_run(run_id) or {}
    job = find_millforge_job(db, run_id)

    events: list[dict] = []

    # Manifest milestones — emit 1 entry per known timestamp on the
    # manifest. The canonical run-start field is `timestamp_utc`; older
    # legacy fields like `started_at` are also accepted. Each milestone
    # gets a kind that names what stage produced it.
    manifest = fs.get("manifest") or {}
    milestone_keys = (
        "timestamp_utc",                # canonical run start
        "started_at",                   # legacy alias
        "spec_extracted_at", "geometry_emitted_at",
        "agent_loop_complete_at", "dfm_complete_at",
        "fea_complete_at", "cam_complete_at",
        "render_complete_at", "vault_complete_at",
        "completed_at",
    )
    for k in milestone_keys:
        v = manifest.get(k)
        if v is None:
            continue
        ts_epoch = _to_epoch(v)
        if ts_epoch is None:
            continue
        # Normalize the kind so the UI displays a consistent label
        kind = "run_started" if k in ("timestamp_utc", "started_at") else k
        events.append({
            "ts": ts_epoch,
            "kind": kind,
            "payload": {"source": "run_manifest", "raw_field": k},
            "_source": "aria_run_manifest",
        })

    # MillForge job stage history — derived from cam_metadata + timestamps
    job_dict: Optional[dict] = None
    if job is not None:
        job_dict = {
            "id": job.id,
            "title": job.title,
            "stage": job.stage,
            "source": job.source,
            "material": job.material,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "updated_at": job.updated_at.isoformat() if job.updated_at else None,
            "estimated_duration_minutes": job.estimated_duration_minutes,
            "cam_metadata_keys": list((job.cam_metadata or {}).keys()),
        }
        if job.created_at:
            events.append({
                "ts": job.created_at.timestamp(),
                "kind": "millforge_job_created",
                "payload": {"job_id": job.id, "stage": "queued"},
                "_source": "millforge_db",
            })
        if job.updated_at and job.updated_at != job.created_at:
            events.append({
                "ts": job.updated_at.timestamp(),
                "kind": f"millforge_job_{job.stage}",
                "payload": {"job_id": job.id, "stage": job.stage},
                "_source": "millforge_db",
            })

    # ARIA floor events with this run_id or job_id
    events.extend(floor_events_for_run(
        run_id,
        job_id=job.id if job is not None else None,
        limit=event_limit,
    ))

    # MillForge pipeline event log
    events.extend(millforge_pipeline_events(
        run_id=run_id,
        job_id=str(job.id) if job is not None else None,
        limit=event_limit,
    ))

    # Sort ascending; missing ts → push to start so they don't shuffle
    # into the middle of a real timeline
    events.sort(key=lambda e: (e.get("ts") or 0.0))

    return {
        "run_id": run_id,
        "manifest": manifest,
        "artifacts": fs.get("artifacts", []),
        "run_dir": fs.get("run_dir"),
        "millforge_job": job_dict,
        "events": events,
        "events_total": len(events),
    }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_json(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


def _iso_to_epoch(s: Optional[str]) -> Optional[float]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _to_epoch(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        return _iso_to_epoch(v)
    if isinstance(v, datetime):
        return v.timestamp()
    return None
