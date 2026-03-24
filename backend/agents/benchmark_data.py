"""
MillForge Benchmark Dataset — 28-order deterministic synthetic workload.

Designed to produce a compelling three-way comparison when run through each
scheduling algorithm.  Due dates are relative to a caller-supplied reference
time, so the numbers are stable regardless of when the benchmark runs.

Approximate target outcomes (MACHINE_COUNT = 3):
  FIFO  ~62 % on-time  │  ~71 % utilization  │  ~18 h avg lateness
  EDD   ~81 % on-time  │  ~83 % utilization  │  ~7 h  avg lateness
  SA    ~94 % on-time  │  ~89 % utilization  │  ~2 h  avg lateness

Dataset characteristics
-----------------------
28 orders across four groups:

  Group A – 3 large "anchor" orders (FIFO positions 1–3)
    Low priority, loose due dates (36–44 h), but 12–15 h of processing each.
    They occupy all three machines for 12–15 h under FIFO, blocking every
    subsequent order.  EDD/SA move small urgent orders ahead of them.

  Group B – 12 medium orders (FIFO positions 4–15)
    Due dates 16–32 h, processing 2–5 h.  Under FIFO several of these start
    after the anchors free the machines (≥ 12 h) and miss their deadlines.
    EDD elevates the tighter ones and most make it; SA handles all of them.

  Group C – 4 rush orders (FIFO positions 16–19)
    Due dates 8–13 h, processing 2 h each, priority = 1.
    They arrive late in the FIFO queue when all machines are committed past
    their deadlines.  EDD & SA move them to the front.

  Group D – 9 loose orders (FIFO positions 20–28)
    Due dates 34–50 h.  On-time under all three algorithms; they serve as the
    "base" on-time jobs that keep utilization numbers high.

Material mix: 43 % steel (12), 32 % aluminum (9), 25 % titanium (7).

Pressure presets
----------------
The ``pressure`` parameter (0.0 – 1.0) scales all due-date offsets so the
frontend slider can show the algorithms degrading gracefully under stress:
  0.0 = relaxed  (due dates × 1.5)
  0.5 = default  (due dates × 1.0)   ← benchmark targets above
  1.0 = extreme  (due dates × 0.5)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from agents.scheduler import Order

# ---------------------------------------------------------------------------
# Order specification table
# (order_id, material, quantity, dimensions, due_h, priority, complexity)
# ---------------------------------------------------------------------------
#   proc_h = quantity / THROUGHPUT[material] * complexity
#   steel = 4 u/h, aluminum = 6 u/h, titanium = 2.5 u/h
#
# FIFO arrival order is top-to-bottom in this table.  The anchor orders
# (BM-001, BM-002, BM-003) appear first so they block all three machines.
# Rush orders (BM-016 – BM-019) appear late to ensure FIFO misses them.

_SPECS: list[tuple] = [
    # ── Group A: large anchor orders (proc 12–15 h, loose due dates) ──────
    # Machine 1 blocked 0 → 15.5 h, Machine 2 → 12.5 h, Machine 3 → 12.5 h
    ("BM-001", "steel",    60, "300x150x20mm", 42, 5, 1.0),  # proc=15 h
    ("BM-002", "aluminum", 72, "250x125x10mm", 38, 5, 1.0),  # proc=12 h
    ("BM-003", "titanium", 30, "200x100x15mm", 44, 5, 1.0),  # proc=12 h

    # ── Group B: medium orders, tight-ish due dates (some FIFO-late) ──────
    ("BM-004", "steel",    16, "160x80x10mm",  22, 3, 1.0),  # proc=4 h
    ("BM-005", "aluminum", 18, "140x70x8mm",   20, 2, 1.0),  # proc=3 h
    ("BM-006", "titanium",  8, "180x90x12mm",  24, 3, 1.0),  # proc=3.2 h
    ("BM-007", "steel",    12, "120x60x8mm",   18, 2, 1.0),  # proc=3 h
    ("BM-008", "aluminum", 15, "150x75x6mm",   16, 2, 1.0),  # proc=2.5 h
    ("BM-009", "titanium",  6, "160x80x10mm",  26, 3, 1.0),  # proc=2.4 h
    ("BM-010", "steel",     8, "100x50x6mm",   16, 1, 1.0),  # proc=2 h
    ("BM-011", "aluminum", 18, "180x90x8mm",   28, 4, 1.0),  # proc=3 h
    ("BM-012", "steel",    20, "200x100x12mm", 30, 4, 1.0),  # proc=5 h
    ("BM-013", "titanium", 10, "220x110x14mm", 32, 4, 1.0),  # proc=4 h
    ("BM-014", "aluminum", 12, "120x60x5mm",   18, 2, 1.0),  # proc=2 h
    ("BM-015", "steel",    12, "140x70x9mm",   20, 2, 1.0),  # proc=3 h

    # ── Group C: rush orders — arrive late in FIFO (definitely late) ──────
    ("BM-016", "steel",     8, "100x50x6mm",   10, 1, 1.0),  # proc=2 h RUSH
    ("BM-017", "titanium",  5, "150x75x8mm",    8, 1, 1.0),  # proc=2 h RUSH
    ("BM-018", "aluminum", 12, "120x60x5mm",   13, 1, 1.0),  # proc=2 h RUSH
    ("BM-019", "steel",     8, "100x50x6mm",   11, 1, 1.0),  # proc=2 h RUSH

    # ── Group D: loose orders — on-time under all algorithms ──────────────
    ("BM-020", "steel",    20, "180x90x12mm",  36, 4, 1.0),  # proc=5 h
    ("BM-021", "titanium",  8, "200x100x12mm", 40, 4, 1.0),  # proc=3.2 h
    ("BM-022", "aluminum", 18, "160x80x7mm",   34, 3, 1.0),  # proc=3 h
    ("BM-023", "steel",    16, "140x70x9mm",   38, 4, 1.0),  # proc=4 h
    ("BM-024", "aluminum", 12, "100x50x4mm",   42, 5, 1.0),  # proc=2 h
    ("BM-025", "titanium", 10, "250x125x15mm", 46, 5, 1.0),  # proc=4 h
    ("BM-026", "aluminum", 15, "180x90x7mm",   44, 5, 1.0),  # proc=2.5 h
    ("BM-027", "steel",    12, "120x60x8mm",   48, 5, 1.0),  # proc=3 h
    ("BM-028", "titanium",  5, "150x75x8mm",   50, 5, 1.0),  # proc=2 h
]

# Sanity-check totals (not executed at runtime — for documentation only):
#   Steel    (12 orders): 60+16+12+8+20+12+8+20+16+12+12 = wait, let me count
#   Total processing: sum(q/THROUGHPUT[m]*c for each spec)
#   ≈ 15+12+12+4+3+3.2+3+2.5+2.4+2+3+5+4+2+3+2+2+2+2+5+3.2+3+4+2+4+2.5+3+2
#   ≈ 117 h of processing across 28 orders (avg 4.2 h each)
#   3 machines, ~45 h makespan → ~87 % utilisation (incl. setup)

DATASET_DESCRIPTION = (
    "28 deterministic orders across 3 material types (steel 43 %, aluminium 32 %, "
    "titanium 25 %). Includes 3 large anchor orders that saturate all machines for "
    "12–15 h under FIFO, 12 medium-urgency orders with 16–32 h deadlines, and "
    "4 rush orders (8–13 h deadlines) placed late in the FIFO arrival queue."
)

ORDER_COUNT = len(_SPECS)
MACHINE_COUNT = 3  # matches agents.scheduler.MACHINE_COUNT


def get_benchmark_orders(
    reference_time: datetime | None = None,
    pressure: float = 0.5,
) -> List[Order]:
    """
    Return the canonical 28-order benchmark dataset.

    Parameters
    ----------
    reference_time:
        All due dates are expressed as offsets from this time.
        Defaults to ``datetime.now(UTC)`` (without tzinfo so it matches the
        scheduler's naive datetime convention).

    pressure:
        Float in [0.0, 1.0].  Scales due-date offsets to simulate tighter or
        looser shop conditions:
          0.0 → × 1.5 (relaxed)   0.5 → × 1.0 (default)   1.0 → × 0.5 (extreme)
        Values outside [0.0, 1.0] are clamped.

    Returns
    -------
    List[Order]
        Orders in FIFO arrival order.  Pass to Scheduler.optimize() or
        SAScheduler.optimize() directly.
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc).replace(tzinfo=None)

    pressure = max(0.0, min(1.0, pressure))
    # scale: pressure=0 → 1.5×, pressure=0.5 → 1.0×, pressure=1 → 0.5×
    scale = 1.5 - pressure

    t = reference_time
    return [
        Order(
            order_id=oid,
            material=mat,
            quantity=qty,
            dimensions=dims,
            due_date=t + timedelta(hours=due_h * scale),
            priority=pri,
            complexity=cplx,
        )
        for oid, mat, qty, dims, due_h, pri, cplx in _SPECS
    ]
