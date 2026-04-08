"""
Scheduling Digital Twin — wraps SETUP_MATRIX / THROUGHPUT physics defaults,
upgrades to ML predictions automatically as feedback accumulates.

Narrow predict API: predict_setup_time(), predict_completion(), predict_on_time_probability()
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from agents.scheduler import BASE_SETUP_MINUTES, SETUP_MATRIX, THROUGHPUT

logger = logging.getLogger(__name__)

# Lazy singleton — loaded once on first call
_setup_predictor = None


def _get_setup_predictor():
    global _setup_predictor
    if _setup_predictor is None:
        try:
            from agents.setup_time_predictor import SetupTimePredictor
            _setup_predictor = SetupTimePredictor()
        except Exception as exc:
            logger.warning("Could not initialise SetupTimePredictor: %s", exc)
    return _setup_predictor


class SchedulingTwin:
    """
    Digital twin for the MillForge scheduler.

    Defaults to physics-based constants (SETUP_MATRIX, THROUGHPUT).
    Automatically upgrades to ML predictions once SetupTimePredictor is trained
    with ≥20 feedback records.
    """

    def predict_setup_time(
        self,
        from_material: str,
        to_material: str,
        machine_id: int = 1,
        hour_of_day: int = 8,
        day_of_week: int = 0,
        simulation_confidence: float = 0.8,
        tolerance_class: str = "standard",
    ) -> dict:
        """Predict setup/changeover time in minutes.

        simulation_confidence — ARIA CAM simulation confidence score (0–1).
          Lower confidence (e.g. 0.4) typically correlates with more complex
          setups and wider tolerances, both of which increase setup time.

        tolerance_class — from the ARIA job submission:
          "standard" | "medium" | "tight" | "ultra"
          Tighter tolerances require slower feeds and more careful setup.
        """
        predictor = _get_setup_predictor()
        if predictor is not None and predictor._trained:
            minutes = predictor.predict(
                from_material, to_material, machine_id, hour_of_day, day_of_week,
                simulation_confidence=simulation_confidence,
                tolerance_class=tolerance_class,
            )
            source = "ml_model"
        else:
            key = (from_material.lower(), to_material.lower())
            minutes = float(SETUP_MATRIX.get(key, BASE_SETUP_MINUTES))
            source = "setup_matrix"

        return {
            "from_material": from_material,
            "to_material": to_material,
            "machine_id": machine_id,
            "predicted_setup_minutes": round(minutes, 1),
            "source": source,
            "simulation_confidence": simulation_confidence,
            "tolerance_class": tolerance_class,
        }

    def predict_completion(
        self,
        material: str,
        quantity: int,
        complexity: float,
        setup_time_minutes: float,
        start_time: Optional[datetime] = None,
    ) -> dict:
        """Predict when a job will complete given its parameters."""
        if start_time is None:
            start_time = datetime.now(timezone.utc).replace(tzinfo=None)

        throughput = THROUGHPUT.get(material.lower(), 3.0)
        processing_hours = (quantity / throughput) * complexity
        total_minutes = setup_time_minutes + processing_hours * 60
        completion = start_time + timedelta(minutes=total_minutes)

        return {
            "material": material,
            "quantity": quantity,
            "complexity": complexity,
            "setup_minutes": round(setup_time_minutes, 1),
            "processing_hours": round(processing_hours, 2),
            "total_minutes": round(total_minutes, 1),
            "predicted_completion": completion.isoformat(),
            "throughput_units_per_hour": throughput,
        }

    def predict_on_time_probability(
        self,
        material: str,
        quantity: int,
        complexity: float,
        setup_time_minutes: float,
        due_date: datetime,
        start_time: Optional[datetime] = None,
    ) -> dict:
        """
        Predict probability that a job finishes before due_date.

        Heuristic: ≥120 min slack → 95%, 0 min slack → 50%,
        negative slack → clamps at 10%.
        """
        completion_info = self.predict_completion(
            material, quantity, complexity, setup_time_minutes, start_time
        )
        predicted = datetime.fromisoformat(completion_info["predicted_completion"])
        slack_minutes = (due_date - predicted).total_seconds() / 60

        if slack_minutes >= 120:
            prob = 0.95
        elif slack_minutes >= 0:
            prob = 0.50 + (slack_minutes / 120) * 0.45
        else:
            prob = max(0.10, 0.50 + (slack_minutes / 120) * 0.40)

        return {
            **completion_info,
            "due_date": due_date.isoformat(),
            "slack_minutes": round(slack_minutes, 1),
            "on_time_probability": round(prob, 3),
            "on_time": slack_minutes >= 0,
        }

    def accuracy_report(self, db) -> dict:
        """Compare twin predictions against logged actuals from JobFeedbackRecord."""
        from db_models import JobFeedbackRecord

        records = (
            db.query(JobFeedbackRecord)
            .order_by(JobFeedbackRecord.logged_at.desc())
            .limit(100)
            .all()
        )

        if not records:
            return {"n_records": 0, "message": "No feedback data yet — log job outcomes via /api/learning/feedback"}

        setup_errs = [abs(r.actual_setup_minutes - r.predicted_setup_minutes) for r in records]
        proc_errs = [abs(r.actual_processing_minutes - r.predicted_processing_minutes) for r in records]

        predictor = _get_setup_predictor()
        ml_info = predictor.accuracy_report() if predictor is not None else {"trained": False}

        return {
            "n_records": len(records),
            "setup_mae_minutes": round(sum(setup_errs) / len(setup_errs), 2),
            "processing_mae_minutes": round(sum(proc_errs) / len(proc_errs), 2),
            "ml_model": ml_info,
            "data_source": "job_feedback_log",
        }
