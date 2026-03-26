"""
Exception queue — unified view of everything that needs a human decision.

This is the lights-out handoff interface: software handles routine production;
when it can't, an exception lands here. Humans only touch the exception queue.

Exception sources (aggregated in priority order):
  1. machine_fault      — MachineStateLog rows where to_state = FAULT
  2. held_order         — OrderRecord rows with status = "held" (blocked by anomaly gate)
  3. quality_failure    — InspectionRecord rows where passed = False (no rework order yet)
  4. low_inventory      — Materials below reorder threshold (from InventoryAgent)
  5. maintenance_risk   — Machines whose predictive maintenance risk_level = "urgent"

Each exception carries:
  - id           unique string key (<source>-<pk>)
  - source       one of the four types above
  - severity     critical | warning | info
  - title        one-line human description
  - detail       actionable detail text
  - order_id     if tied to a specific order (nullable)
  - machine_id   if tied to a specific machine (nullable)
  - occurred_at  ISO timestamp
  - resolved     bool (default False; set via PATCH /api/exceptions/{id}/resolve)

Resolution is stored in an in-process dict (survives for the server lifetime).
For a real deployment, persist to a DB table. The architecture makes that easy —
swap `_resolutions` for a DB query without touching the aggregator logic.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-process resolution store (keyed by exception_id → resolved_at ISO string)
# ---------------------------------------------------------------------------
_resolutions: Dict[str, str] = {}


def _is_resolved(exc_id: str) -> bool:
    return exc_id in _resolutions


def mark_resolved(exc_id: str) -> bool:
    """Mark an exception as resolved. Returns True if it existed, False if unknown."""
    if exc_id in _resolutions:
        return True
    _resolutions[exc_id] = datetime.now(timezone.utc).isoformat()
    logger.info("Exception resolved: %s", exc_id)
    return True


def mark_unresolved(exc_id: str) -> bool:
    """Reopen a previously resolved exception. Returns True if it was resolved."""
    if exc_id not in _resolutions:
        return False
    del _resolutions[exc_id]
    logger.info("Exception re-opened: %s", exc_id)
    return True


# ---------------------------------------------------------------------------
# Exception item dataclass
# ---------------------------------------------------------------------------

class ExceptionItem:
    """Single actionable exception."""

    __slots__ = (
        "exc_id", "source", "severity", "title", "detail",
        "order_id", "machine_id", "occurred_at", "resolved", "resolved_at",
    )

    def __init__(
        self,
        *,
        exc_id: str,
        source: str,
        severity: str,
        title: str,
        detail: str,
        order_id: Optional[str] = None,
        machine_id: Optional[int] = None,
        occurred_at: datetime,
    ) -> None:
        self.exc_id = exc_id
        self.source = source
        self.severity = severity
        self.title = title
        self.detail = detail
        self.order_id = order_id
        self.machine_id = machine_id
        self.occurred_at = occurred_at
        self.resolved = _is_resolved(exc_id)
        self.resolved_at: Optional[str] = _resolutions.get(exc_id)

    def to_dict(self) -> dict:
        return {
            "id": self.exc_id,
            "source": self.source,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "order_id": self.order_id,
            "machine_id": self.machine_id,
            "occurred_at": self.occurred_at.isoformat(),
            "resolved": self.resolved,
            "resolved_at": self.resolved_at,
        }


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------

_SEVERITY_RANK = {"critical": 0, "warning": 1, "info": 2}


class ExceptionQueueAgent:
    """
    Aggregates exceptions from all sources and returns a priority-sorted list.

    Usage::

        agent = ExceptionQueueAgent(inventory_agent)
        items = agent.gather(db, include_resolved=False)
    """

    def __init__(self, inventory_agent=None) -> None:
        self._inventory = inventory_agent

    def gather(
        self,
        db,
        *,
        include_resolved: bool = False,
        source_filter: Optional[str] = None,
        severity_filter: Optional[str] = None,
        limit: int = 200,
    ) -> List[ExceptionItem]:
        """
        Aggregate exceptions from all sources.

        Parameters
        ----------
        db:               SQLAlchemy session
        include_resolved: include already-resolved exceptions (default False)
        source_filter:    restrict to one source type (machine_fault | held_order |
                          quality_failure | low_inventory | maintenance_risk)
        severity_filter:  restrict to one severity (critical | warning | info)
        limit:            max items to return

        Returns
        -------
        List[ExceptionItem] sorted by (severity, occurred_at desc)
        """
        collectors = [
            self._machine_faults,
            self._held_orders,
            self._quality_failures,
            self._low_inventory,
            self._maintenance_risk,
        ]

        items: List[ExceptionItem] = []
        for collect in collectors:
            try:
                items.extend(collect(db))
            except Exception as exc:
                logger.warning("Exception collector %s failed: %s", collect.__name__, exc)

        if not include_resolved:
            items = [i for i in items if not i.resolved]
        if source_filter:
            items = [i for i in items if i.source == source_filter]
        if severity_filter:
            items = [i for i in items if i.severity == severity_filter]

        items.sort(key=lambda i: (
            _SEVERITY_RANK.get(i.severity, 99),
            -(i.occurred_at.timestamp() if i.occurred_at else 0),
        ))

        return items[:limit]

    # ------------------------------------------------------------------
    # Source collectors
    # ------------------------------------------------------------------

    def _machine_faults(self, db) -> List[ExceptionItem]:
        """Machines that transitioned to FAULT and haven't been reset."""
        from db_models import MachineStateLog

        fault_rows = (
            db.query(MachineStateLog)
            .filter(MachineStateLog.to_state == "FAULT")
            .order_by(MachineStateLog.occurred_at.desc())
            .limit(50)
            .all()
        )

        # Exclude machines that later transitioned out of FAULT
        resolved_machines: set[int] = set()
        post_fault = (
            db.query(MachineStateLog.machine_id)
            .filter(
                MachineStateLog.from_state == "FAULT",
                MachineStateLog.to_state == "IDLE",
            )
            .all()
        )
        for (mid,) in post_fault:
            resolved_machines.add(mid)

        items = []
        seen_machines: set[int] = set()
        for row in fault_rows:
            if row.machine_id in resolved_machines:
                continue
            if row.machine_id in seen_machines:
                continue
            seen_machines.add(row.machine_id)

            exc_id = f"machine_fault-{row.id}"
            occurred_at = row.occurred_at
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)

            items.append(ExceptionItem(
                exc_id=exc_id,
                source="machine_fault",
                severity="critical",
                title=f"Machine {row.machine_id} in FAULT state",
                detail=(
                    f"Machine {row.machine_id} faulted"
                    + (f" during job {row.job_id}" if row.job_id else "")
                    + ". Operator must inspect and call reset_fault() to return to IDLE."
                ),
                machine_id=row.machine_id,
                order_id=row.job_id,
                occurred_at=occurred_at,
            ))

        return items

    def _held_orders(self, db) -> List[ExceptionItem]:
        """Orders with status='held' — blocked by the anomaly gate."""
        from db_models import OrderRecord

        held = (
            db.query(OrderRecord)
            .filter(OrderRecord.status == "held")
            .order_by(OrderRecord.created_at.desc())
            .limit(100)
            .all()
        )

        items = []
        for row in held:
            exc_id = f"held_order-{row.order_id}"
            occurred_at = row.updated_at or row.created_at
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)

            items.append(ExceptionItem(
                exc_id=exc_id,
                source="held_order",
                severity="critical",
                title=f"Order {row.order_id} held by anomaly gate",
                detail=(
                    f"Order {row.order_id} ({row.material}, qty {row.quantity}) "
                    f"was blocked before scheduling due to a critical anomaly "
                    f"(duplicate ID or impossible deadline). "
                    f"Review and either correct the order or release it manually."
                ),
                order_id=row.order_id,
                occurred_at=occurred_at,
            ))

        return items

    def _quality_failures(self, db) -> List[ExceptionItem]:
        """Inspections that failed and don't yet have a rework order."""
        from db_models import InspectionRecord, OrderRecord
        import json

        failed = (
            db.query(InspectionRecord)
            .filter(InspectionRecord.passed == False)  # noqa: E712
            .order_by(InspectionRecord.created_at.desc())
            .limit(100)
            .all()
        )

        # Find order_ids that already have a rework order (status = rework or order_id starts with RW-)
        rework_ids: set[str] = set()
        rw_orders = db.query(OrderRecord.order_id).filter(
            OrderRecord.order_id.like("RW-%")
        ).all()
        for (oid,) in rw_orders:
            # RW-{original_id} → strip prefix to get original
            original = oid[3:]
            rework_ids.add(original)

        items = []
        for row in failed:
            order_id = row.order_id_str
            if order_id and order_id in rework_ids:
                continue  # rework already dispatched

            exc_id = f"quality_failure-{row.id}"
            occurred_at = row.created_at
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=timezone.utc)

            try:
                defects = json.loads(row.defects_json) if row.defects_json else []
            except Exception:
                defects = []

            defect_summary = ", ".join(defects[:3]) if defects else "unspecified defects"
            severity = "critical" if row.confidence > 0.8 else "warning"

            items.append(ExceptionItem(
                exc_id=exc_id,
                source="quality_failure",
                severity=severity,
                title=f"Quality failure on order {order_id or 'unknown'}",
                detail=(
                    f"Inspection {row.id} failed (confidence {row.confidence:.0%}): "
                    f"{defect_summary}. "
                    f"Recommendation: {row.recommendation}. "
                    f"Submit to POST /api/schedule/rework to dispatch rework order."
                ),
                order_id=order_id,
                occurred_at=occurred_at,
            ))

        return items

    def _low_inventory(self, db) -> List[ExceptionItem]:
        """Materials below reorder threshold."""
        if self._inventory is None:
            return []

        try:
            status = self._inventory.check_reorder_points()
        except Exception as exc:
            logger.warning("Inventory check failed: %s", exc)
            return []

        items = []
        for material in status.items_below_reorder:
            exc_id = f"low_inventory-{material}"
            detail_item = status.stock.get(material)

            current = detail_item.current_stock_kg if detail_item else 0.0
            reorder = detail_item.reorder_point_kg if detail_item else 0.0
            severity = "critical" if current < reorder * 0.5 else "warning"

            items.append(ExceptionItem(
                exc_id=exc_id,
                source="low_inventory",
                severity=severity,
                title=f"Low stock: {material}",
                detail=(
                    f"{material.capitalize()} stock at {current:.0f} kg "
                    f"(reorder point: {reorder:.0f} kg). "
                    f"POST /api/inventory/reorder to generate a purchase order."
                ),
                occurred_at=datetime.now(timezone.utc),
            ))

        return items

    def _maintenance_risk(self, db) -> List[ExceptionItem]:
        """Machines whose predictive maintenance signal is 'urgent'."""
        try:
            from agents.predictive_maintenance import PredictiveMaintenanceAgent
        except ImportError:
            return []

        try:
            agent = PredictiveMaintenanceAgent()
            signals = agent.signals(db)
        except Exception as exc:
            logger.warning("Maintenance risk collector failed: %s", exc)
            return []

        items = []
        for sig in signals:
            if sig.get("risk_level") != "urgent":
                continue

            machine_id = sig["machine_id"]
            exc_id = f"maintenance_risk-{machine_id}"
            score = sig.get("risk_score", 0)
            fault_24h = sig.get("fault_count_24h", 0)
            mtbf = sig.get("mtbf_hours")
            mtbf_str = f"{mtbf:.1f}h MTBF" if mtbf is not None else "MTBF unknown"
            recommendation = sig.get("recommendation", "Schedule immediate inspection.")
            last_fault = sig.get("last_fault_at") or "unknown"

            items.append(ExceptionItem(
                exc_id=exc_id,
                source="maintenance_risk",
                severity="critical",
                title=f"Machine {machine_id} — urgent maintenance risk (score {score})",
                detail=(
                    f"Machine {machine_id} has {fault_24h} fault(s) in the last 24h, "
                    f"{mtbf_str}. Last fault: {last_fault}. "
                    f"{recommendation}"
                ),
                machine_id=machine_id,
                occurred_at=datetime.now(timezone.utc),
            ))

        return items

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def summary(self, db) -> dict:
        """Count of open exceptions by source and severity."""
        items = self.gather(db, include_resolved=False)
        by_source: dict[str, int] = {}
        by_severity: dict[str, int] = {"critical": 0, "warning": 0, "info": 0}

        for item in items:
            by_source[item.source] = by_source.get(item.source, 0) + 1
            by_severity[item.severity] = by_severity.get(item.severity, 0) + 1

        return {
            "open_exceptions": len(items),
            "critical": by_severity["critical"],
            "warning": by_severity["warning"],
            "info": by_severity["info"],
            "by_source": by_source,
        }
