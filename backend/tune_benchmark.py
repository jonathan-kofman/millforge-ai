"""Benchmark tuning script — run from backend/ directory."""
import importlib.util
import sys

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

sched_mod = load('agents.scheduler', 'agents/scheduler.py')
sa_mod = load('agents.sa_scheduler', 'agents/sa_scheduler.py')

Order = sched_mod.Order
Scheduler = sched_mod.Scheduler
THROUGHPUT = sched_mod.THROUGHPUT
BASE_SETUP_MINUTES = sched_mod.BASE_SETUP_MINUTES
MACHINE_COUNT = sched_mod.MACHINE_COUNT
SAScheduler = sa_mod.SAScheduler

from datetime import datetime, timedelta


def fifo_schedule(orders):
    """Matches _fifo_schedule in schedule.py — flat 30-min setup."""
    start = datetime(2025, 1, 1, 8, 0)
    machine_free = [start] * MACHINE_COUNT
    setup_hours = BASE_SETUP_MINUTES / 60
    on_time = 0
    for order in orders:
        tput = THROUGHPUT.get(order.material.lower(), 3.0)
        proc_h = (order.quantity / tput) * order.complexity
        mi = min(range(MACHINE_COUNT), key=lambda i: machine_free[i])
        proc_start = machine_free[mi] + timedelta(hours=setup_hours)
        completion = proc_start + timedelta(hours=proc_h)
        machine_free[mi] = completion
        if completion <= order.due_date:
            on_time += 1
    return round(on_time / len(orders) * 100, 1), on_time


def test_dataset(specs, label=''):
    ref = datetime(2025, 1, 1, 8, 0)
    orders = [
        Order(oid, mat, qty, dims, ref + timedelta(hours=due_h), pri, cplx)
        for oid, mat, qty, dims, due_h, pri, cplx in specs
    ]
    edd_sched = Scheduler()
    sa_sched = SAScheduler()
    fifo_r, fifo_ct = fifo_schedule(orders)
    edd_s = edd_sched.optimize(orders, start_time=ref)
    sa_s = sa_sched.optimize(orders, start_time=ref)
    edd_late = [so.order.order_id for so in edd_s.scheduled_orders if not so.on_time]
    sa_late = [so.order.order_id for so in sa_s.scheduled_orders if not so.on_time]
    n = len(orders)
    print(f'{label}: FIFO={fifo_r}% ({fifo_ct}/{n}) EDD={edd_s.on_time_rate}% ({edd_s.on_time_count}/{n}) SA={sa_s.on_time_rate}% ({sa_s.on_time_count}/{n})')
    print(f'  EDD late ({len(edd_late)}): {edd_late}')
    print(f'  SA  late ({len(sa_late)}): {sa_late}')
    return fifo_r, edd_s.on_time_rate, sa_s.on_time_rate


SPECS_ORIG = [
    # Group A: large anchor orders
    ('BM-001', 'steel',    60, '300x150x20mm', 42, 5, 1.0),
    ('BM-002', 'aluminum', 72, '250x125x10mm', 38, 5, 1.0),
    ('BM-003', 'titanium', 30, '200x100x15mm', 44, 5, 1.0),
    # Group B: medium orders
    ('BM-004', 'steel',    16, '160x80x10mm',  22, 3, 1.0),
    ('BM-005', 'aluminum', 18, '140x70x8mm',   20, 2, 1.0),
    ('BM-006', 'titanium',  8, '180x90x12mm',  24, 3, 1.0),
    ('BM-007', 'steel',    12, '120x60x8mm',   18, 2, 1.0),
    ('BM-008', 'aluminum', 15, '150x75x6mm',   16, 2, 1.0),
    ('BM-009', 'titanium',  6, '160x80x10mm',  26, 3, 1.0),
    ('BM-010', 'steel',     8, '100x50x6mm',   16, 1, 1.0),
    ('BM-011', 'aluminum', 18, '180x90x8mm',   28, 4, 1.0),
    ('BM-012', 'steel',    20, '200x100x12mm', 30, 4, 1.0),
    ('BM-013', 'titanium', 10, '220x110x14mm', 32, 4, 1.0),
    ('BM-014', 'aluminum', 12, '120x60x5mm',   18, 2, 1.0),
    ('BM-015', 'steel',    12, '140x70x9mm',   20, 2, 1.0),
    # Group C: rush orders
    ('BM-016', 'steel',     8, '100x50x6mm',   10, 1, 1.0),
    ('BM-017', 'titanium',  5, '150x75x8mm',    8, 1, 1.0),
    ('BM-018', 'aluminum', 12, '120x60x5mm',   13, 1, 1.0),
    ('BM-019', 'steel',     8, '100x50x6mm',   11, 1, 1.0),
    # Group D: loose orders
    ('BM-020', 'steel',    20, '180x90x12mm',  36, 4, 1.0),
    ('BM-021', 'titanium',  8, '200x100x12mm', 40, 4, 1.0),
    ('BM-022', 'aluminum', 18, '160x80x7mm',   34, 3, 1.0),
    ('BM-023', 'steel',    16, '140x70x9mm',   38, 4, 1.0),
    ('BM-024', 'aluminum', 12, '100x50x4mm',   42, 5, 1.0),
    ('BM-025', 'titanium', 10, '250x125x15mm', 46, 5, 1.0),
    ('BM-026', 'aluminum', 15, '180x90x7mm',   44, 5, 1.0),
    ('BM-027', 'steel',    12, '120x60x8mm',   48, 5, 1.0),
    ('BM-028', 'titanium',  5, '150x75x8mm',   50, 5, 1.0),
]

# v3: Tighten Group B and some Group D orders to add machine contention
# Target: FIFO=60-65%, EDD=78-83%, SA=92-96%
SPECS_V3 = [
    # Group A unchanged
    ('BM-001', 'steel',    60, '300x150x20mm', 42, 5, 1.0),
    ('BM-002', 'aluminum', 72, '250x125x10mm', 38, 5, 1.0),
    ('BM-003', 'titanium', 30, '200x100x15mm', 44, 5, 1.0),
    # Group B: slightly tighter due dates, a few with complexity=1.1
    ('BM-004', 'steel',    16, '160x80x10mm',  20, 3, 1.1),  # proc=4.4h, due=20h
    ('BM-005', 'aluminum', 18, '140x70x8mm',   19, 2, 1.0),  # due=19h
    ('BM-006', 'titanium',  8, '180x90x12mm',  22, 3, 1.1),  # proc=3.5h, due=22h
    ('BM-007', 'steel',    12, '120x60x8mm',   17, 2, 1.0),
    ('BM-008', 'aluminum', 15, '150x75x6mm',   15, 2, 1.0),
    ('BM-009', 'titanium',  6, '160x80x10mm',  24, 3, 1.0),
    ('BM-010', 'steel',     8, '100x50x6mm',   15, 1, 1.0),
    ('BM-011', 'aluminum', 18, '180x90x8mm',   26, 4, 1.0),
    ('BM-012', 'steel',    20, '200x100x12mm', 28, 4, 1.1),  # proc=5.5h, due=28h
    ('BM-013', 'titanium', 10, '220x110x14mm', 30, 4, 1.0),
    ('BM-014', 'aluminum', 12, '120x60x5mm',   17, 2, 1.0),
    ('BM-015', 'steel',    12, '140x70x9mm',   19, 2, 1.0),
    # Group C unchanged
    ('BM-016', 'steel',     8, '100x50x6mm',   10, 1, 1.0),
    ('BM-017', 'titanium',  5, '150x75x8mm',    8, 1, 1.0),
    ('BM-018', 'aluminum', 12, '120x60x5mm',   13, 1, 1.0),
    ('BM-019', 'steel',     8, '100x50x6mm',   11, 1, 1.0),
    # Group D: tighten first 4 orders significantly
    ('BM-020', 'steel',    20, '180x90x12mm',  28, 4, 1.0),  # proc=5h, was due=36h now 28h
    ('BM-021', 'titanium',  8, '200x100x12mm', 30, 4, 1.0),  # proc=3.2h, was 40h now 30h
    ('BM-022', 'aluminum', 18, '160x80x7mm',   26, 3, 1.0),  # proc=3h, was 34h now 26h
    ('BM-023', 'steel',    16, '140x70x9mm',   30, 4, 1.0),  # proc=4h, was 38h now 30h
    ('BM-024', 'aluminum', 12, '100x50x4mm',   36, 5, 1.0),
    ('BM-025', 'titanium', 10, '250x125x15mm', 40, 5, 1.0),
    ('BM-026', 'aluminum', 15, '180x90x7mm',   38, 5, 1.0),
    ('BM-027', 'steel',    12, '120x60x8mm',   42, 5, 1.0),
    ('BM-028', 'titanium',  5, '150x75x8mm',   44, 5, 1.0),
]

print('=== Benchmark tuning ===')
print()
test_dataset(SPECS_ORIG, 'Original')
print()
test_dataset(SPECS_V3, 'v3')

# Also test at different pressure levels for v3
print()
print('--- v3 at different pressure levels ---')

def test_pressure(specs, pressure, label):
    ref = datetime(2025, 1, 1, 8, 0)
    scale = 1.5 - pressure
    orders = [
        Order(oid, mat, qty, dims, ref + timedelta(hours=due_h * scale), pri, cplx)
        for oid, mat, qty, dims, due_h, pri, cplx in specs
    ]
    edd_sched = Scheduler()
    sa_sched = SAScheduler()
    fifo_r, _ = fifo_schedule(orders)
    edd_s = edd_sched.optimize(orders, start_time=ref)
    sa_s = sa_sched.optimize(orders, start_time=ref)
    print(f'  {label} p={pressure}: FIFO={fifo_r}% EDD={edd_s.on_time_rate}% SA={sa_s.on_time_rate}%')

test_pressure(SPECS_V3, 0.0, 'v3')
test_pressure(SPECS_V3, 0.5, 'v3')
test_pressure(SPECS_V3, 1.0, 'v3')
