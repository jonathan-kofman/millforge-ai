"""Read-only adapter to the aria_os.floor SQLite events log.

The MillForge backend never imports `aria_os` directly — the bridge between
the two stacks is event-based. The aria_os pipeline writes a SQLite database
on the host (default location `outputs/floor_state.db` inside the aria-os
repo) and MillForge can optionally read it to surface lights-out shop-floor
state in the operator dashboard.

If `ARIA_FLOOR_DB_PATH` is not set or the file is missing, every reader call
returns a structured "unconfigured" / "unreachable" result rather than
raising — the dashboard still works, it just shows the millforge-only side.

The aria_os schema is documented in `aria_os/floor/state_store.py`. The bits
this reader cares about:

  machines  (id, name, controller, ...)
  jobs      (id, run_id, part_name, machine_id, status,
             queued_at, started_at, completed_at)
  events    (id, job_id, ts, kind, payload_json)

Event kinds we surface (originated in aria_os/floor/* modules):

  machine_down / machine_up             — reroute.py
  watchdog_trip                          — health_watchdog.py
  lights_off_pass / _borderline / _escalate
                                         — lights_off_policy.py
  gauging_queued / _in_transit / _measuring / _done / _failed
                                         — gauging_queue.py
  purchase_order / po_submitted / po_received / po_cancelled
  po_no_vendor / po_submit_failed        — procurement.py
  consumable_low / consumable_empty      — stock_inventory.py
  tool_needs_preset / tool_offset_applied
                                         — tool_presetter.py
  job_energy                             — energy_tracker.py
  spindle_warmup_injected                — spindle_warmup.py

All public methods are no-side-effect read paths.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional

logger = logging.getLogger(__name__)


_ENV_VAR = "ARIA_FLOOR_DB_PATH"


# ---------------------------------------------------------------------------
# Connection plumbing
# ---------------------------------------------------------------------------

class FloorReaderUnavailable(Exception):
    """Raised internally when the DB is missing or the connection fails.
    Caller-facing functions catch this and return a structured payload
    instead of bubbling the exception up to the HTTP layer."""


def _resolve_db_path() -> Optional[str]:
    p = os.getenv(_ENV_VAR, "").strip()
    if not p:
        return None
    return p


@contextmanager
def _ro_conn() -> Iterator[sqlite3.Connection]:
    path = _resolve_db_path()
    if not path:
        raise FloorReaderUnavailable("ARIA_FLOOR_DB_PATH not set")
    if not os.path.isfile(path):
        raise FloorReaderUnavailable(f"path does not exist: {path}")
    # Open read-only via URI so we never accidentally lock or write.
    uri = f"file:{path}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=2.0)
    except sqlite3.Error as exc:
        raise FloorReaderUnavailable(f"sqlite open failed: {exc}") from exc
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception:
            pass


def db_status() -> dict:
    """Lightweight 'is this thing alive' probe for the dashboard banner."""
    path = _resolve_db_path()
    if not path:
        return {"state": "unconfigured", "path": None,
                "hint": f"set {_ENV_VAR} to the aria-os floor_state.db"}
    if not os.path.isfile(path):
        return {"state": "missing", "path": path,
                "hint": "aria-os pipeline has not written the DB yet"}
    try:
        with _ro_conn() as c:
            r = c.execute("SELECT COUNT(*) AS n FROM events").fetchone()
            return {"state": "ok", "path": path,
                    "events_total": int(r["n"])}
    except FloorReaderUnavailable as exc:
        return {"state": "unreachable", "path": path,
                "error": str(exc)}
    except sqlite3.Error as exc:
        # Schema mismatch (very old aria-os) → treat as unreachable
        return {"state": "unreachable", "path": path,
                "error": f"schema probe failed: {exc}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_payload(s: Optional[str]) -> dict:
    if not s:
        return {}
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return {}


# Kinds that count as "active alerts" on the floor. value = severity.
_ALERT_SEVERITIES: dict[str, str] = {
    "machine_down":          "critical",
    "watchdog_trip":         "critical",
    "lights_off_escalate":   "critical",
    "fault":                 "high",
    "alarm":                 "high",
    "gauging_failed":        "high",
    "gauging_transfer_failed": "high",
    "po_no_vendor":          "high",
    "po_submit_failed":      "high",
    "consumable_empty":      "high",
    "stock_consume_failed":  "high",
    "consumable_low":        "medium",
    "tool_needs_preset":     "medium",
    "lights_off_borderline": "medium",
    "spindle_warmup_failed": "low",
}

# Kinds that "clear" prior alerts of the same family. Cleared once a
# clearing event with the same machine_id arrives more recently than the
# triggering one.
_ALERT_CLEARERS: dict[str, str] = {
    "machine_down":  "machine_up",
    "watchdog_trip": "watchdog_clear",
    "tool_needs_preset": "tool_offset_applied",
}


# ---------------------------------------------------------------------------
# Snapshot pieces
# ---------------------------------------------------------------------------

def list_machines() -> list[dict]:
    """All machines registered in the aria_os floor DB, with the latest
    derived status (ok / down / fault) and the active job ref if any."""
    try:
        with _ro_conn() as c:
            mrows = c.execute(
                "SELECT id, name, controller, controller_addr, "
                "       kinematics, max_spindle_rpm "
                "FROM machines ORDER BY id"
            ).fetchall()
            machines: list[dict] = []
            for m in mrows:
                # Latest machine_up / machine_down event for this machine.
                # The aria_os reroute module stores machine_id inside the
                # payload, not as a column on events, so we have to scan.
                latest = c.execute(
                    "SELECT kind, ts, payload_json FROM events "
                    "WHERE kind IN ('machine_down','machine_up') "
                    "  AND payload_json LIKE ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (f'%"machine_id": {m["id"]}%',),
                ).fetchone()
                if latest is None:
                    status = "unknown"
                    last_status_ts = None
                    status_reason = None
                else:
                    status = "ok" if latest["kind"] == "machine_up" else "down"
                    last_status_ts = float(latest["ts"])
                    status_reason = _safe_payload(latest["payload_json"]).get("reason")

                # Active job (status='running') on this machine. Use jobs
                # table directly — no payload scan needed.
                jrow = c.execute(
                    "SELECT id, run_id, part_name, started_at FROM jobs "
                    "WHERE machine_id=? AND status='running' "
                    "ORDER BY started_at DESC LIMIT 1",
                    (m["id"],),
                ).fetchone()
                active_job = None
                if jrow:
                    active_job = {
                        "job_id": jrow["id"],
                        "run_id": jrow["run_id"],
                        "part_name": jrow["part_name"],
                        "started_at": jrow["started_at"],
                    }

                # Latest watchdog_trip — sticky until a watchdog_clear arrives
                wd = c.execute(
                    "SELECT kind, ts, payload_json FROM events "
                    "WHERE kind IN ('watchdog_trip','watchdog_clear') "
                    "  AND payload_json LIKE ? "
                    "ORDER BY ts DESC LIMIT 1",
                    (f'%"machine_id": {m["id"]}%',),
                ).fetchone()
                watchdog_tripped = wd is not None and wd["kind"] == "watchdog_trip"

                machines.append({
                    "id": int(m["id"]),
                    "name": m["name"],
                    "controller": m["controller"],
                    "kinematics": m["kinematics"],
                    "max_spindle_rpm": m["max_spindle_rpm"],
                    "status": status,
                    "status_reason": status_reason,
                    "last_status_ts": last_status_ts,
                    "watchdog_tripped": watchdog_tripped,
                    "active_job": active_job,
                })
            return machines
    except FloorReaderUnavailable:
        return []
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.list_machines failed: %s", exc)
        return []


def queue_counts() -> dict:
    """Counts in each job lifecycle state on the floor."""
    out = {"queued": 0, "running": 0, "paused": 0,
           "complete": 0, "failed": 0, "cancelled": 0}
    try:
        with _ro_conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
            for r in rows:
                out[r["status"]] = int(r["n"])
    except FloorReaderUnavailable:
        pass
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.queue_counts failed: %s", exc)
    return out


def gauging_queue_summary() -> dict:
    """Mirror aria_os.floor.gauging_queue.queue_status() without importing it.
    Walks `gauging_*` events, picks latest per serial, and tallies states."""
    out = {"queued": 0, "in_transit": 0, "measuring": 0,
           "done": 0, "failed": 0}
    state_from_kind = {
        "gauging_queued":     "queued",
        "gauging_in_transit": "in_transit",
        "gauging_measuring":  "measuring",
        "gauging_done":       "done",
        "gauging_failed":     "failed",
        "gauging_transfer_failed": "failed",
    }
    try:
        with _ro_conn() as c:
            rows = c.execute(
                "SELECT kind, ts, payload_json FROM events "
                "WHERE kind LIKE 'gauging_%' "
                "ORDER BY ts ASC"
            ).fetchall()
    except FloorReaderUnavailable:
        return out
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.gauging_queue_summary failed: %s",
                       exc)
        return out

    by_serial: dict[str, str] = {}
    for r in rows:
        d = _safe_payload(r["payload_json"])
        serial = d.get("serial")
        if not serial:
            continue
        s = state_from_kind.get(r["kind"])
        if s is not None:
            by_serial[serial] = s
    for s in by_serial.values():
        if s in out:
            out[s] += 1
    return out


def open_purchase_orders() -> list[dict]:
    """List of POs whose latest state is emitted/submitted (mirrors
    procurement.open_pos without importing it)."""
    try:
        with _ro_conn() as c:
            rows = c.execute(
                "SELECT id, ts, kind, payload_json FROM events "
                "WHERE kind IN ('purchase_order','po_submitted',"
                "               'po_received','po_cancelled') "
                "ORDER BY ts ASC"
            ).fetchall()
    except FloorReaderUnavailable:
        return []
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.open_purchase_orders failed: %s",
                       exc)
        return []

    state: dict[int, dict] = {}
    transition = {
        "po_submitted": "submitted",
        "po_received":  "received",
        "po_cancelled": "cancelled",
    }
    for r in rows:
        d = _safe_payload(r["payload_json"])
        if r["kind"] == "purchase_order":
            state[r["id"]] = {**d, "po_id": r["id"],
                              "state": "emitted",
                              "emitted_at": float(r["ts"])}
        else:
            po_id = d.get("po_id")
            if po_id and po_id in state:
                state[po_id]["state"] = transition.get(
                    r["kind"], state[po_id]["state"])
    return [v for v in state.values()
            if v.get("state") in ("emitted", "submitted")]


def alerts(*, since_ts: Optional[float] = None,
           limit: int = 50) -> list[dict]:
    """Currently-actionable alerts. Walks events newest-first, tags each
    with a severity, and skips ones that have a more-recent clearing event
    on the same machine."""
    cutoff = float(since_ts) if since_ts is not None else 0.0
    kinds = list(_ALERT_SEVERITIES) + list(_ALERT_CLEARERS.values())
    placeholders = ",".join("?" for _ in kinds)
    try:
        with _ro_conn() as c:
            rows = c.execute(
                f"SELECT id, ts, kind, job_id, payload_json FROM events "
                f"WHERE ts >= ? AND kind IN ({placeholders}) "
                f"ORDER BY ts DESC LIMIT 500",
                (cutoff, *kinds),
            ).fetchall()
    except FloorReaderUnavailable:
        return []
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.alerts failed: %s", exc)
        return []

    cleared_keys: set[tuple[str, Any]] = set()  # (clearer_kind, machine_id)
    out: list[dict] = []
    for r in rows:
        d = _safe_payload(r["payload_json"])
        machine_id = d.get("machine_id")
        if r["kind"] in _ALERT_CLEARERS.values():
            # Track for later passes — when we encounter the matching
            # alert kind, skip if its (kind, machine_id) is already cleared.
            cleared_keys.add((r["kind"], machine_id))
            continue
        clearer = _ALERT_CLEARERS.get(r["kind"])
        if clearer is not None and (clearer, machine_id) in cleared_keys:
            continue
        out.append({
            "id": int(r["id"]),
            "ts": float(r["ts"]),
            "kind": r["kind"],
            "severity": _ALERT_SEVERITIES.get(r["kind"], "low"),
            "machine_id": machine_id,
            "job_id": r["job_id"],
            "payload": d,
        })
        if len(out) >= limit:
            break
    return out


def energy_summary(*, since_ts: Optional[float] = None) -> dict:
    """Tally job_energy events since `since_ts` (default: last 24h)."""
    if since_ts is None:
        since_ts = time.time() - 86400.0
    try:
        with _ro_conn() as c:
            rows = c.execute(
                "SELECT ts, payload_json FROM events "
                "WHERE kind='job_energy' AND ts >= ?",
                (float(since_ts),),
            ).fetchall()
    except FloorReaderUnavailable:
        return {"window_s": time.time() - since_ts,
                "kwh_total": 0.0, "jobs": 0,
                "anomalies": 0, "co2_kg_total": 0.0}
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.energy_summary failed: %s", exc)
        return {"window_s": time.time() - since_ts,
                "kwh_total": 0.0, "jobs": 0,
                "anomalies": 0, "co2_kg_total": 0.0}

    kwh = 0.0
    co2 = 0.0
    anomalies = 0
    for r in rows:
        d = _safe_payload(r["payload_json"])
        try:
            kwh += float(d.get("kwh", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
        try:
            co2 += float(d.get("co2_kg", 0.0) or 0.0)
        except (TypeError, ValueError):
            pass
        if d.get("anomaly"):
            anomalies += 1
    return {
        "window_s": time.time() - since_ts,
        "kwh_total": round(kwh, 3),
        "co2_kg_total": round(co2, 3),
        "jobs": len(rows),
        "anomalies": anomalies,
    }


def timeline(*, since_ts: Optional[float] = None,
             kinds: Optional[Iterable[str]] = None,
             limit: int = 200) -> list[dict]:
    """Raw event timeline for the operator UI. Caller filters by kind."""
    cutoff = float(since_ts) if since_ts is not None else 0.0
    try:
        with _ro_conn() as c:
            if kinds:
                kinds_list = list(kinds)
                placeholders = ",".join("?" for _ in kinds_list)
                rows = c.execute(
                    f"SELECT id, ts, kind, job_id, payload_json FROM events "
                    f"WHERE ts >= ? AND kind IN ({placeholders}) "
                    f"ORDER BY ts DESC LIMIT ?",
                    (cutoff, *kinds_list, int(limit)),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT id, ts, kind, job_id, payload_json FROM events "
                    "WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                    (cutoff, int(limit)),
                ).fetchall()
    except FloorReaderUnavailable:
        return []
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.timeline failed: %s", exc)
        return []

    return [{
        "id": int(r["id"]),
        "ts": float(r["ts"]),
        "kind": r["kind"],
        "job_id": r["job_id"],
        "payload": _safe_payload(r["payload_json"]),
    } for r in rows]


def machine_detail(machine_id: int, *,
                   timeline_limit: int = 50) -> Optional[dict]:
    """Per-machine deep dive: definition, current job, recent events."""
    try:
        with _ro_conn() as c:
            m = c.execute(
                "SELECT id, name, controller, controller_addr, "
                "       max_x_mm, max_y_mm, max_z_mm, max_spindle_rpm, "
                "       kinematics FROM machines WHERE id=?",
                (int(machine_id),),
            ).fetchone()
            if m is None:
                return None
            jobs_q = c.execute(
                "SELECT id, run_id, part_name, status, "
                "       queued_at, started_at, completed_at "
                "FROM jobs WHERE machine_id=? "
                "ORDER BY queued_at DESC LIMIT 20",
                (int(machine_id),),
            ).fetchall()
            evrows = c.execute(
                "SELECT id, ts, kind, job_id, payload_json FROM events "
                "WHERE payload_json LIKE ? "
                "ORDER BY ts DESC LIMIT ?",
                (f'%"machine_id": {int(machine_id)}%', int(timeline_limit)),
            ).fetchall()
    except FloorReaderUnavailable:
        return None
    except sqlite3.Error as exc:
        logger.warning("floor_state_reader.machine_detail failed: %s", exc)
        return None

    # Find this machine in the broader list to inherit derived fields
    derived = next((row for row in list_machines()
                    if row["id"] == int(machine_id)), None)

    return {
        "id": int(m["id"]),
        "name": m["name"],
        "controller": m["controller"],
        "controller_addr": m["controller_addr"],
        "max_envelope_mm": {
            "x": m["max_x_mm"], "y": m["max_y_mm"], "z": m["max_z_mm"]},
        "max_spindle_rpm": m["max_spindle_rpm"],
        "kinematics": m["kinematics"],
        "status": (derived or {}).get("status", "unknown"),
        "watchdog_tripped": (derived or {}).get("watchdog_tripped", False),
        "active_job": (derived or {}).get("active_job"),
        "recent_jobs": [{
            "job_id": int(r["id"]),
            "run_id": r["run_id"],
            "part_name": r["part_name"],
            "status": r["status"],
            "queued_at": r["queued_at"],
            "started_at": r["started_at"],
            "completed_at": r["completed_at"],
        } for r in jobs_q],
        "recent_events": [{
            "id": int(r["id"]),
            "ts": float(r["ts"]),
            "kind": r["kind"],
            "job_id": r["job_id"],
            "payload": _safe_payload(r["payload_json"]),
        } for r in evrows],
    }


# ---------------------------------------------------------------------------
# Top-level snapshot — single shape consumed by the dashboard
# ---------------------------------------------------------------------------

def snapshot(*, alerts_limit: int = 25) -> dict:
    """Single composite call used by the operator dashboard front page."""
    status = db_status()
    if status["state"] != "ok":
        return {
            "as_of": time.time(),
            "aria_floor": status,
            "machines": [],
            "queue": {},
            "gauging": {},
            "purchase_orders": [],
            "alerts": [],
            "energy_24h": {},
        }
    return {
        "as_of": time.time(),
        "aria_floor": status,
        "machines": list_machines(),
        "queue": queue_counts(),
        "gauging": gauging_queue_summary(),
        "purchase_orders": open_purchase_orders(),
        "alerts": alerts(limit=alerts_limit),
        "energy_24h": energy_summary(),
    }
