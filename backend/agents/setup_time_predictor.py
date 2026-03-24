"""
ML surrogate for CNC setup time prediction — adapted from microgravity-manufacturing-stack.

Uses RandomForestRegressor on historical job feedback to learn actual changeover times.
Falls back to SETUP_MATRIX when fewer than MIN_TRAINING_RECORDS are available.

Model file: backend/models/setup_time_predictor.pkl
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import train_test_split

from agents.scheduler import BASE_SETUP_MINUTES, SETUP_MATRIX

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent / "models" / "setup_time_predictor.pkl"
MIN_TRAINING_RECORDS = 20

MATERIALS = ["steel", "aluminum", "titanium", "copper"]
_MATERIAL_INDEX = {m: i for i, m in enumerate(MATERIALS)}


def _encode_material(m: str) -> int:
    """Integer-encode a material string. Unknown materials map to len(MATERIALS)."""
    return _MATERIAL_INDEX.get(m.lower(), len(MATERIALS))


class SetupTimePredictor:
    """
    Predicts CNC machine setup time (minutes) for a material changeover.

    Features: from_material (int), to_material (int), machine_id (int),
              hour_of_day (int 0-23), day_of_week (int 0-6 Mon-Sun)
    Target:   actual setup time in minutes (float)
    """

    def __init__(self) -> None:
        self._model: Optional[RandomForestRegressor] = None
        self._trained = False
        self._mae: Optional[float] = None
        self._n_training: int = 0
        self._load_model()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def predict(
        self,
        from_material: str,
        to_material: str,
        machine_id: int,
        hour_of_day: int = 8,
        day_of_week: int = 0,
    ) -> float:
        """Return predicted setup time in minutes. Falls back to SETUP_MATRIX if untrained."""
        if not self._trained or self._model is None:
            return self._fallback(from_material, to_material)

        features = np.array([[
            _encode_material(from_material),
            _encode_material(to_material),
            machine_id,
            hour_of_day,
            day_of_week,
        ]])
        return float(self._model.predict(features)[0])

    def train(self, records: list[dict]) -> dict:
        """
        Train on a list of feedback dicts.

        Required keys per record: from_material, to_material, machine_id,
        actual_setup_minutes. Optional: hour_of_day, day_of_week.

        Returns accuracy metrics. Saves model to MODEL_PATH on success.
        """
        if len(records) < MIN_TRAINING_RECORDS:
            return {
                "trained": False,
                "reason": f"need ≥{MIN_TRAINING_RECORDS} records, got {len(records)}",
                "n_records": len(records),
            }

        X = np.array([
            [
                _encode_material(r["from_material"]),
                _encode_material(r["to_material"]),
                r["machine_id"],
                r.get("hour_of_day", 8),
                r.get("day_of_week", 0),
            ]
            for r in records
        ])
        y = np.array([r["actual_setup_minutes"] for r in records])

        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.3, random_state=42
        )
        model = RandomForestRegressor(n_estimators=200, random_state=42)
        model.fit(X_train, y_train)

        mae = float(mean_absolute_error(y_test, model.predict(X_test)))
        self._model = model
        self._trained = True
        self._mae = mae
        self._n_training = len(records)

        self._save_model()
        logger.info("SetupTimePredictor trained: n=%d MAE=%.2f min", len(records), mae)
        return {
            "trained": True,
            "n_records": len(records),
            "mae_minutes": round(mae, 2),
            "model_path": str(MODEL_PATH),
        }

    def accuracy_report(self) -> dict:
        """Metrics for the /api/learning/setup-time-accuracy endpoint."""
        return {
            "trained": self._trained,
            "n_training_records": self._n_training,
            "mae_minutes": round(self._mae, 2) if self._mae is not None else None,
            "fallback": "SETUP_MATRIX" if not self._trained else None,
            "model_path": str(MODEL_PATH) if self._trained else None,
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_model(self) -> None:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, MODEL_PATH)
        logger.info("SetupTimePredictor saved to %s", MODEL_PATH)

    def _load_model(self) -> None:
        if MODEL_PATH.exists():
            try:
                self._model = joblib.load(MODEL_PATH)
                self._trained = True
                logger.info("SetupTimePredictor loaded from %s", MODEL_PATH)
            except Exception as exc:
                logger.warning("Could not load predictor model: %s", exc)

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback(self, from_material: str, to_material: str) -> float:
        key = (from_material.lower(), to_material.lower())
        return float(SETUP_MATRIX.get(key, BASE_SETUP_MINUTES))
