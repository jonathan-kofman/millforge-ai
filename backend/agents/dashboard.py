"""
Live factory dashboard — single-endpoint aggregation of all lights-out metrics.

GET /api/dashboard/live returns a point-in-time snapshot of:
  - open_exceptions     count + breakdown by source/severity
  - schedule_health     latest run on-time rate, makespan, algorithm
  - machine_states      per-machine current state (from MachineStateLog)
  - maintenance_risk    count of urgent/watch machines
  - inventory_health    materials below reorder point
  - energy_today        estimated cost and carbon for today's load
  - lights_out_score    overall automation readiness (0–100)

All collectors are fault-tolerant — a failing data source returns a degraded
partial result rather than killing the whole response.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


class DashboardAgent:
    """Aggregates live factory metrics from all subsystems."""

    def __init__(self, inventory_agent=None) -> None:
        self._inventory = inventory_agent

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def live(self, db: Session) -> dict:
        """Return the full live dashboard snapshot."""
        collected_at = datetime.now(timezone.utc).isoformat()

        exceptions    = self._exceptions(db)
        schedule      = self._schedule_health(db)
        machines      = self._machine_states(db)
        maintenance   = self._maintenance_risk(db)
        inventory     = self._inventory_health()
        energy        = self._energy_today()
        score         = self._lights_out_score(exceptions, schedule, maintenance)

        return {
            "collected_at":      collected_at,
            "lights_out_score":  score,
            "open_exceptions":   exceptions,
            "schedule_health":   schedule,
            "machine_states":    machines,
            "maintenance_risk":  maintenance,
            "inventory_health":  inventory,
            "energy_today":      energy,
        }

    # ------------------------------------------------------------------
    # Collectors
    # ------------------------------------------------------------------

    def _exceptions(self, db) -> dict:
        try:
            from agents.exception_queue import ExceptionQueueAgent
            agent = ExceptionQueueAgent(inventory_agent=self._inventory)
            items = agent.gather(db, include_resolved=False)
            by_source: dict[str, int] = {}
            by_severity = {"critical": 0, "warning": 0, "info": 0}
            for item in items:
                by_source[item.source] = by_source.get(item.source, 0) + 1
                by_severity[item.severity] = by_severity.get(item.severity, 0) + 1
            return {
                "total":      len(items),
                "critical":   by_severity["critical"],
                "warning":    by_severity["warning"],
                "info":       by_severity["info"],
                "by_source":  by_source,
            }
        except Exception as exc:
            logger.warning("Dashboard exceptions collector failed: %s", exc)
            return {"total": None, "error": str(exc)}

    def _schedule_health(self, db) -> dict:
        try:
            from db_models import ScheduleRun
            run = (
                db.query(ScheduleRun)
                .order_by(ScheduleRun.created_at.desc())
                .first()
            )
            if run is None:
                return {"status": "no_runs", "on_time_rate_percent": None}
            summary = run.summary
            return {
                "status":               "ok",
                "run_id":               run.id,
                "algorithm":            run.algorithm,
                "on_time_rate_percent": round(run.on_time_rate * 100, 1),
                "makespan_hours":       round(run.makespan_hours, 2),
                "orders_scheduled":     summary.get("total_orders"),
                "on_time_count":        summary.get("on_time_count"),
                "ran_at":               run.created_at.isoformat(),
            }
        except Exception as exc:
            logger.warning("Dashboard schedule collector failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _machine_states(self, db) -> dict:
        try:
            from db_models import MachineStateLog

            # Latest state per machine — get most recent row per machine_id
            cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=24)
            rows = (
                db.query(MachineStateLog)
                .filter(MachineStateLog.occurred_at >= cutoff)
                .order_by(MachineStateLog.occurred_at.desc())
                .limit(500)
                .all()
            )

            latest: dict[int, str] = {}
            for row in rows:
                if row.machine_id not in latest:
                    latest[row.machine_id] = row.to_state

            state_counts: dict[str, int] = {}
            for state in latest.values():
                state_counts[state] = state_counts.get(state, 0) + 1

            return {
                "total_machines":  len(latest),
                "state_counts":    state_counts,
                "running":         state_counts.get("RUNNING", 0),
                "idle":            state_counts.get("IDLE", 0),
                "fault":           state_counts.get("FAULT", 0),
                "per_machine":     latest,
            }
        except Exception as exc:
            logger.warning("Dashboard machine states collector failed: %s", exc)
            return {"total_machines": None, "error": str(exc)}

    def _maintenance_risk(self, db) -> dict:
        try:
            from agents.predictive_maintenance import PredictiveMaintenanceAgent
            signals = PredictiveMaintenanceAgent().signals(db)
            urgent      = [s for s in signals if s["risk_level"] == "urgent"]
            service_soon = [s for s in signals if s["risk_level"] == "service_soon"]
            watch       = [s for s in signals if s["risk_level"] == "watch"]
            return {
                "total_monitored":   len(signals),
                "urgent":            len(urgent),
                "service_soon":      len(service_soon),
                "watch":             len(watch),
                "ok":                len([s for s in signals if s["risk_level"] == "ok"]),
                "urgent_machine_ids": [s["machine_id"] for s in urgent],
            }
        except Exception as exc:
            logger.warning("Dashboard maintenance collector failed: %s", exc)
            return {"total_monitored": None, "error": str(exc)}

    def _inventory_health(self) -> dict:
        if self._inventory is None:
            return {"status": "unavailable"}
        try:
            status = self._inventory.check_reorder_points()
            return {
                "status":               "ok",
                "items_below_reorder":  status.items_below_reorder,
                "critical_count":       sum(
                    1 for m in status.items_below_reorder
                    if status.stock.get(m) and
                    status.stock[m].current_stock_kg < status.stock[m].reorder_point_kg * 0.5
                ),
            }
        except Exception as exc:
            logger.warning("Dashboard inventory collector failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    def _energy_today(self) -> dict:
        try:
            from agents.energy_optimizer import _get_hourly_rates
            rates, data_source = _get_hourly_rates()
            avg_rate = sum(rates) / max(len(rates), 1)

            # Estimate cost for a typical 8-hour production shift at 70 kW average load
            _TYPICAL_KW = 70.0
            _SHIFT_HOURS = 8
            kwh = _TYPICAL_KW * _SHIFT_HOURS
            cost_usd = kwh * avg_rate
            carbon_kg = kwh * 0.386  # EPA 2023 US grid average

            # Find cheapest 4-hour window
            indexed = list(enumerate(rates))
            sorted_rates = sorted(indexed, key=lambda x: x[1])
            cheap_hours = [h for h, _ in sorted_rates[:4]]

            return {
                "status":           "ok",
                "avg_rate_usd_kwh": round(avg_rate, 4),
                "shift_cost_usd":   round(cost_usd, 2),
                "shift_carbon_kg":  round(carbon_kg, 1),
                "cheapest_hours":   cheap_hours,
            }
        except Exception as exc:
            logger.warning("Dashboard energy collector failed: %s", exc)
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------
    # Composite score
    # ------------------------------------------------------------------

    def _lights_out_score(
        self,
        exceptions: dict,
        schedule: dict,
        maintenance: dict,
    ) -> dict:
        """
        Composite 0–100 score for lights-out readiness right now.

        Starts at 100 and deducts points for active problems:
          -10 per critical exception (max -40)
          -5  per warning exception (max -20)
          -15 if on-time rate < 80%
          -10 if on-time rate < 90%
          -20 per urgent machine (max -40)
          -10 per service_soon machine (max -20)
        """
        score = 100

        critical_exc = exceptions.get("critical") or 0
        warning_exc  = exceptions.get("warning")  or 0
        score -= min(critical_exc * 10, 40)
        score -= min(warning_exc  *  5, 20)

        otr = schedule.get("on_time_rate_percent")
        if otr is not None:
            if otr < 80:
                score -= 15
            elif otr < 90:
                score -= 10

        urgent_m      = maintenance.get("urgent")       or 0
        service_soon_m = maintenance.get("service_soon") or 0
        score -= min(urgent_m       * 20, 40)
        score -= min(service_soon_m * 10, 20)

        score = max(0, min(100, score))

        level = (
            "critical" if score < 50 else
            "degraded" if score < 75 else
            "healthy"  if score < 95 else
            "optimal"
        )

        return {"score": score, "level": level}
