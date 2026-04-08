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

import numpy as np

try:
    import joblib
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.metrics import mean_absolute_error
    from sklearn.model_selection import train_test_split
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

from agents.scheduler import BASE_SETUP_MINUTES, SETUP_MATRIX

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).parent.parent / "models" / "setup_time_predictor.pkl"
MIN_TRAINING_RECORDS = 20

MATERIALS = ["steel", "aluminum", "titanium", "copper"]
_MATERIAL_INDEX = {m: i for i, m in enumerate(MATERIALS)}

TOLERANCE_CLASSES = ["standard", "medium", "tight", "ultra"]
_TOLERANCE_INDEX = {t: i for i, t in enumerate(TOLERANCE_CLASSES)}

# Feature count for the current model version.
# Increment when adding features — triggers automatic refit if saved model mismatches.
_N_FEATURES = 7   # from_mat, to_mat, machine_id, hour, day, sim_confidence, tolerance_class


def _encode_material(m: str) -> int:
    """Integer-encode a material string. Unknown materials map to len(MATERIALS)."""
    return _MATERIAL_INDEX.get(m.lower(), len(MATERIALS))


def _encode_tolerance(t: str) -> float:
    """Map tolerance class string to a numeric feature (0=standard … 3=ultra).

    Also accepts raw float pass-through (e.g. from a legacy record).
    """
    if isinstance(t, (int, float)):
        return float(t)
    return float(_TOLERANCE_INDEX.get(str(t).lower(), 0))


class SetupTimePredictor:
    """
    Predicts CNC machine setup time (minutes) for a material changeover.

    Features (7):
      from_material (int), to_material (int), machine_id (int),
      hour_of_day (int 0-23), day_of_week (int 0-6 Mon-Sun),
      simulation_confidence (float 0-1),   ← from ARIA CAM simulation
      tolerance_class (float 0-3)           ← 0=standard,1=medium,2=tight,3=ultra

    Target:   actual setup time in minutes (float)
    """

    def __init__(self) -> None:
        self._model: Optional[object] = None
        self._trained = False
        self._mae: Optional[float] = None
        self._n_training: int = 0
        if SKLEARN_AVAILABLE:
            self._load_model()
        else:
            logger.warning("scikit-learn/joblib not installed — SetupTimePredictor using SETUP_MATRIX fallback")

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
        simulation_confidence: float = 0.8,
        tolerance_class: str = "standard",
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
            float(simulation_confidence),
            _encode_tolerance(tolerance_class),
        ]])
        return float(self._model.predict(features)[0])

    def train(self, records: list[dict]) -> dict:
        """
        Train on a list of feedback dicts.

        Required keys per record: from_material, to_material, machine_id,
        actual_setup_minutes. Optional: hour_of_day, day_of_week.

        Returns accuracy metrics. Saves model to MODEL_PATH on success.
        """
        if not SKLEARN_AVAILABLE:
            return {
                "trained": False,
                "reason": "scikit-learn not installed — run: pip install scikit-learn joblib",
                "n_records": len(records),
            }
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
                float(r.get("simulation_confidence", 0.8)),
                _encode_tolerance(r.get("tolerance_class", "standard")),
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

    def train_from_db(self, db) -> dict:
        """Query all JobFeedbackRecord rows and train on them.

        Uses material as both from_material and to_material — the feedback
        record tracks the job material but not the previous machine material,
        so same-material changeover is the best approximation available.
        """
        from db_models import JobFeedbackRecord

        rows = db.query(JobFeedbackRecord).all()
        records = [
            {
                "from_material": r.material,
                "to_material": r.material,
                "machine_id": r.machine_id,
                "actual_setup_minutes": r.actual_setup_minutes,
                "simulation_confidence": (
                    r.simulation_confidence
                    if r.simulation_confidence is not None
                    else 0.8
                ),
                "tolerance_class": r.tolerance_class or "standard",
            }
            for r in rows
        ]
        return self.train(records)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_model(self) -> None:
        if not SKLEARN_AVAILABLE:
            return
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(self._model, MODEL_PATH)
        logger.info("SetupTimePredictor saved to %s", MODEL_PATH)

    def _load_model(self) -> None:
        if not SKLEARN_AVAILABLE or not MODEL_PATH.exists():
            return
        try:
            model = joblib.load(MODEL_PATH)
            # Reject models trained on a different feature count — they will
            # produce wrong predictions silently if we let them through.
            n_features = getattr(model, "n_features_in_", None)
            if n_features is not None and n_features != _N_FEATURES:
                logger.warning(
                    "SetupTimePredictor: saved model has %d features, expected %d — "
                    "discarding (will retrain on next feedback batch)",
                    n_features, _N_FEATURES,
                )
                MODEL_PATH.unlink(missing_ok=True)
                return
            self._model = model
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
