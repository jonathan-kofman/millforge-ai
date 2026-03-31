"""
Work Order Model
==================
Bridges manufacturing planning (ProcessPlan) to shop-floor execution
(scheduling, machine assignment, QC tracking).

A WorkOrder is the primary entity that flows through the MillForge
operational pipeline:

    ManufacturingIntent
        → RoutingEngine.route()
        → ProcessPlan
        → WorkOrder
        → Scheduler (EDD / SA)
        → MachineFleet.assign_job()
        → QC pass/fail
        → COMPLETE

The status enum follows a strict finite state machine. The WorkOrder model
provides helper methods for common state queries.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

from .ontology import ManufacturingIntent, ProcessFamily, ProcessPlan


# ---------------------------------------------------------------------------
# Status Enum
# ---------------------------------------------------------------------------


class WorkOrderStatus(str, Enum):
    """
    Lifecycle states for a WorkOrder.

    Transitions (simplified):
        DRAFT → PLANNED → SCHEDULED → IN_SETUP → IN_PROGRESS
            → QC_PENDING → QC_PASSED → COMPLETE
                         → QC_FAILED → REWORK → IN_SETUP  (loop back)
        Any state → CANCELLED
        Any state → ON_HOLD → (previous state)
    """
    DRAFT = "DRAFT"
    PLANNED = "PLANNED"
    SCHEDULED = "SCHEDULED"
    IN_SETUP = "IN_SETUP"
    IN_PROGRESS = "IN_PROGRESS"
    QC_PENDING = "QC_PENDING"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    REWORK = "REWORK"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"
    ON_HOLD = "ON_HOLD"

    # ---------------------------------------------------------------------------
    # Terminal and active states
    # ---------------------------------------------------------------------------

    @property
    def is_terminal(self) -> bool:
        """True for states that cannot transition further without intervention."""
        return self in {
            WorkOrderStatus.COMPLETE,
            WorkOrderStatus.CANCELLED,
            WorkOrderStatus.QC_FAILED,
        }

    @property
    def is_active(self) -> bool:
        """True while shop-floor work is in progress."""
        return self in {
            WorkOrderStatus.IN_SETUP,
            WorkOrderStatus.IN_PROGRESS,
            WorkOrderStatus.QC_PENDING,
        }

    # ---------------------------------------------------------------------------
    # Valid transitions
    # ---------------------------------------------------------------------------

    VALID_TRANSITIONS: Dict[str, List[str]] = {}  # populated after class body

    @classmethod
    def can_transition(cls, from_status: "WorkOrderStatus", to_status: "WorkOrderStatus") -> bool:
        """Return True if transitioning from → to is a legal state change."""
        allowed = _VALID_TRANSITIONS.get(from_status, set())
        return to_status in allowed


# Legal transition map — defined outside enum to avoid enum member confusion
_VALID_TRANSITIONS: Dict[WorkOrderStatus, set] = {
    WorkOrderStatus.DRAFT: {
        WorkOrderStatus.PLANNED,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.PLANNED: {
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.SCHEDULED: {
        WorkOrderStatus.IN_SETUP,
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.IN_SETUP: {
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.IN_PROGRESS: {
        WorkOrderStatus.QC_PENDING,
        WorkOrderStatus.ON_HOLD,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.QC_PENDING: {
        WorkOrderStatus.QC_PASSED,
        WorkOrderStatus.QC_FAILED,
        WorkOrderStatus.ON_HOLD,
    },
    WorkOrderStatus.QC_PASSED: {
        WorkOrderStatus.COMPLETE,
        WorkOrderStatus.IN_SETUP,   # next step in multi-step work order
    },
    WorkOrderStatus.QC_FAILED: {
        WorkOrderStatus.REWORK,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.REWORK: {
        WorkOrderStatus.IN_SETUP,
        WorkOrderStatus.CANCELLED,
    },
    WorkOrderStatus.COMPLETE: set(),   # terminal
    WorkOrderStatus.CANCELLED: set(),  # terminal
    WorkOrderStatus.ON_HOLD: {
        WorkOrderStatus.PLANNED,
        WorkOrderStatus.SCHEDULED,
        WorkOrderStatus.IN_SETUP,
        WorkOrderStatus.IN_PROGRESS,
        WorkOrderStatus.CANCELLED,
    },
}


# ---------------------------------------------------------------------------
# Work Order Step
# ---------------------------------------------------------------------------


class WorkOrderStep(BaseModel):
    """
    A single process step within a WorkOrder. Corresponds 1:1 with
    a ProcessStepDefinition but adds execution tracking fields.

    Attributes:
        step_number:             1-based position in the work order
        process_family:          Which process this step uses
        machine_id:              Assigned machine (None until scheduled)
        status:                  Current execution status
        setup_sheet:             Generated setup sheet from adapter.generate_setup_sheet()
        estimated_time_minutes:  Pre-calculated estimate
        actual_time_minutes:     Filled in after completion
        started_at:              Wall clock time when IN_PROGRESS began
        completed_at:            Wall clock time when QC_PASSED or step completed
        quality_result:          Dict from the QC check (pass/fail details)
        operator_notes:          Free-text notes from the operator
    """
    step_number: int = Field(ge=1)
    process_family: ProcessFamily
    machine_id: Optional[str] = None
    status: WorkOrderStatus = WorkOrderStatus.DRAFT
    setup_sheet: Dict[str, Any] = Field(default_factory=dict)
    estimated_time_minutes: float = Field(ge=0.0)
    actual_time_minutes: Optional[float] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    quality_result: Optional[Dict[str, Any]] = None
    operator_notes: str = ""

    @property
    def is_complete(self) -> bool:
        return self.status in {WorkOrderStatus.QC_PASSED, WorkOrderStatus.COMPLETE}

    @property
    def elapsed_minutes(self) -> Optional[float]:
        """Actual elapsed time, or None if not yet started."""
        if self.started_at is None:
            return None
        end = self.completed_at or datetime.now(timezone.utc)
        if self.started_at.tzinfo is None:
            end = end.replace(tzinfo=None)
        return (end - self.started_at).total_seconds() / 60.0

    @property
    def efficiency_ratio(self) -> Optional[float]:
        """
        Ratio of estimated to actual time (> 1.0 = faster than estimated).
        None if actual time not yet recorded.
        """
        if self.actual_time_minutes is None or self.actual_time_minutes <= 0:
            return None
        return self.estimated_time_minutes / self.actual_time_minutes


# ---------------------------------------------------------------------------
# Work Order
# ---------------------------------------------------------------------------


class WorkOrder(BaseModel):
    """
    Top-level entity representing a shop-floor work order derived from
    a ManufacturingIntent + ProcessPlan.

    Attributes:
        work_order_id:            Unique identifier (typically UUID)
        intent:                   Original manufacturing intent
        process_plan:             The process plan used to generate this WO
        steps:                    Ordered list of work order steps
        status:                   Current work order status
        assigned_cell:            Manufacturing cell or bay assignment
        priority:                 1 (highest) — 10 (lowest); mirrors intent.priority
        created_at:               Creation timestamp (UTC)
        updated_at:               Last modification timestamp (UTC)
        due_date:                 Required completion date (mirrors intent.due_date)
        total_estimated_cost_usd: Sum of per-step estimates
        total_actual_cost_usd:    Filled in after completion
        custom_metadata:          ERP integration fields, customer references, etc.
    """
    work_order_id: str
    intent: ManufacturingIntent
    process_plan: ProcessPlan
    steps: List[WorkOrderStep]
    status: WorkOrderStatus = WorkOrderStatus.DRAFT
    assigned_cell: Optional[str] = None
    priority: int = Field(default=5, ge=1, le=10)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    due_date: Optional[datetime] = None
    total_estimated_cost_usd: Optional[float] = None
    total_actual_cost_usd: Optional[float] = None
    custom_metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def mirror_intent_fields(self) -> "WorkOrder":
        """Pull priority and due_date from intent if not explicitly set."""
        if self.priority == 5 and self.intent.priority != 5:
            self.priority = self.intent.priority
        if self.due_date is None and self.intent.due_date is not None:
            self.due_date = self.intent.due_date
        return self

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------

    def current_step(self) -> Optional[WorkOrderStep]:
        """
        Return the first step that is not yet complete (i.e. not QC_PASSED
        or COMPLETE). Returns None if all steps are done.
        """
        for step in self.steps:
            if not step.is_complete:
                return step
        return None

    def progress_percent(self) -> float:
        """
        Percentage of steps that have reached a completed state.
        Returns 0.0 if there are no steps. Returns 100.0 if all done.
        """
        if not self.steps:
            return 0.0
        completed_count = sum(1 for s in self.steps if s.is_complete)
        return round((completed_count / len(self.steps)) * 100.0, 1)

    def is_overdue(self) -> bool:
        """
        True if due_date is in the past and the work order is not
        in a terminal state.
        """
        if self.due_date is None:
            return False
        if self.status in {WorkOrderStatus.COMPLETE, WorkOrderStatus.CANCELLED}:
            return False
        now = datetime.utcnow()
        due = self.due_date
        # Normalize timezone handling
        if due.tzinfo is not None:
            now = datetime.now(timezone.utc)
        return now > due

    def can_transition_to(self, new_status: WorkOrderStatus) -> bool:
        """Check if the current status allows transitioning to new_status."""
        return WorkOrderStatus.can_transition(self.status, new_status)

    def transition_to(self, new_status: WorkOrderStatus) -> "WorkOrder":
        """
        Return a copy of this WorkOrder with status updated to new_status
        and updated_at refreshed.

        Raises:
            ValueError: if the transition is not allowed by the FSM.
        """
        if not self.can_transition_to(new_status):
            raise ValueError(
                f"Invalid work order transition: {self.status.value} → {new_status.value}"
            )
        return self.model_copy(
            update={
                "status": new_status,
                "updated_at": datetime.utcnow(),
            }
        )

    def total_estimated_time_minutes(self) -> float:
        """Sum of all step estimated times."""
        return sum(s.estimated_time_minutes for s in self.steps)

    def total_actual_time_minutes(self) -> Optional[float]:
        """Sum of all step actual times. Returns None if any step is incomplete."""
        actuals = [s.actual_time_minutes for s in self.steps]
        if any(a is None for a in actuals):
            return None
        return sum(actuals)  # type: ignore[arg-type]

    def steps_by_status(self, status: WorkOrderStatus) -> List[WorkOrderStep]:
        """Return all steps in a given status."""
        return [s for s in self.steps if s.status == status]

    @property
    def is_complete(self) -> bool:
        return self.status == WorkOrderStatus.COMPLETE

    @property
    def is_active(self) -> bool:
        return self.status.is_active

    def summary(self) -> Dict[str, Any]:
        """Lightweight summary dict for dashboard / list views."""
        return {
            "work_order_id": self.work_order_id,
            "part_id": self.intent.part_id,
            "part_name": self.intent.part_name,
            "status": self.status.value,
            "priority": self.priority,
            "progress_percent": self.progress_percent(),
            "is_overdue": self.is_overdue(),
            "step_count": len(self.steps),
            "assigned_cell": self.assigned_cell,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "total_estimated_cost_usd": self.total_estimated_cost_usd,
        }
