"""
Tool-Aware Scheduler — post-processing wrapper around the SA optimizer.

Inserts tool-change events BETWEEN jobs (never during) so the physical
change happens at a natural boundary. Never modifies scheduler.py or
sa_scheduler.py.

Usage:
    from agents.tool_aware_scheduler import build_tool_aware_schedule

    schedule = _sa.optimize(orders, start_time)
    result = build_tool_aware_schedule(schedule, tool_agent)
    # result["scheduled_orders"] — original schedule output
    # result["tool_changes"]    — list of ToolChangeEvent dicts
    # result["tool_warnings"]   — list of warning strings
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

TOOL_CHANGE_MINUTES = 15  # estimated time for physical tool change


@dataclass
class ToolChangeEvent:
    tool_id: str
    machine_id: int
    between_jobs: tuple[str, str]  # (before_order_id, after_order_id)
    scheduled_at: datetime
    duration_minutes: float = TOOL_CHANGE_MINUTES
    reason: str = "wear_threshold"

    def to_dict(self) -> dict:
        return {
            "tool_id": self.tool_id,
            "machine_id": self.machine_id,
            "before_order_id": self.between_jobs[0],
            "after_order_id": self.between_jobs[1],
            "scheduled_at": self.scheduled_at.isoformat(),
            "duration_minutes": self.duration_minutes,
            "reason": self.reason,
        }


def build_tool_aware_schedule(
    schedule: Any,
    tool_agent: Any,
) -> Dict[str, Any]:
    """
    Post-process a Schedule object from the SA optimizer.

    Args:
        schedule: agents.scheduler.Schedule (has .scheduled_orders)
        tool_agent: ToolWearAgent instance (may have zero tools — safe)

    Returns dict with:
        scheduled_orders — original list (unchanged)
        tool_changes     — list of ToolChangeEvent dicts
        tool_warnings    — list of human-readable warning strings
    """
    tool_changes: List[ToolChangeEvent] = []
    tool_warnings: List[str] = []

    if tool_agent is None or not hasattr(schedule, "scheduled_orders"):
        return {
            "scheduled_orders": schedule.scheduled_orders if schedule else [],
            "tool_changes": [],
            "tool_warnings": [],
        }

    # Group scheduled orders by machine
    by_machine: Dict[int, List[Any]] = {}
    for order in schedule.scheduled_orders:
        mid = order.machine_id
        by_machine.setdefault(mid, []).append(order)

    for machine_id, orders in by_machine.items():
        # Sort by processing start time
        sorted_orders = sorted(orders, key=lambda o: o.processing_start)

        # Find tool(s) assigned to this machine
        machine_tools = [
            t for t in tool_agent.list_tools()
            if t.machine_id == machine_id
        ]

        for tool_state in machine_tools:
            tool_id = tool_state.tool_id
            if not tool_state.is_baseline_ready:
                continue  # still learning — no recommendation possible

            if tool_state.wear_score_ema >= 70.0:
                tool_warnings.append(
                    f"Tool {tool_id} on machine {machine_id}: "
                    f"wear score {tool_state.wear_score_ema:.0f}% ({tool_state.alert_level})"
                )

            for i, order in enumerate(sorted_orders[:-1]):
                next_order = sorted_orders[i + 1]
                job_min = getattr(order, "processing_minutes", 60.0)

                if tool_state.should_change_before_job(job_min):
                    # Insert change between this order and the next
                    change_at = order.completion_time
                    event = ToolChangeEvent(
                        tool_id=tool_id,
                        machine_id=machine_id,
                        between_jobs=(order.order_id, next_order.order_id),
                        scheduled_at=change_at,
                        reason=f"wear_{tool_state.wear_score_ema:.0f}pct",
                    )
                    tool_changes.append(event)
                    # Only one change per gap (first tool that needs it wins)
                    break

    return {
        "scheduled_orders": schedule.scheduled_orders,
        "tool_changes": [e.to_dict() for e in tool_changes],
        "tool_warnings": tool_warnings,
    }
