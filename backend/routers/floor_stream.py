"""Unified live event stream — `/api/floor/stream` (SSE).

Subscribers (operator dashboard, StructSight live floor tab, ops alerting)
get one feed that fuses:

  * **aria_os.floor events** — new rows in the events table since the
    last id seen. Source label: `aria_floor`.
  * **MillForge pipeline_events.jsonl** — new lines since the last byte
    offset seen. Source label: `millforge_pipeline`.
  * **MillForge DB stage transitions** — Job rows whose `updated_at`
    advanced since the last tick. Source label: `millforge_job`.

The producer-side modules don't have to push anywhere; this consumer
polls cheaply (1.5 s default) and never holds a writer lock on the
SQLite DB (read-only URI mode).

Connection lifecycle:
  * 60-min ceiling (configurable via `?max_minutes=N` up to 240).
  * `:keepalive` comment every 25 s to keep proxies happy.
  * Closes when the client disconnects (StarletteResponse handles it).

Filters via query params:
  * `kinds=` — repeat to whitelist event kinds (any source).
  * `since_ts=` — bootstrap with everything since this UNIX time.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import AsyncIterator, Iterable, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db, SessionLocal
from db_models import Job, User
from services import floor_state_reader as floor

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/floor", tags=["Floor Dashboard"])

_POLL_S_DEFAULT = 1.5
_KEEPALIVE_S = 25.0
_DEFAULT_MAX_MIN = 60
_HARD_MAX_MIN = 240
_MILLFORGE_JOBS_BATCH = 25


# ---------------------------------------------------------------------------
# Producers — read-only, cheap, never raise
# ---------------------------------------------------------------------------

def _aria_new_events(last_id: int, *,
                     kinds: Optional[set[str]] = None,
                     limit: int = 200) -> tuple[list[dict], int]:
    """Pull events from the aria_os.floor SQLite with id > last_id.
    Returns (events, new_high_water_id). Empty + same id on miss/error."""
    if floor.db_status()["state"] != "ok":
        return [], last_id
    try:
        with floor._ro_conn() as c:
            sql = (
                "SELECT id, ts, kind, job_id, payload_json FROM events "
                "WHERE id > ? "
            )
            params: list = [int(last_id)]
            if kinds:
                placeholders = ",".join("?" for _ in kinds)
                sql += f"AND kind IN ({placeholders}) "
                params.extend(kinds)
            sql += "ORDER BY id ASC LIMIT ?"
            params.append(int(limit))
            rows = c.execute(sql, params).fetchall()
    except sqlite3.Error as exc:
        logger.warning("floor stream aria poll failed: %s", exc)
        return [], last_id
    except floor.FloorReaderUnavailable:
        return [], last_id

    out: list[dict] = []
    new_high = last_id
    for r in rows:
        new_high = max(new_high, int(r["id"]))
        out.append({
            "source": "aria_floor",
            "id": int(r["id"]),
            "ts": float(r["ts"]),
            "kind": r["kind"],
            "job_id": r["job_id"],
            "payload": _safe_json(r["payload_json"]),
        })
    return out, new_high


def _millforge_pipeline_new(last_offset: int, *,
                            kinds: Optional[set[str]] = None,
                            limit: int = 200) -> tuple[list[dict], int]:
    """Tail the JSONL pipeline_events log starting at byte offset
    `last_offset`. Returns (events, new_offset)."""
    from services.pipeline_events import _LOG_PATH

    if not _LOG_PATH.exists():
        return [], last_offset
    out: list[dict] = []
    try:
        with _LOG_PATH.open("rb") as f:
            f.seek(int(last_offset))
            data = f.read()
            new_offset = f.tell()
    except OSError as exc:
        logger.warning("pipeline log tail failed: %s", exc)
        return [], last_offset

    for raw_line in data.splitlines():
        if not raw_line.strip():
            continue
        try:
            ev = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        kind = ev.get("event_type")
        if kinds and kind not in kinds:
            continue
        out.append({
            "source": "millforge_pipeline",
            "ts": _iso_to_epoch(ev.get("timestamp")) or time.time(),
            "kind": kind,
            "boundary": ev.get("boundary"),
            "trace_id": ev.get("trace_id"),
            "job_id": ev.get("job_id"),
            "status_code": ev.get("status_code"),
            "duration_ms": ev.get("duration_ms"),
            "extra": ev.get("extra") or {},
        })
        if len(out) >= int(limit):
            break
    return out, new_offset


def _millforge_job_changes(last_seen: float, *,
                           limit: int = _MILLFORGE_JOBS_BATCH
                           ) -> tuple[list[dict], float]:
    """MillForge DB Jobs whose updated_at advanced since `last_seen`.
    Uses an isolated session so it can run inside the SSE generator."""
    out: list[dict] = []
    new_high = last_seen
    db: Optional[Session] = None
    try:
        db = SessionLocal()
        from datetime import datetime
        cutoff = datetime.utcfromtimestamp(last_seen)
        rows = (
            db.query(Job)
            .filter(Job.updated_at > cutoff)
            .order_by(Job.updated_at.asc())
            .limit(int(limit))
            .all()
        )
        for j in rows:
            ts = j.updated_at.timestamp() if j.updated_at else time.time()
            new_high = max(new_high, ts)
            meta = j.cam_metadata or {}
            out.append({
                "source": "millforge_job",
                "ts": ts,
                "kind": f"job_{j.stage}",
                "job_id": j.id,
                "title": j.title,
                "stage": j.stage,
                "aria_run_id": meta.get("aria_run_id"),
                "aria_job_id": meta.get("aria_job_id"),
            })
    except Exception as exc:                     # pragma: no cover
        logger.warning("millforge job poll failed: %s", exc)
    finally:
        if db is not None:
            db.close()
    return out, new_high


# ---------------------------------------------------------------------------
# SSE generator
# ---------------------------------------------------------------------------

def _sse(line: dict | str, *, event: Optional[str] = None) -> bytes:
    if isinstance(line, dict):
        body = json.dumps(line, default=str)
    else:
        body = str(line)
    parts = []
    if event:
        parts.append(f"event: {event}")
    parts.append(f"data: {body}")
    return ("\n".join(parts) + "\n\n").encode("utf-8")


async def _stream(*, since_ts: Optional[float],
                  kinds: Optional[set[str]],
                  poll_s: float,
                  max_seconds: float) -> AsyncIterator[bytes]:
    """Async generator producing SSE frames."""
    started = time.time()

    # Bootstrap watermarks. If `since_ts` is given, replay from that
    # point; otherwise start at "now".
    aria_high_id = _aria_id_at(since_ts) if since_ts else _aria_max_id()
    pipeline_offset = _pipeline_size_now()
    job_high_ts = since_ts if since_ts else time.time()

    yield _sse({
        "ts": time.time(),
        "msg": "stream_open",
        "since_ts": since_ts,
        "kinds": list(kinds) if kinds else None,
        "max_seconds": max_seconds,
    }, event="hello")

    last_keepalive = time.time()
    while time.time() - started < max_seconds:
        any_emitted = False

        aria_evs, aria_high_id = _aria_new_events(
            aria_high_id, kinds=kinds, limit=200)
        for ev in aria_evs:
            yield _sse(ev, event="event")
            any_emitted = True

        pipeline_evs, pipeline_offset = _millforge_pipeline_new(
            pipeline_offset, kinds=kinds, limit=200)
        for ev in pipeline_evs:
            yield _sse(ev, event="event")
            any_emitted = True

        # Job-stage events ignore the kind filter (different namespace)
        job_evs, job_high_ts = _millforge_job_changes(job_high_ts)
        for ev in job_evs:
            yield _sse(ev, event="event")
            any_emitted = True

        if not any_emitted and time.time() - last_keepalive > _KEEPALIVE_S:
            yield b": keepalive\n\n"
            last_keepalive = time.time()

        await asyncio.sleep(poll_s)

    yield _sse({"ts": time.time(), "msg": "stream_closed",
                "elapsed_s": time.time() - started}, event="bye")


# ---------------------------------------------------------------------------
# Watermark helpers
# ---------------------------------------------------------------------------

def _aria_max_id() -> int:
    if floor.db_status()["state"] != "ok":
        return 0
    try:
        with floor._ro_conn() as c:
            r = c.execute(
                "SELECT COALESCE(MAX(id), 0) AS m FROM events"
            ).fetchone()
            return int(r["m"]) if r else 0
    except (sqlite3.Error, floor.FloorReaderUnavailable):
        return 0


def _aria_id_at(ts: float) -> int:
    """Highest event id with ts < `ts`. Used to bootstrap a replay."""
    if floor.db_status()["state"] != "ok":
        return 0
    try:
        with floor._ro_conn() as c:
            r = c.execute(
                "SELECT COALESCE(MAX(id), 0) AS m FROM events WHERE ts < ?",
                (float(ts),),
            ).fetchone()
            return int(r["m"]) if r else 0
    except (sqlite3.Error, floor.FloorReaderUnavailable):
        return 0


def _pipeline_size_now() -> int:
    from services.pipeline_events import _LOG_PATH
    try:
        return _LOG_PATH.stat().st_size if _LOG_PATH.exists() else 0
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get(
    "/stream",
    summary="Unified live event stream (SSE)",
    description=(
        "Single Server-Sent Events feed combining aria_os.floor events, "
        "MillForge pipeline events, and Job stage transitions. Used by "
        "the operator dashboard and the StructSight live-floor view. "
        "Auth via JWT cookie (passed by the browser fetch with credentials)."
    ),
)
async def stream_events(
    since_ts: Optional[float] = Query(
        None,
        description=(
            "UNIX time to replay from. Omit to start at 'now'. Useful for "
            "reconnect-with-resume after a brief network drop."
        ),
    ),
    kinds: Optional[list[str]] = Query(
        None, description="Repeat to whitelist event kinds"),
    poll_s: float = Query(_POLL_S_DEFAULT, ge=0.5, le=10.0),
    max_minutes: int = Query(_DEFAULT_MAX_MIN, ge=1, le=_HARD_MAX_MIN),
    _user: User = Depends(get_current_user),
):
    kinds_set = set(kinds) if kinds else None
    return StreamingResponse(
        _stream(
            since_ts=since_ts,
            kinds=kinds_set,
            poll_s=float(poll_s),
            max_seconds=float(max_minutes) * 60.0,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


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
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None
