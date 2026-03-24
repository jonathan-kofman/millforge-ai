"""
MillForge Simulated Annealing Scheduler

Replaces the greedy EDD heuristic with a metaheuristic optimizer that
minimizes total weighted tardiness across all orders and machines.

Algorithm:
  1. Warm-start from an EDD solution (fast, good initial state)
  2. Iteratively perturb the assignment/sequence via three move types:
       - Swap: exchange two jobs on the same machine
       - Transfer: move a job from one machine to another
       - Cross-swap: exchange one job from each of two different machines
  3. Accept improvements always; accept worsening moves with probability
     exp(-ΔE / T) where T cools geometrically (simulated annealing)
  4. Return the best solution seen during the entire search

Objective (energy): Σ_i  w_i · max(0, C_i − d_i)
  where w_i = (11 − priority_i)  so urgent orders are penalised more heavily.

Complexity: O(max_iterations) with a small constant per iteration.
For 8–50 orders / 3 machines this runs in < 200 ms.
"""

import copy
import math
import random
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Optional

from .scheduler import (
    Order, Schedule, ScheduledOrder, Scheduler,
    SETUP_MATRIX, BASE_SETUP_MINUTES,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SA hyper-parameters (tuned for 5–50 order instances, 2–4 machines)
# ---------------------------------------------------------------------------
DEFAULT_MAX_ITER   = 12_000
DEFAULT_INIT_TEMP  = 800.0   # energy units ≈ priority-weighted tardiness hours
DEFAULT_COOL_RATE  = 0.9992  # temp halves every ~830 iterations
MIN_TEMP           = 0.01


# ---------------------------------------------------------------------------
# Internal state type: List[List[order_id]]  (one list per machine)
# ---------------------------------------------------------------------------
State = List[List[str]]


class SAScheduler:
    """
    Simulated Annealing production scheduler.

    Implements the same interface as `Scheduler` so it can be used as a
    drop-in replacement anywhere in the codebase.

    Extension points:
    - Swap the energy function for a multi-objective formulation (cost + carbon)
    - Add reheating for escaping local optima on large instances
    - Seed with domain knowledge (group same-material jobs on same machine)
    """

    def __init__(
        self,
        machine_count: int = 3,
        max_iterations: int = DEFAULT_MAX_ITER,
        initial_temp: float = DEFAULT_INIT_TEMP,
        cooling_rate: float = DEFAULT_COOL_RATE,
        seed: Optional[int] = None,
    ):
        self.machine_count = machine_count
        self.max_iterations = max_iterations
        self.initial_temp = initial_temp
        self.cooling_rate = cooling_rate
        self._rng = random.Random(seed)  # isolated RNG — doesn't affect global state
        self._edd = Scheduler(machine_count)
        logger.info(
            f"SAScheduler initialized: machines={machine_count} "
            f"max_iter={max_iterations} T0={initial_temp} α={cooling_rate}"
        )

    # ------------------------------------------------------------------
    # Public interface (identical to Scheduler)
    # ------------------------------------------------------------------

    def optimize(self, orders: List[Order], start_time: Optional[datetime] = None) -> Schedule:
        """
        Optimize production schedule via simulated annealing.

        Args:
            orders: List of Order objects to schedule.
            start_time: When production can begin (defaults to now UTC).

        Returns:
            A Schedule object — same structure as Scheduler.optimize().
        """
        if not orders:
            return Schedule(
                scheduled_orders=[],
                total_orders=0,
                on_time_count=0,
                makespan_hours=0.0,
                utilization_percent=0.0,
            )

        if start_time is None:
            start_time = datetime.now(timezone.utc).replace(tzinfo=None)

        orders_by_id: Dict[str, Order] = {o.order_id: o for o in orders}

        # --- Step 1: warm-start from EDD ---
        edd_schedule = self._edd.optimize(orders, start_time)
        state = self._schedule_to_state(edd_schedule)
        best_state = copy.deepcopy(state)
        current_energy = self._energy(state, orders_by_id, start_time)
        best_energy = current_energy

        # --- Step 2: SA main loop ---
        temp = self.initial_temp
        accepted = 0

        for iteration in range(self.max_iterations):
            if temp < MIN_TEMP:
                break

            neighbor = self._neighbor(state, orders_by_id)
            if neighbor is None:
                break

            n_energy = self._energy(neighbor, orders_by_id, start_time)
            delta = n_energy - current_energy

            if delta < 0 or self._rng.random() < math.exp(-delta / temp):
                state = neighbor
                current_energy = n_energy
                accepted += 1
                if current_energy < best_energy:
                    best_state = copy.deepcopy(state)
                    best_energy = current_energy

            temp *= self.cooling_rate

        accept_rate = accepted / self.max_iterations * 100
        logger.info(
            f"SA finished: energy {self._energy(self._schedule_to_state(edd_schedule), orders_by_id, start_time):.2f}"
            f" → {best_energy:.2f} | accept_rate={accept_rate:.1f}%"
        )

        return self._state_to_schedule(best_state, orders_by_id, start_time)

    def estimate_lead_time(self, order: Order, current_queue: List[Order]) -> float:
        """Estimate lead time hours for a new order — same as EDD agent."""
        all_orders = current_queue + [order]
        schedule = self.optimize(all_orders)
        for s in schedule.scheduled_orders:
            if s.order.order_id == order.order_id:
                now = datetime.now(timezone.utc).replace(tzinfo=None)
                return max(0.0, (s.completion_time - now).total_seconds() / 3600)
        return 0.0

    # ------------------------------------------------------------------
    # Energy function
    # ------------------------------------------------------------------

    def _energy(self, state: State, orders_by_id: Dict[str, Order], start_time: datetime) -> float:
        """
        Compute total weighted tardiness for a given state.

        Lower is better. Units: priority-weighted tardiness hours.
        """
        completions = self._completion_times(state, orders_by_id, start_time)
        total = 0.0
        for oid, ct in completions.items():
            order = orders_by_id[oid]
            tardiness_h = max(0.0, (ct - order.due_date).total_seconds() / 3600)
            weight = max(1, 11 - order.priority)   # priority 1 → weight 10
            total += weight * tardiness_h
        return total

    # ------------------------------------------------------------------
    # Completion time simulation
    # ------------------------------------------------------------------

    def _completion_times(
        self, state: State, orders_by_id: Dict[str, Order], start_time: datetime
    ) -> Dict[str, datetime]:
        """Simulate execution of the state and return {order_id: completion_time}."""
        result: Dict[str, datetime] = {}
        for sequence in state:
            t = start_time
            last_mat: Optional[str] = None
            for oid in sequence:
                order = orders_by_id[oid]
                setup_m = self._setup(last_mat, order.material)
                proc_m = order.base_processing_minutes
                t = t + timedelta(minutes=setup_m + proc_m)
                result[oid] = t
                last_mat = order.material
        return result

    def _setup(self, from_mat: Optional[str], to_mat: str) -> int:
        if from_mat is None:
            return BASE_SETUP_MINUTES
        return SETUP_MATRIX.get((from_mat.lower(), to_mat.lower()), BASE_SETUP_MINUTES)

    # ------------------------------------------------------------------
    # State ↔ Schedule conversion
    # ------------------------------------------------------------------

    def _schedule_to_state(self, schedule: Schedule) -> State:
        """Convert a Schedule object to an SA state (list-of-lists of order_ids)."""
        state: State = [[] for _ in range(self.machine_count)]
        # Sort by processing_start so sequence is correctly reconstructed
        sorted_items = sorted(schedule.scheduled_orders, key=lambda s: s.processing_start)
        for s in sorted_items:
            idx = s.machine_id - 1
            if 0 <= idx < self.machine_count:
                state[idx].append(s.order.order_id)
        return state

    def _state_to_schedule(
        self,
        state: State,
        orders_by_id: Dict[str, Order],
        start_time: datetime,
    ) -> Schedule:
        """Convert an SA state back to a full Schedule object."""
        scheduled: List[ScheduledOrder] = []
        total_busy = 0.0
        machine_end_times = []

        for machine_idx, sequence in enumerate(state):
            t = start_time
            last_mat: Optional[str] = None
            for oid in sequence:
                order = orders_by_id[oid]
                setup_m = self._setup(last_mat, order.material)
                proc_m = order.base_processing_minutes
                setup_start = t
                proc_start = t + timedelta(minutes=setup_m)
                completion = proc_start + timedelta(minutes=proc_m)
                scheduled.append(ScheduledOrder(
                    order=order,
                    machine_id=machine_idx + 1,
                    setup_start=setup_start,
                    processing_start=proc_start,
                    completion_time=completion,
                    setup_minutes=setup_m,
                    processing_minutes=proc_m,
                ))
                t = completion
                last_mat = order.material
                total_busy += setup_m + proc_m
            machine_end_times.append(t)

        makespan_end = max(machine_end_times) if machine_end_times else start_time
        makespan_h = (makespan_end - start_time).total_seconds() / 3600
        avail_m = makespan_h * 60 * self.machine_count
        util = (total_busy / avail_m * 100) if avail_m > 0 else 0.0
        on_time = sum(1 for s in scheduled if s.on_time)

        return Schedule(
            scheduled_orders=scheduled,
            total_orders=len(scheduled),
            on_time_count=on_time,
            makespan_hours=makespan_h,
            utilization_percent=util,
        )

    # ------------------------------------------------------------------
    # Neighborhood moves
    # ------------------------------------------------------------------

    def _neighbor(self, state: State, orders_by_id: Dict[str, Order]) -> Optional[State]:
        """
        Generate a neighboring state via one of three random moves:
          1. SWAP   – exchange positions of two jobs on the same machine
          2. TRANSFER – move a job to a different machine
          3. CROSS  – exchange one job from each of two different machines
        """
        move = self._rng.choice(["swap", "transfer", "cross"])

        new_state = [list(seq) for seq in state]  # shallow copy of sequences

        non_empty = [k for k, seq in enumerate(new_state) if seq]
        if not non_empty:
            return None

        if move == "swap":
            # Pick a machine with ≥ 2 jobs
            eligible = [k for k in non_empty if len(new_state[k]) >= 2]
            if not eligible:
                return self._neighbor_transfer(new_state, non_empty)
            k = self._rng.choice(eligible)
            i, j = self._rng.sample(range(len(new_state[k])), 2)
            new_state[k][i], new_state[k][j] = new_state[k][j], new_state[k][i]

        elif move == "transfer":
            new_state = self._neighbor_transfer(new_state, non_empty)  # type: ignore
            if new_state is None:
                return None

        else:  # cross
            if len(non_empty) < 2:
                return self._neighbor_transfer(new_state, non_empty)
            k1, k2 = self._rng.sample(non_empty, 2)
            i1 = self._rng.randrange(len(new_state[k1]))
            i2 = self._rng.randrange(len(new_state[k2]))
            new_state[k1][i1], new_state[k2][i2] = new_state[k2][i2], new_state[k1][i1]

        return new_state

    def _neighbor_transfer(self, state: State, non_empty: List[int]) -> Optional[State]:
        """Move one job from a random non-empty machine to any other machine."""
        src = self._rng.choice(non_empty)
        targets = [k for k in range(self.machine_count) if k != src]
        if not targets:
            return None
        dst = self._rng.choice(targets)
        pos = self._rng.randrange(len(state[src]))
        job = state[src].pop(pos)
        insert_pos = self._rng.randint(0, len(state[dst]))
        state[dst].insert(insert_pos, job)
        return state
