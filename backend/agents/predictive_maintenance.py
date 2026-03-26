"""
Predictive maintenance signals derived from MachineStateLog history.

Analyses fault frequency, MTBF, MTTR, and abnormal dwell times per machine.
Returns a risk score (0–100) and actionable recommendation for each machine.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

from db_models import MachineStateLog

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# How long a single FAULT event is allowed to take before adding to risk
_HIGH_MTTR_MINUTES = 30.0

# Fault counts that map to risk levels within a 24-hour window
_FAULT_THRESHOLDS = [
    (3, "urgent",       90),   # ≥3 faults in 24h → urgent
    (2, "service_soon", 65),   # 2 faults in 24h  → service_soon
    (1, "watch",        35),   # 1 fault  in 24h  → watch
    (0, "ok",           0),    # 0 faults          → ok
]

# Low MTBF (rapid re-faulting) adds to risk
_LOW_MTBF_HOURS = 12.0      # MTBF below this adds +20
_CRITICAL_MTBF_HOURS = 4.0  # MTBF below this adds +30 instead


class PredictiveMaintenanceAgent:
    """
    Analyses historical MachineStateLog data to surface maintenance risk signals.

    All logic is read-only — no DB writes.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def signals(
        self,
        db: Session,
        *,
        machine_ids: Optional[list[int]] = None,
        lookback_hours: int = 168,   # default 7 days
    ) -> list[dict]:
        """
        Return a maintenance-risk signal dict for every requested machine.

        If ``machine_ids`` is None, all machines present in MachineStateLog
        within the lookback window are analysed.

        Each dict contains:
          machine_id, fault_count_24h, fault_count_7d,
          mtbf_hours, mttr_minutes, last_fault_at,
          risk_score (0–100), risk_level, recommendation
        """
        cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=lookback_hours)
        cutoff_24h = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)

        # Collect all relevant log rows
        query = db.query(MachineStateLog).filter(MachineStateLog.occurred_at >= cutoff)
        if machine_ids:
            query = query.filter(MachineStateLog.machine_id.in_(machine_ids))
        rows: list[MachineStateLog] = query.order_by(MachineStateLog.occurred_at.asc()).all()

        if not rows:
            # Return safe "ok" signals for each requested machine
            if machine_ids:
                return [self._empty_signal(mid) for mid in machine_ids]
            return []

        # Group rows by machine
        by_machine: dict[int, list[MachineStateLog]] = {}
        for row in rows:
            by_machine.setdefault(row.machine_id, []).append(row)

        result = []
        target_ids = machine_ids or sorted(by_machine.keys())
        for mid in target_ids:
            machine_rows = by_machine.get(mid, [])
            result.append(self._analyse_machine(mid, machine_rows, cutoff_24h))

        return result

    def signal_for_machine(
        self,
        db: Session,
        machine_id: int,
        *,
        lookback_hours: int = 168,
    ) -> dict:
        """Return a single machine's signal dict."""
        results = self.signals(db, machine_ids=[machine_id], lookback_hours=lookback_hours)
        return results[0] if results else self._empty_signal(machine_id)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _analyse_machine(
        self,
        machine_id: int,
        rows: list[MachineStateLog],
        cutoff_24h: datetime,
    ) -> dict:
        fault_entries = [r for r in rows if r.to_state == "FAULT"]
        fault_count_7d = len(fault_entries)
        fault_count_24h = sum(1 for r in fault_entries if r.occurred_at >= cutoff_24h)

        last_fault_at: Optional[str] = None
        if fault_entries:
            last = fault_entries[-1].occurred_at
            last_fault_at = last.isoformat()

        mtbf_hours = self._compute_mtbf(fault_entries)
        mttr_minutes = self._compute_mttr(rows)

        risk_score, risk_level = self._score(fault_count_24h, fault_count_7d, mtbf_hours, mttr_minutes)
        recommendation = self._recommendation(risk_level, fault_count_24h, mtbf_hours, mttr_minutes)

        return {
            "machine_id": machine_id,
            "fault_count_24h": fault_count_24h,
            "fault_count_7d": fault_count_7d,
            "mtbf_hours": round(mtbf_hours, 2) if mtbf_hours is not None else None,
            "mttr_minutes": round(mttr_minutes, 1) if mttr_minutes is not None else None,
            "last_fault_at": last_fault_at,
            "risk_score": risk_score,
            "risk_level": risk_level,
            "recommendation": recommendation,
        }

    @staticmethod
    def _compute_mtbf(fault_entries: list[MachineStateLog]) -> Optional[float]:
        """Mean time between faults in hours. None if fewer than 2 faults."""
        if len(fault_entries) < 2:
            return None
        times = [r.occurred_at for r in fault_entries]
        gaps = [(times[i + 1] - times[i]).total_seconds() / 3600 for i in range(len(times) - 1)]
        return sum(gaps) / len(gaps)

    @staticmethod
    def _compute_mttr(rows: list[MachineStateLog]) -> Optional[float]:
        """
        Mean time to repair (time spent in FAULT state) in minutes.
        Measures from to_state=FAULT entry to the matching from_state=FAULT entry.
        Returns None if no resolved fault is found.
        """
        fault_start: Optional[datetime] = None
        durations: list[float] = []

        for row in rows:
            if row.to_state == "FAULT":
                fault_start = row.occurred_at
            elif row.from_state == "FAULT" and fault_start is not None:
                duration_minutes = (row.occurred_at - fault_start).total_seconds() / 60
                durations.append(duration_minutes)
                fault_start = None

        if not durations:
            return None
        return sum(durations) / len(durations)

    @staticmethod
    def _score(
        fault_count_24h: int,
        fault_count_7d: int,
        mtbf_hours: Optional[float],
        mttr_minutes: Optional[float],
    ) -> tuple[int, str]:
        """Return (risk_score 0-100, risk_level string)."""
        # Base score from 24h fault count
        base_score = 0
        risk_level = "ok"
        for threshold, level, score in _FAULT_THRESHOLDS:
            if fault_count_24h >= threshold:
                base_score = score
                risk_level = level
                break

        # Bonus from weekly fault volume
        if fault_count_7d >= 10:
            base_score = min(100, base_score + 15)
        elif fault_count_7d >= 5:
            base_score = min(100, base_score + 8)

        # Bonus from low MTBF (rapid re-faulting = bad)
        if mtbf_hours is not None:
            if mtbf_hours < _CRITICAL_MTBF_HOURS:
                base_score = min(100, base_score + 30)
            elif mtbf_hours < _LOW_MTBF_HOURS:
                base_score = min(100, base_score + 15)

        # Bonus from high MTTR (slow recovery = bad)
        if mttr_minutes is not None and mttr_minutes > _HIGH_MTTR_MINUTES:
            base_score = min(100, base_score + 10)

        # Re-derive level from final score
        if base_score >= 80:
            risk_level = "urgent"
        elif base_score >= 60:
            risk_level = "service_soon"
        elif base_score >= 30:
            risk_level = "watch"
        else:
            risk_level = "ok"

        return base_score, risk_level

    @staticmethod
    def _recommendation(
        risk_level: str,
        fault_count_24h: int,
        mtbf_hours: Optional[float],
        mttr_minutes: Optional[float],
    ) -> str:
        if risk_level == "ok":
            return "No action required."
        if risk_level == "watch":
            return (
                f"1 fault in the last 24 hours. Monitor closely; schedule inspection "
                f"if faults continue."
            )
        if risk_level == "service_soon":
            mtbf_str = f" MTBF: {mtbf_hours:.1f}h." if mtbf_hours else ""
            return (
                f"{fault_count_24h} faults in the last 24 hours.{mtbf_str} "
                f"Schedule preventive maintenance within 48 hours."
            )
        # urgent
        mtbf_str = f" MTBF: {mtbf_hours:.1f}h." if mtbf_hours else ""
        mttr_str = f" Avg repair: {mttr_minutes:.0f} min." if mttr_minutes else ""
        return (
            f"URGENT: {fault_count_24h} faults in the last 24 hours.{mtbf_str}{mttr_str} "
            f"Take machine offline for immediate inspection."
        )

    @staticmethod
    def _empty_signal(machine_id: int) -> dict:
        return {
            "machine_id": machine_id,
            "fault_count_24h": 0,
            "fault_count_7d": 0,
            "mtbf_hours": None,
            "mttr_minutes": None,
            "last_fault_at": None,
            "risk_score": 0,
            "risk_level": "ok",
            "recommendation": "No action required.",
        }
