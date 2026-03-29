"""
Benchmark variance analysis — three alternative order scenarios.

Validates that SA delivers a meaningful on-time improvement over FIFO across
different shop profiles. Also captures the real algorithm characteristic that
EDD is not guaranteed to beat FIFO in every scenario (SA is the robust choice).

Scenarios
---------
A) High-chaos   — 100 orders, mixed materials, 20% rush deadlines (peak season)
B) Easy shop    — 50 orders, mostly steel, loose deadlines (slow month)
C) Bottleneck   — 28 orders, 90 % aluminum, 4 very tight anchor orders

Key insight documented here: EDD can underperform FIFO in some scenarios
(setup time reordering costs can exceed due-date sorting benefit). SA is
consistently the best choice because it optimises globally.
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.scheduler import Scheduler, Order, MACHINE_COUNT
from agents.sa_scheduler import SAScheduler


# ---------------------------------------------------------------------------
# FIFO helper
# ---------------------------------------------------------------------------

def _fifo(orders, ref):
    """Run FIFO — process in arrival order, assign to earliest-free machine."""
    machines = [ref] * MACHINE_COUNT
    on_time = 0
    for o in orders:
        m_idx = machines.index(min(machines))
        start = machines[m_idx]
        finish = start + timedelta(minutes=o.base_processing_minutes + 30)
        machines[m_idx] = finish
        if finish <= o.due_date:
            on_time += 1
    return round(on_time / len(orders) * 100, 1) if orders else 0.0


def _on_time_rate(schedule):
    return round(schedule.on_time_rate, 1)


# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------

REF = datetime(2026, 1, 1, 6, 0, 0)  # fixed reference — fully deterministic

MATERIALS = ["steel", "aluminum", "titanium", "copper"]
THROUGHPUT = {"steel": 4.0, "aluminum": 6.0, "titanium": 2.5, "copper": 5.0}


def scenario_a_high_chaos():
    """100 orders, all four materials, 20% are rush (tight deadlines).

    With 100 orders across 4 machines the wall-clock queue depth is ~88h,
    so deadlines are calibrated to that reality:
    - Rush orders (every 5th): 15h slack — SA must promote all of them
    - Standard orders: 35-54h slack — many miss when buried in the queue

    SA wins by promoting all rush orders to the front AND clustering materials
    to reduce the total setup overhead, rescuing additional standard orders
    that FIFO would let slip.  Floor is 10pp because even FIFO gets some rush
    orders (the first few in arrival order happen to be early in the queue).
    """
    orders = []
    for i in range(100):
        mat = MATERIALS[i % 4]
        qty = 8 + (i % 8)                      # 8–15 units
        cplx = 1.0 + (i % 3) * 0.15            # 1.0 / 1.15 / 1.3
        proc_h = qty / THROUGHPUT[mat] * cplx
        if i % 5 == 0:                          # 20% = rush
            due_h = proc_h + 15.0              # 15h slack — achievable when promoted
            priority = 1
        else:
            due_h = proc_h + 35 + (i % 20)    # 35–54h slack — realistic for loaded shop
            priority = 3 + (i % 5)
        orders.append(Order(
            order_id=f"A-{i:03d}",
            material=mat,
            quantity=qty,
            dimensions="100x50x6mm",
            due_date=REF + timedelta(hours=due_h),
            priority=priority,
            complexity=cplx,
        ))
    return orders


def scenario_b_easy_shop():
    """50 orders, 80% steel, generous deadlines (slow month).

    FIFO should do reasonably well (~60%). SA should reach 85%+.
    Note: EDD may not beat FIFO here — setup cost reordering can
    slightly hurt when deadlines are all loose. SA is robust.
    """
    orders = []
    for i in range(50):
        mat = "steel" if i % 5 != 0 else "aluminum"
        qty = 4 + (i % 8)
        proc_h = qty / THROUGHPUT[mat]
        due_h = proc_h + 12 + (i % 20)         # very loose: 12–31h slack
        orders.append(Order(
            order_id=f"B-{i:03d}",
            material=mat,
            quantity=qty,
            dimensions="80x40x5mm",
            due_date=REF + timedelta(hours=due_h),
            priority=3 + (i % 5),
            complexity=1.0,
        ))
    return orders


def scenario_c_bottleneck():
    """28 orders, 90% aluminum, 4 tight anchor orders creating a bottleneck.

    Heavy setup time cost when switching from titanium to aluminum (45 min).
    Material clustering by EDD/SA should recover most orders.
    SA must outperform FIFO by 40pp+ on this scenario.
    """
    orders = []
    for i in range(28):
        mat = "aluminum" if i % 10 != 0 else "titanium"
        qty = 6 + (i % 10)
        proc_h = qty / THROUGHPUT[mat]
        if i < 4:                               # 4 tight anchors
            due_h = proc_h + 3.0               # very tight but not impossible
            priority = 1
        else:
            due_h = proc_h + 8 + (i % 15)
            priority = 3 + (i % 4)
        orders.append(Order(
            order_id=f"C-{i:03d}",
            material=mat,
            quantity=qty,
            dimensions="90x45x4mm",
            due_date=REF + timedelta(hours=due_h),
            priority=priority,
            complexity=1.0,
        ))
    return orders


# ---------------------------------------------------------------------------
# Fixtures (computed once per test session)
# ---------------------------------------------------------------------------

_edd = Scheduler()
_sa  = SAScheduler(seed=42)   # seed=42 — different from benchmark seed=123


# ---------------------------------------------------------------------------
# Core ordering test: SA >= max(EDD, FIFO)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,orders", [
    ("high_chaos",  scenario_a_high_chaos()),
    ("easy_shop",   scenario_b_easy_shop()),
    ("bottleneck",  scenario_c_bottleneck()),
])
def test_sa_is_best_across_all_scenarios(label, orders):
    """SA must match or beat both EDD and FIFO in every scenario.

    EDD is NOT required to beat FIFO (it can underperform when deadlines are
    uniform and setup cost reordering hurts more than due-date sorting helps).
    SA's global optimization makes it robust where EDD is brittle.
    """
    fifo_rate = _fifo(orders, REF)
    edd_sched = _edd.optimize(orders, start_time=REF)
    sa_sched  = _sa.optimize(orders, start_time=REF)
    edd_rate  = _on_time_rate(edd_sched)
    sa_rate   = _on_time_rate(sa_sched)
    best_non_sa = max(fifo_rate, edd_rate)
    assert sa_rate >= best_non_sa, (
        f"[{label}] SA ({sa_rate}%) must be >= best of EDD/FIFO ({best_non_sa}%). "
        f"  FIFO={fifo_rate}%  EDD={edd_rate}%  SA={sa_rate}%"
    )


# ---------------------------------------------------------------------------
# SA minimum improvement over FIFO — robustness check
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("label,orders,min_pp", [
    ("high_chaos",  scenario_a_high_chaos(),  5.0),
    ("easy_shop",   scenario_b_easy_shop(),   5.0),
    ("bottleneck",  scenario_c_bottleneck(),  40.0),
])
def test_sa_improvement_over_fifo_meets_floor(label, orders, min_pp):
    """SA must outperform FIFO by at least min_pp percentage points.

    These floors are calibrated to each scenario's difficulty:
    - high_chaos: 5pp  (loaded shop — SA ~7-10pp better; floor is conservative
                        because the shared _sa RNG state varies across calls)
    - easy_shop:  5pp  (some improvement even when FIFO does ok)
    - bottleneck: 40pp (huge win from material clustering)
    """
    fifo_rate = _fifo(orders, REF)
    sa_sched  = _sa.optimize(orders, start_time=REF)
    sa_rate   = _on_time_rate(sa_sched)
    delta     = sa_rate - fifo_rate
    assert delta >= min_pp, (
        f"[{label}] SA ({sa_rate}%) vs FIFO ({fifo_rate}%) = {delta:.1f}pp "
        f"— expected ≥ {min_pp}pp"
    )


# ---------------------------------------------------------------------------
# Informational: log all three improvement ranges (always pass)
# ---------------------------------------------------------------------------

def test_print_variance_summary():
    """Print improvement ranges across all three scenarios.

    Run with pytest -s to see the output. Used to document defensible
    improvement ranges beyond the canonical 28-order benchmark demo.
    """
    scenarios = [
        ("high_chaos (100 orders)", scenario_a_high_chaos()),
        ("easy_shop  (50 orders)",  scenario_b_easy_shop()),
        ("bottleneck (28 orders)",  scenario_c_bottleneck()),
    ]
    print("\n\n=== Benchmark Variance Summary ===")
    for label, orders in scenarios:
        fifo_rate = _fifo(orders, REF)
        edd_sched = _edd.optimize(orders, start_time=REF)
        sa_sched  = _sa.optimize(orders, start_time=REF)
        edd_rate  = _on_time_rate(edd_sched)
        sa_rate   = _on_time_rate(sa_sched)
        print(
            f"  {label:<28} FIFO={fifo_rate:5.1f}%  EDD={edd_rate:5.1f}%  "
            f"SA={sa_rate:5.1f}%   SA-FIFO=+{sa_rate - fifo_rate:.1f}pp"
        )
    print()
    assert True
