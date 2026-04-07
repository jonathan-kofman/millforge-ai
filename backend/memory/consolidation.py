"""MillForge Knowledge Base Consolidation.

Runs as a background process between sessions.
Merges new information from session logs, interviews, benchmarks,
and shop configs into persistent Markdown topic files.

Directory layout (all under data/memory/):
  INDEX.md                — master index (<200 lines, <25 KB)
  shop_profiles.md        — per-shop knowledge
  scheduling_patterns.md  — algorithm × shop-type learnings
  supplier_insights.md    — lead times, reliability, regional patterns
  discovery_insights.md   — validated hypotheses from customer interviews
  archive/                — pruned historical data
  .consolidation_lock     — file-based mutex
  .last_consolidation     — UTC timestamp of last successful run
  .session_count          — integer, resets after consolidation

Three-Gate Trigger:
  Gate 1 — time    : >= 24 h since last consolidation
  Gate 2 — activity: >= 5 new scheduling sessions since last run
  Gate 3 — lock    : acquire .consolidation_lock (prevents concurrent runs)

All gates must pass before consolidation begins.
The process has READ-ONLY access to production data.
It may only WRITE to data/memory/.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Paths ─────────────────────────────────────────────────────────────────────

_MEMORY_DIR = Path("data/memory")
_ARCHIVE_DIR = _MEMORY_DIR / "archive"

_INDEX = _MEMORY_DIR / "INDEX.md"
_SHOP_PROFILES = _MEMORY_DIR / "shop_profiles.md"
_SCHEDULING_PATTERNS = _MEMORY_DIR / "scheduling_patterns.md"
_SUPPLIER_INSIGHTS = _MEMORY_DIR / "supplier_insights.md"
_DISCOVERY_INSIGHTS = _MEMORY_DIR / "discovery_insights.md"

_LOCK_FILE = _MEMORY_DIR / ".consolidation_lock"
_LAST_RUN_FILE = _MEMORY_DIR / ".last_consolidation"
_SESSION_COUNT_FILE = _MEMORY_DIR / ".session_count"

_MIN_HOURS_BETWEEN_RUNS = 24
_MIN_SESSIONS_BEFORE_RUN = 5
_MAX_INDEX_LINES = 200
_MAX_INDEX_BYTES = 25 * 1024  # 25 KB


# ── Gate system ───────────────────────────────────────────────────────────────

def _read_last_run_timestamp() -> float:
    """Return epoch seconds of last consolidation, or 0.0 if never run."""
    if _LAST_RUN_FILE.exists():
        try:
            return float(_LAST_RUN_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    return 0.0


def _read_session_count() -> int:
    if _SESSION_COUNT_FILE.exists():
        try:
            return int(_SESSION_COUNT_FILE.read_text(encoding="utf-8").strip())
        except ValueError:
            pass
    return 0


def _write_session_count(n: int) -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _SESSION_COUNT_FILE.write_text(str(n), encoding="utf-8")


def increment_session_count() -> int:
    """Call this at the start of every scheduling session."""
    n = _read_session_count() + 1
    _write_session_count(n)
    logger.debug("Session count → %d", n)
    return n


def check_gates() -> dict[str, Any]:
    """
    Evaluate all three gates.

    Returns a dict with:
      gate_1_time: bool
      gate_2_activity: bool
      gate_3_lock: bool  (True = lock is NOT currently held = available)
      all_pass: bool
      hours_since_last: float
      sessions_since_last: int
      reason: str
    """
    now = time.time()
    last_run = _read_last_run_timestamp()
    hours_since = (now - last_run) / 3600.0
    sessions = _read_session_count()
    lock_free = not _LOCK_FILE.exists()

    gate1 = hours_since >= _MIN_HOURS_BETWEEN_RUNS
    gate2 = sessions >= _MIN_SESSIONS_BEFORE_RUN
    gate3 = lock_free
    all_pass = gate1 and gate2 and gate3

    reasons: list[str] = []
    if not gate1:
        reasons.append(f"only {hours_since:.1f}h since last run (need {_MIN_HOURS_BETWEEN_RUNS}h)")
    if not gate2:
        reasons.append(f"only {sessions} sessions since last run (need {_MIN_SESSIONS_BEFORE_RUN})")
    if not gate3:
        reasons.append("consolidation already running (lock held)")

    return {
        "gate_1_time": gate1,
        "gate_2_activity": gate2,
        "gate_3_lock": gate3,
        "all_pass": all_pass,
        "hours_since_last": round(hours_since, 2),
        "sessions_since_last": sessions,
        "reason": "; ".join(reasons) if reasons else "all gates pass",
    }


# ── Lock helpers ──────────────────────────────────────────────────────────────

class _ConsolidationLock:
    """Context manager for the file-based lock."""

    def __enter__(self) -> "_ConsolidationLock":
        _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        if _LOCK_FILE.exists():
            raise RuntimeError("Consolidation lock already held — concurrent run prevented.")
        _LOCK_FILE.write_text(str(os.getpid()), encoding="utf-8")
        logger.debug("Consolidation lock acquired (pid=%d)", os.getpid())
        return self

    def __exit__(self, *_: object) -> None:
        _LOCK_FILE.unlink(missing_ok=True)
        logger.debug("Consolidation lock released")


# ── Read-only data accessors ──────────────────────────────────────────────────

def _gather_recent_shop_configs(db: Any | None) -> list[dict[str, Any]]:
    """Read shop configs from DB (read-only). Returns list of config dicts."""
    if db is None:
        return []
    try:
        from db_models import ShopConfig  # type: ignore[import]
        rows = db.query(ShopConfig).order_by(ShopConfig.updated_at.desc()).limit(50).all()
        return [
            {
                "shop_name": r.shop_name,
                "machine_count": r.machine_count,
                "shifts_per_day": r.shifts_per_day,
                "hours_per_shift": r.hours_per_shift,
                "scheduling_method": r.scheduling_method,
                "baseline_otd": r.baseline_otd,
                "weekly_order_volume": r.weekly_order_volume,
                "updated_at": str(getattr(r, "updated_at", "")),
            }
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Could not read ShopConfig: %s", exc)
        return []


def _gather_recent_interviews(db: Any | None) -> list[dict[str, Any]]:
    """Read customer discovery interviews (read-only)."""
    if db is None:
        return []
    try:
        from discovery.models import Interview, Insight  # type: ignore[import]
        rows = db.query(Interview).order_by(Interview.date.desc()).limit(20).all()
        out = []
        for row in rows:
            insights = db.query(Insight).filter(Insight.interview_id == row.id).all()
            out.append({
                "shop_name": row.shop_name,
                "shop_size": row.shop_size,
                "role": row.role,
                "date": str(row.date),
                "insight_count": len(insights),
                "top_pains": [i.content for i in insights if i.category == "pain_point"][:3],
                "wtp_signals": [i.content for i in insights if i.category == "wtp_signal"][:2],
            })
        return out
    except Exception as exc:
        logger.warning("Could not read discovery interviews: %s", exc)
        return []


def _gather_benchmark_results() -> list[dict[str, Any]]:
    """Read latest benchmark data (read-only, from benchmark_data module)."""
    try:
        from agents.benchmark_data import get_mock_orders  # type: ignore[import]
        from agents.scheduler import Scheduler  # type: ignore[import]
        from agents.sa_scheduler import SAScheduler  # type: ignore[import]

        orders = get_mock_orders()
        fifo_schedule = Scheduler(orders=orders).optimize()
        sa_schedule = SAScheduler().optimize(orders)

        fifo_ot = sum(1 for o in fifo_schedule.scheduled_orders if o.on_time)
        sa_ot = sum(1 for o in sa_schedule.scheduled_orders if o.on_time)
        total = len(orders)

        return [{
            "source": "benchmark",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fifo_on_time_pct": round(fifo_ot / total * 100, 1) if total else 0,
            "sa_on_time_pct": round(sa_ot / total * 100, 1) if total else 0,
            "improvement_pp": round((sa_ot - fifo_ot) / total * 100, 1) if total else 0,
        }]
    except Exception as exc:
        logger.warning("Could not gather benchmark results: %s", exc)
        return []


# ── Topic file writers (WRITE ONLY to data/memory/) ──────────────────────────

def _ensure_memory_dir() -> None:
    _MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    _ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)


def _update_shop_profiles(configs: list[dict[str, Any]]) -> int:
    """Merge latest shop configs into shop_profiles.md. Returns lines written."""
    if not configs:
        return 0

    existing = _SHOP_PROFILES.read_text(encoding="utf-8") if _SHOP_PROFILES.exists() else "# Shop Profiles\n\n"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_sections: list[str] = []

    for cfg in configs:
        name = cfg.get("shop_name") or "Unknown Shop"
        section = (
            f"## {name}\n"
            f"- machines: {cfg.get('machine_count', 'unknown')}\n"
            f"- shifts: {cfg.get('shifts_per_day', '?')} × {cfg.get('hours_per_shift', '?')}h\n"
            f"- scheduling_method: {cfg.get('scheduling_method', 'unknown')}\n"
            f"- baseline_otd: {cfg.get('baseline_otd', '?')}%\n"
            f"- weekly_volume: {cfg.get('weekly_order_volume', '?')}\n"
            f"- last_seen: {ts}\n\n"
        )
        # Replace existing section for this shop, or append
        header = f"## {name}\n"
        if header in existing:
            # Find and replace the section
            start = existing.index(header)
            end = existing.find("\n## ", start + 1)
            if end == -1:
                existing = existing[:start] + section
            else:
                existing = existing[:start] + section + existing[end:]
        else:
            existing += section
        new_sections.append(name)

    _SHOP_PROFILES.write_text(existing, encoding="utf-8")
    logger.info("CONSOLIDATE: updated shop_profiles.md (%d shops)", len(new_sections))
    return len(new_sections)


def _update_discovery_insights(interviews: list[dict[str, Any]]) -> int:
    if not interviews:
        return 0

    existing = _DISCOVERY_INSIGHTS.read_text(encoding="utf-8") if _DISCOVERY_INSIGHTS.exists() else "# Customer Discovery Insights\n\n"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_lines: list[str] = [f"\n## Interview Batch consolidated {ts}\n"]

    pain_counts: dict[str, int] = {}
    wtp_signals: list[str] = []
    for iv in interviews:
        for pain in iv.get("top_pains", []):
            pain_counts[pain] = pain_counts.get(pain, 0) + 1
        wtp_signals.extend(iv.get("wtp_signals", []))

    if pain_counts:
        new_lines.append("### Top Pain Points\n")
        for pain, count in sorted(pain_counts.items(), key=lambda x: -x[1]):
            new_lines.append(f"- [{count}x] {pain}\n")

    if wtp_signals:
        new_lines.append("\n### WTP Signals\n")
        for sig in dict.fromkeys(wtp_signals):  # deduplicate while preserving order
            new_lines.append(f"- {sig}\n")

    new_lines.append(f"\nTotal interviews in batch: {len(interviews)}\n")
    _DISCOVERY_INSIGHTS.write_text(existing + "".join(new_lines), encoding="utf-8")
    logger.info("CONSOLIDATE: updated discovery_insights.md (%d interviews)", len(interviews))
    return len(interviews)


def _update_scheduling_patterns(benchmarks: list[dict[str, Any]]) -> None:
    if not benchmarks:
        return
    existing = _SCHEDULING_PATTERNS.read_text(encoding="utf-8") if _SCHEDULING_PATTERNS.exists() else "# Scheduling Patterns\n\n"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for bm in benchmarks:
        entry = (
            f"\n## Benchmark run {ts}\n"
            f"- FIFO on-time: {bm.get('fifo_on_time_pct')}%\n"
            f"- SA on-time: {bm.get('sa_on_time_pct')}%\n"
            f"- Improvement: +{bm.get('improvement_pp')}pp\n"
        )
        existing += entry
    _SCHEDULING_PATTERNS.write_text(existing, encoding="utf-8")
    logger.info("CONSOLIDATE: updated scheduling_patterns.md")


# ── Prune ─────────────────────────────────────────────────────────────────────

def _prune_index() -> None:
    """Keep INDEX.md under _MAX_INDEX_LINES lines and _MAX_INDEX_BYTES bytes."""
    if not _INDEX.exists():
        return

    content = _INDEX.read_text(encoding="utf-8")
    lines = content.splitlines(keepends=True)
    size = len(content.encode("utf-8"))

    if len(lines) <= _MAX_INDEX_LINES and size <= _MAX_INDEX_BYTES:
        return

    logger.info("PRUNE: INDEX.md has %d lines / %d bytes — pruning", len(lines), size)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    archive_path = _ARCHIVE_DIR / f"INDEX_{ts}.md"
    archive_path.write_text(content, encoding="utf-8")

    # Keep the most recent _MAX_INDEX_LINES lines
    kept = lines[-_MAX_INDEX_LINES:]
    header = f"# MillForge Knowledge Index (pruned {ts})\n\nSee archive/ for history.\n\n"
    _INDEX.write_text(header + "".join(kept), encoding="utf-8")
    logger.info("PRUNE: INDEX.md reduced to %d lines, archived to %s", len(kept), archive_path.name)


def _rebuild_index() -> None:
    """Regenerate INDEX.md from the current topic files."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        f"# MillForge Knowledge Index\n",
        f"Last consolidated: {ts}\n\n",
        "## Topic Files\n",
    ]

    for path, desc in [
        (_SHOP_PROFILES, "Per-shop machine counts, shifts, scheduling methods, baseline OTD"),
        (_SCHEDULING_PATTERNS, "Algorithm performance benchmarks and shop-type learnings"),
        (_SUPPLIER_INSIGHTS, "Lead times, reliability scores, regional coverage"),
        (_DISCOVERY_INSIGHTS, "Customer pain points, WTP signals, validated hypotheses"),
    ]:
        exists = "✓" if path.exists() else "○"
        size = f"{path.stat().st_size // 1024}KB" if path.exists() else "empty"
        lines.append(f"- {exists} [{path.name}]({path.name}) — {desc} ({size})\n")

    _INDEX.write_text("".join(lines), encoding="utf-8")
    logger.info("INDEX.md rebuilt (%d lines)", len(lines))


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_consolidation(db: Any | None = None) -> dict[str, Any]:
    """
    Run the full four-phase consolidation.

    Returns a summary dict. Raises RuntimeError if gates don't pass.
    Safe to call from FastAPI background tasks or a cron loop.
    """
    # ── Gate check ────────────────────────────────────────────────────────
    gates = check_gates()
    if not gates["all_pass"]:
        logger.info("Consolidation skipped: %s", gates["reason"])
        return {"skipped": True, "reason": gates["reason"], "gates": gates}

    _ensure_memory_dir()

    with _ConsolidationLock():
        start_ts = time.time()
        logger.info("=== CONSOLIDATION START ===")

        # Phase 1: ORIENT — read current index and topic files
        logger.info("[ORIENT] Reading current knowledge index")
        current_index = _INDEX.read_text(encoding="utf-8") if _INDEX.exists() else "(empty)"
        existing_files = [p.name for p in _MEMORY_DIR.glob("*.md")]
        logger.info("[ORIENT] Existing files: %s", existing_files)

        # Phase 2: GATHER — read new data (read-only production access)
        logger.info("[GATHER] Collecting new session data")
        shop_configs = await asyncio.get_event_loop().run_in_executor(None, _gather_recent_shop_configs, db)
        interviews = await asyncio.get_event_loop().run_in_executor(None, _gather_recent_interviews, db)
        benchmarks = await asyncio.get_event_loop().run_in_executor(None, _gather_benchmark_results)
        logger.info(
            "[GATHER] Found: %d shop configs, %d interviews, %d benchmarks",
            len(shop_configs), len(interviews), len(benchmarks),
        )

        # Phase 3: CONSOLIDATE — merge into topic files
        logger.info("[CONSOLIDATE] Merging into topic files")
        shops_updated = _update_shop_profiles(shop_configs)
        interviews_merged = _update_discovery_insights(interviews)
        _update_scheduling_patterns(benchmarks)

        # Phase 4: PRUNE — keep index lean
        logger.info("[PRUNE] Checking index size")
        _rebuild_index()
        _prune_index()

        # Mark completion
        elapsed = time.time() - start_ts
        _LAST_RUN_FILE.write_text(str(time.time()), encoding="utf-8")
        _write_session_count(0)  # reset session counter

        summary = {
            "skipped": False,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 2),
            "shops_updated": shops_updated,
            "interviews_merged": interviews_merged,
            "benchmarks_processed": len(benchmarks),
            "phases": ["ORIENT", "GATHER", "CONSOLIDATE", "PRUNE"],
        }
        logger.info("=== CONSOLIDATION COMPLETE (%.2fs) ===", elapsed)
        return summary
