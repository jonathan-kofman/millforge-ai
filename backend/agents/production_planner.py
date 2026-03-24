"""
MillForge Production Planner Agent

Accepts a natural-language demand forecast + per-material machine-hour capacity
and returns a validated weekly production plan.  Uses Claude as the reasoning
engine; falls back to a deterministic heuristic when the Anthropic key is absent
(CI-safe).

Validation loop: parses Claude's JSON, validates constraints, retries ≤ 3 times.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-20250514"
MAX_RETRIES = 3

# Throughput constants (units per machine-hour) — mirrors scheduler
THROUGHPUT: Dict[str, float] = {
    "steel":    10.0,
    "aluminum": 14.0,
    "titanium":  6.0,
    "copper":   12.0,
}

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

@dataclass
class DailyPlan:
    day: str
    material: str
    units: int
    machine_hours: float


@dataclass
class WeeklyPlan:
    week_start: str
    total_units_planned: int
    daily_plans: List[DailyPlan]
    capacity_utilization_percent: float
    bottlenecks: List[str]
    recommendations: List[str]
    validation_failures: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ProductionPlannerAgent:
    """
    Production Planner.

    Calls Claude to translate a demand signal + capacity envelope into a
    concrete 5-day production plan.  Falls back to a rule-based heuristic
    when ``ANTHROPIC_API_KEY`` is not set.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None
        if self._api_key:
            try:
                import anthropic  # noqa: PLC0415
                self._client = anthropic.Anthropic(api_key=self._api_key)
                logger.info("ProductionPlannerAgent: Claude client initialised (%s)", MODEL)
            except ImportError:
                logger.warning("anthropic package not installed; using heuristic planner")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan_week(
        self,
        demand_signal: str,
        capacity: Dict[str, float],
    ) -> WeeklyPlan:
        """
        Generate a weekly production plan.

        Args:
            demand_signal: Natural-language description of demand.
            capacity: Available machine hours per material for the week.

        Returns:
            WeeklyPlan with per-day breakdown, utilisation, and recommendations.
        """
        failures: List[str] = []
        best: Optional[WeeklyPlan] = None

        for attempt in range(MAX_RETRIES):
            if self._client is not None:
                plan = self._claude_plan(demand_signal, capacity, failures)
            else:
                plan = self._heuristic_plan(demand_signal, capacity)

            errors = self._validate(plan, capacity)

            if not errors:
                plan.validation_failures = []
                return plan

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = plan
            logger.warning(
                "Planner validation failed attempt %d: %s", attempt + 1, errors
            )

        assert best is not None
        best.validation_failures = failures
        return best

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, plan: WeeklyPlan, capacity: Dict[str, float]) -> List[str]:
        errors: List[str] = []

        if plan.total_units_planned < 0:
            errors.append("total_units_planned is negative")

        if not (0.0 <= plan.capacity_utilization_percent <= 100.0):
            errors.append(
                f"capacity_utilization_percent out of range: {plan.capacity_utilization_percent}"
            )

        if not plan.daily_plans:
            errors.append("daily_plans is empty")

        for dp in plan.daily_plans:
            if dp.units < 0:
                errors.append(f"{dp.day}/{dp.material}: negative units ({dp.units})")
            if dp.machine_hours < 0:
                errors.append(
                    f"{dp.day}/{dp.material}: negative machine_hours ({dp.machine_hours})"
                )

        # Total machine-hours per material must not exceed capacity
        usage: Dict[str, float] = {}
        for dp in plan.daily_plans:
            usage[dp.material] = usage.get(dp.material, 0.0) + dp.machine_hours
        for mat, hours in usage.items():
            cap = capacity.get(mat, 0.0)
            if hours > cap * 1.05:  # 5 % tolerance for rounding
                errors.append(
                    f"{mat}: planned {hours:.1f}h exceeds capacity {cap:.1f}h"
                )

        return errors

    # ------------------------------------------------------------------
    # Claude-backed planner
    # ------------------------------------------------------------------

    def _claude_plan(
        self,
        demand_signal: str,
        capacity: Dict[str, float],
        prior_failures: List[str],
    ) -> WeeklyPlan:
        week_start = _monday_iso()
        failure_note = (
            f"\n\nPrior validation failures to avoid:\n{chr(10).join(prior_failures)}"
            if prior_failures
            else ""
        )

        prompt = f"""You are a production scheduling AI for a precision metal mill.

Week starting: {week_start}
Available machine hours this week: {json.dumps(capacity)}
Demand signal: {demand_signal}{failure_note}

Produce a 5-day (Mon-Fri) production plan. Reply with ONLY valid JSON in this exact shape:
{{
  "week_start": "{week_start}",
  "total_units_planned": <integer>,
  "daily_plans": [
    {{"day": "Monday", "material": "<steel|aluminum|titanium|copper>", "units": <int>, "machine_hours": <float>}},
    ...
  ],
  "capacity_utilization_percent": <0-100 float>,
  "bottlenecks": ["<string>", ...],
  "recommendations": ["<string>", ...]
}}

Rules:
- Machine hours per material across all days must not exceed the capacity given.
- units = machine_hours × throughput (steel=10, aluminum=14, titanium=6, copper=12 units/hr).
- All numbers must be non-negative.
- Distribute work across all 5 days.
- capacity_utilization_percent = (total machine hours used / total capacity) × 100."""

        try:
            message = self._client.messages.create(  # type: ignore[union-attr]
                model=MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            return _parse_plan(raw)
        except Exception as exc:
            logger.error("Claude plan call failed: %s", exc, exc_info=True)
            return self._heuristic_plan(demand_signal, capacity)

    # ------------------------------------------------------------------
    # Heuristic fallback (CI-safe, deterministic)
    # ------------------------------------------------------------------

    def _heuristic_plan(
        self,
        demand_signal: str,
        capacity: Dict[str, float],
    ) -> WeeklyPlan:
        """
        Distribute capacity evenly across the 5-day week for each material.
        Prioritise materials mentioned in the demand signal.
        """
        week_start = _monday_iso()
        demand_lower = demand_signal.lower()

        # Weight materials by demand mention
        weights: Dict[str, float] = {}
        for mat in capacity:
            weights[mat] = 2.0 if mat in demand_lower else 1.0

        daily_plans: List[DailyPlan] = []
        total_units = 0
        total_hours_used = 0.0
        total_hours_cap = sum(capacity.values())

        for mat, cap_hours in capacity.items():
            if cap_hours <= 0:
                continue
            hours_per_day = cap_hours / len(DAYS)
            tput = THROUGHPUT.get(mat, 10.0)
            for day in DAYS:
                units = int(hours_per_day * tput)
                daily_plans.append(
                    DailyPlan(
                        day=day,
                        material=mat,
                        units=units,
                        machine_hours=round(hours_per_day, 2),
                    )
                )
                total_units += units
                total_hours_used += hours_per_day

        util = (total_hours_used / total_hours_cap * 100) if total_hours_cap else 0.0

        bottlenecks = [
            f"{mat}: only {cap:.0f}h available"
            for mat, cap in capacity.items()
            if cap < 20
        ]
        recommendations = [
            "Consider overtime if demand exceeds capacity",
            "Review setup-time matrix for material changeovers",
        ]

        return WeeklyPlan(
            week_start=week_start,
            total_units_planned=total_units,
            daily_plans=daily_plans,
            capacity_utilization_percent=round(util, 1),
            bottlenecks=bottlenecks,
            recommendations=recommendations,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _monday_iso() -> str:
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    return monday.isoformat()


def _parse_plan(raw: str) -> WeeklyPlan:
    """Extract JSON from Claude's reply and parse into WeeklyPlan."""
    # Strip markdown code fences if present
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw

    data = json.loads(json_str)
    daily_plans = [
        DailyPlan(
            day=dp["day"],
            material=dp["material"],
            units=int(dp["units"]),
            machine_hours=float(dp["machine_hours"]),
        )
        for dp in data.get("daily_plans", [])
    ]
    return WeeklyPlan(
        week_start=data.get("week_start", _monday_iso()),
        total_units_planned=int(data.get("total_units_planned", 0)),
        daily_plans=daily_plans,
        capacity_utilization_percent=float(data.get("capacity_utilization_percent", 0.0)),
        bottlenecks=list(data.get("bottlenecks", [])),
        recommendations=list(data.get("recommendations", [])),
    )
