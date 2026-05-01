"""Run registry router — `/api/runs/*`.

Cross-stack views over a single ARIA run_id: list, detail, timeline,
artifact download. Backed by `services.run_registry`, which fuses
aria-os filesystem outputs + MillForge DB + aria_os.floor events into
one ordered story.

This is the "what happened to part X end-to-end" surface that
StructSight, the operator dashboard, and any external dashboarding
tool can lean on.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import User
from services import run_registry

router = APIRouter(prefix="/api/runs", tags=["Runs"])


@router.get(
    "",
    summary="List recent ARIA runs",
    description=(
        "Walks the aria-os outputs/runs/ directory and returns a brief "
        "summary per run. Newest-first by mtime. Configure path with the "
        "ARIA_OUTPUTS_PATH env var; defaults to a sibling aria-os repo."
    ),
)
def list_runs(
    limit: int = Query(50, ge=1, le=500),
    _user: User = Depends(get_current_user),
):
    return {"runs": run_registry.list_runs(limit=limit)}


@router.get(
    "/{run_id}",
    summary="Single-run filesystem view",
    description=(
        "Manifest + artifacts list for one run_id. Useful when the caller "
        "only needs the artifact catalogue and not the cross-stack timeline."
    ),
)
def get_run(
    run_id: str,
    _user: User = Depends(get_current_user),
):
    r = run_registry.get_run(run_id)
    if r is None:
        raise HTTPException(status_code=404,
                            detail=f"run_id={run_id!r} not found")
    return r


@router.get(
    "/{run_id}/timeline",
    summary="Cross-stack timeline for a run",
    description=(
        "One ordered timeline merging aria-os manifest milestones, "
        "MillForge job stage transitions, aria_os.floor events tagged "
        "with this run, and MillForge pipeline_events.jsonl entries."
    ),
)
def get_timeline(
    run_id: str,
    event_limit: int = Query(200, ge=1, le=2000),
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    return run_registry.timeline(db, run_id, event_limit=event_limit)


@router.get(
    "/{run_id}/artifact/{name}",
    summary="Download an artifact from a run dir",
    description=(
        "Streams an artifact file from outputs/runs/<run_id>/<name>. "
        "Restricted to the run dir — no path traversal allowed."
    ),
)
def get_artifact(
    run_id: str,
    name: str,
    _user: User = Depends(get_current_user),
):
    r = run_registry.get_run(run_id)
    if r is None or not r.get("run_dir"):
        raise HTTPException(status_code=404, detail="run not found")
    run_dir = Path(r["run_dir"]).resolve()

    # Path-traversal guard: reject anything that escapes the run dir.
    requested = (run_dir / name).resolve()
    try:
        requested.relative_to(run_dir)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail="path traversal not allowed")
    if not requested.is_file():
        raise HTTPException(status_code=404, detail="artifact not found")

    return FileResponse(
        path=str(requested),
        filename=name,
        media_type="application/octet-stream",
    )
