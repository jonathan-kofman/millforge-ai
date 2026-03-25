"""
MillForge Production Scheduler Agent

Implements an Earliest Due Date (EDD) algorithm with sequence-dependent
setup times and machine capacity constraints. This is the core POC component
demonstrating lead time compression through intelligent scheduling.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Setup-time matrix (minutes) for material changeovers.
# Keys are (from_material, to_material). Missing pairs default to BASE_SETUP.
# ---------------------------------------------------------------------------
BASE_SETUP_MINUTES = 30

SETUP_MATRIX: Dict[tuple, int] = {
    ("steel", "aluminum"): 60,
    ("aluminum", "steel"): 75,
    ("steel", "titanium"): 90,
    ("titanium", "steel"): 90,
    ("aluminum", "titanium"): 45,
    ("titanium", "aluminum"): 45,
    ("steel", "steel"): 15,
    ("aluminum", "aluminum"): 15,
    ("titanium", "titanium"): 20,
    ("steel", "copper"): 50,
    ("copper", "steel"): 50,
    ("aluminum", "copper"): 35,
    ("copper", "aluminum"): 35,
    ("copper", "copper"): 15,
}

# Machine throughput: units per hour by material
THROUGHPUT: Dict[str, float] = {
    "steel": 4.0,
    "aluminum": 6.0,
    "titanium": 2.5,
    "copper": 5.0,
}

# Number of available machines
MACHINE_COUNT = 3


@dataclass
class Order:
    """Represents a single production order."""
    order_id: str
    material: str
    quantity: int           # units
    dimensions: str         # e.g. "100x200x5mm"
    due_date: datetime
    priority: int = 5       # 1 (highest) – 10 (lowest)
    complexity: float = 1.0 # multiplier on base processing time

    @property
    def base_processing_minutes(self) -> float:
        """Estimated processing time in minutes based on material and quantity."""
        throughput = THROUGHPUT.get(self.material.lower(), 3.0)
        # hours = quantity / throughput, scaled by complexity
        hours = (self.quantity / throughput) * self.complexity
        return hours * 60


@dataclass
class ScheduledOrder:
    """An order with assigned start/end times on a specific machine."""
    order: Order
    machine_id: int
    setup_start: datetime
    processing_start: datetime
    completion_time: datetime
    setup_minutes: int
    processing_minutes: float

    @property
    def total_minutes(self) -> float:
        return self.setup_minutes + self.processing_minutes

    @property
    def on_time(self) -> bool:
        return self.completion_time <= self.order.due_date

    @property
    def lateness_hours(self) -> float:
        delta = self.completion_time - self.order.due_date
        return delta.total_seconds() / 3600

    def to_dict(self) -> dict:
        return {
            "order_id": self.order.order_id,
            "machine_id": self.machine_id,
            "material": self.order.material,
            "quantity": self.order.quantity,
            "setup_start": self.setup_start.isoformat(),
            "processing_start": self.processing_start.isoformat(),
            "completion_time": self.completion_time.isoformat(),
            "setup_minutes": self.setup_minutes,
            "processing_minutes": round(self.processing_minutes, 1),
            "on_time": self.on_time,
            "lateness_hours": round(self.lateness_hours, 2),
            "due_date": self.order.due_date.isoformat(),
        }


@dataclass
class Schedule:
    """The full production schedule output."""
    scheduled_orders: List[ScheduledOrder]
    total_orders: int
    on_time_count: int
    makespan_hours: float
    utilization_percent: float
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    validation_failures: List[str] = field(default_factory=list)

    @property
    def on_time_rate(self) -> float:
        if self.total_orders == 0:
            return 100.0
        return round((self.on_time_count / self.total_orders) * 100, 1)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at.isoformat(),
            "summary": {
                "total_orders": self.total_orders,
                "on_time_count": self.on_time_count,
                "on_time_rate_percent": self.on_time_rate,
                "makespan_hours": round(self.makespan_hours, 2),
                "utilization_percent": round(self.utilization_percent, 1),
            },
            "schedule": [s.to_dict() for s in self.scheduled_orders],
        }


class Scheduler:
    """
    Production Scheduler Agent.

    Algorithm: Modified Earliest Due Date (EDD) with sequence-dependent
    setup times and parallel machine assignment using a greedy
    "earliest available machine" heuristic.

    Validation loop: output is validated after each attempt; retried up to
    MAX_RETRIES times before returning the best result with validation_failures.

    Future extension points:
    - Replace greedy machine assignment with ILP or genetic algorithm
    - Integrate real-time machine sensor data
    - Add AI-driven priority scoring via LLM
    """

    MAX_RETRIES = 3

    def __init__(self, machine_count: int = MACHINE_COUNT):
        self.machine_count = machine_count
        logger.info(f"Scheduler initialized with {machine_count} machines")

    def optimize(self, orders: List[Order], start_time: Optional[datetime] = None) -> Schedule:
        """
        Optimize the production schedule for the given orders.

        Args:
            orders: List of Order objects to schedule.
            start_time: When production can begin (defaults to now).

        Returns:
            A Schedule object with assigned machine times.
        """
        if not orders:
            return Schedule(
                scheduled_orders=[],
                total_orders=0,
                on_time_count=0,
                makespan_hours=0.0,
                utilization_percent=0.0,
            )

        failures: List[str] = []
        best: Optional[Schedule] = None

        for attempt in range(self.MAX_RETRIES):
            schedule = self._do_optimize(orders, start_time)
            errors = self._validate_schedule(schedule, orders)

            if not errors:
                schedule.validation_failures = []
                return schedule

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = schedule
            logger.warning("Schedule validation failed attempt %d: %s", attempt + 1, errors)

        assert best is not None
        best.validation_failures = failures
        return best

    def _validate_schedule(self, schedule: Schedule, orders: List[Order]) -> List[str]:
        """Return a list of constraint violations (empty = valid)."""
        errors: List[str] = []

        if schedule.total_orders != len(orders):
            errors.append(
                f"total_orders mismatch: expected {len(orders)}, got {schedule.total_orders}"
            )

        if schedule.makespan_hours < 0:
            errors.append(f"makespan_hours is negative: {schedule.makespan_hours}")

        if not (0.0 <= schedule.utilization_percent <= 100.0):
            errors.append(
                f"utilization_percent out of range: {schedule.utilization_percent}"
            )

        order_ids = {o.order_id for o in orders}
        scheduled_ids = {s.order.order_id for s in schedule.scheduled_orders}
        missing = order_ids - scheduled_ids
        if missing:
            errors.append(f"orders not scheduled: {missing}")

        for s in schedule.scheduled_orders:
            if s.processing_start < s.setup_start:
                errors.append(
                    f"{s.order.order_id}: processing_start before setup_start"
                )
            if s.completion_time < s.processing_start:
                errors.append(
                    f"{s.order.order_id}: completion_time before processing_start"
                )

        return errors

    def _do_optimize(self, orders: List[Order], start_time: Optional[datetime] = None) -> Schedule:
        """Core EDD scheduling algorithm."""
        if start_time is None:
            start_time = datetime.now(timezone.utc).replace(tzinfo=None)

        # Step 1: Sort by EDD, breaking ties by priority then complexity
        sorted_orders = sorted(
            orders,
            key=lambda o: (o.due_date, o.priority, o.complexity)
        )

        # Step 2: Track machine state: (current_time, last_material)
        machine_state: List[Dict] = [
            {"available_at": start_time, "last_material": None}
            for _ in range(self.machine_count)
        ]

        scheduled: List[ScheduledOrder] = []
        total_busy_minutes = 0.0

        for order in sorted_orders:
            # Find the machine that can start this order earliest
            best_machine_idx, best_start = self._find_best_machine(
                order, machine_state
            )

            machine = machine_state[best_machine_idx]
            setup_mins = self._get_setup_time(machine["last_material"], order.material)
            proc_mins = order.base_processing_minutes

            setup_start = best_start
            proc_start = setup_start + timedelta(minutes=setup_mins)
            completion = proc_start + timedelta(minutes=proc_mins)

            scheduled_order = ScheduledOrder(
                order=order,
                machine_id=best_machine_idx + 1,
                setup_start=setup_start,
                processing_start=proc_start,
                completion_time=completion,
                setup_minutes=setup_mins,
                processing_minutes=proc_mins,
            )
            scheduled.append(scheduled_order)

            # Update machine state
            machine_state[best_machine_idx]["available_at"] = completion
            machine_state[best_machine_idx]["last_material"] = order.material

            total_busy_minutes += setup_mins + proc_mins

        # Compute metrics
        all_end_times = [machine_state[i]["available_at"] for i in range(self.machine_count)]
        makespan_end = max(all_end_times)
        makespan_hours = (makespan_end - start_time).total_seconds() / 3600

        available_machine_minutes = makespan_hours * 60 * self.machine_count
        utilization = (total_busy_minutes / available_machine_minutes * 100) if available_machine_minutes > 0 else 0.0

        on_time_count = sum(1 for s in scheduled if s.on_time)

        logger.info(
            f"Scheduled {len(scheduled)} orders | "
            f"On-time: {on_time_count}/{len(scheduled)} | "
            f"Makespan: {makespan_hours:.1f}h | "
            f"Utilization: {utilization:.1f}%"
        )

        return Schedule(
            scheduled_orders=scheduled,
            total_orders=len(scheduled),
            on_time_count=on_time_count,
            makespan_hours=makespan_hours,
            utilization_percent=utilization,
        )

    def estimate_lead_time(self, order: Order, current_queue: List[Order]) -> float:
        """
        Estimate lead time in hours for a new order given the current queue.

        Used by the /api/quote endpoint to give realistic lead time estimates.
        """
        all_orders = current_queue + [order]
        schedule = self.optimize(all_orders)

        # Find our order in the schedule
        for scheduled in schedule.scheduled_orders:
            if scheduled.order.order_id == order.order_id:
                delta = scheduled.completion_time - datetime.now(timezone.utc).replace(tzinfo=None)
                return max(0.0, delta.total_seconds() / 3600)

        return 0.0

    def _find_best_machine(
        self, order: Order, machine_state: List[Dict]
    ) -> tuple:
        """Return (machine_index, earliest_start) for the best machine."""
        best_idx = 0
        best_start = None

        for idx, machine in enumerate(machine_state):
            start = machine["available_at"]
            if best_start is None or start < best_start:
                best_start = start
                best_idx = idx

        return best_idx, best_start

    def _get_setup_time(self, from_material: Optional[str], to_material: str) -> int:
        """Return setup time in minutes for a material changeover."""
        if from_material is None:
            return BASE_SETUP_MINUTES  # initial setup

        key = (from_material.lower(), to_material.lower())
        return SETUP_MATRIX.get(key, BASE_SETUP_MINUTES)


# ---------------------------------------------------------------------------
# Mock order data for demos and testing
# ---------------------------------------------------------------------------
def get_mock_orders() -> List[Order]:
    """Return a representative set of mock orders for demos."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return [
        Order("ORD-001", "steel",    500, "200x100x10mm", now + timedelta(hours=48), priority=2),
        Order("ORD-002", "aluminum", 200, "150x75x5mm",   now + timedelta(hours=24), priority=1),
        Order("ORD-003", "titanium",  50, "300x200x15mm", now + timedelta(hours=72), priority=3),
        Order("ORD-004", "steel",    750, "100x50x8mm",   now + timedelta(hours=36), priority=2),
        Order("ORD-005", "aluminum", 300, "250x125x6mm",  now + timedelta(hours=60), priority=4),
        Order("ORD-006", "copper",   100, "80x40x3mm",    now + timedelta(hours=20), priority=1),
        Order("ORD-007", "steel",    400, "180x90x12mm",  now + timedelta(hours=54), priority=3, complexity=1.5),
        Order("ORD-008", "titanium",  25, "400x300x20mm", now + timedelta(hours=96), priority=5, complexity=2.0),
    ]
