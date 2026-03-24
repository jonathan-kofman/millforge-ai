"""
Unit tests for SetupTimePredictor.

Eight tests:
  1. fallback when untrained
  2. train rejects < MIN_TRAINING_RECORDS
  3. train succeeds with enough records
  4. predict uses ML after training
  5. predict falls back for unknown material pair
  6. accuracy_report fields when untrained
  7. accuracy_report fields after training
  8. model round-trips through save/load
"""

import sys
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
import numpy as np

from agents.setup_time_predictor import SetupTimePredictor, MIN_TRAINING_RECORDS, MODEL_PATH


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_records(n: int) -> list[dict]:
    """Generate n synthetic feedback records with realistic values."""
    rng = np.random.default_rng(42)
    materials = ["steel", "aluminum", "titanium", "copper"]
    records = []
    for i in range(n):
        fm = materials[i % len(materials)]
        tm = materials[(i + 1) % len(materials)]
        records.append({
            "from_material": fm,
            "to_material": tm,
            "machine_id": (i % 3) + 1,
            "hour_of_day": int(rng.integers(6, 22)),
            "day_of_week": int(rng.integers(0, 5)),
            "actual_setup_minutes": float(rng.integers(15, 90)),
        })
    return records


# ---------------------------------------------------------------------------
# 1. Fallback when untrained
# ---------------------------------------------------------------------------

def test_predict_fallback_when_untrained():
    """Untrained predictor returns SETUP_MATRIX / BASE value — not zero."""
    with patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
    result = p.predict("steel", "aluminum", machine_id=1)
    assert result > 0


# ---------------------------------------------------------------------------
# 2. Train rejects insufficient records
# ---------------------------------------------------------------------------

def test_train_rejects_too_few_records():
    with patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
    result = p.train(_make_records(MIN_TRAINING_RECORDS - 1))
    assert result["trained"] is False
    assert "need" in result["reason"]


# ---------------------------------------------------------------------------
# 3. Train succeeds with enough records
# ---------------------------------------------------------------------------

def test_train_succeeds_with_sufficient_records(tmp_path):
    model_file = tmp_path / "test_model.pkl"
    with patch("agents.setup_time_predictor.MODEL_PATH", model_file), \
         patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
        result = p.train(_make_records(MIN_TRAINING_RECORDS + 5))
    assert result["trained"] is True
    assert "mae_minutes" in result
    assert result["n_records"] == MIN_TRAINING_RECORDS + 5


# ---------------------------------------------------------------------------
# 4. Predict uses ML after training
# ---------------------------------------------------------------------------

def test_predict_uses_ml_after_training(tmp_path):
    model_file = tmp_path / "test_model.pkl"
    with patch("agents.setup_time_predictor.MODEL_PATH", model_file), \
         patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
        p.train(_make_records(MIN_TRAINING_RECORDS + 10))
        assert p._trained is True
        minutes = p.predict("steel", "aluminum", machine_id=1)
    assert isinstance(minutes, float)
    assert 0 < minutes < 300  # sanity range


# ---------------------------------------------------------------------------
# 5. Fallback for unknown material pair (still returns a positive number)
# ---------------------------------------------------------------------------

def test_fallback_unknown_materials():
    with patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
    result = p.predict("unobtainium", "vibranium", machine_id=1)
    assert result > 0  # BASE_SETUP_MINUTES = 30


# ---------------------------------------------------------------------------
# 6. Accuracy report when untrained
# ---------------------------------------------------------------------------

def test_accuracy_report_untrained():
    with patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
    report = p.accuracy_report()
    assert report["trained"] is False
    assert report["mae_minutes"] is None
    assert report["fallback"] == "SETUP_MATRIX"


# ---------------------------------------------------------------------------
# 7. Accuracy report after training
# ---------------------------------------------------------------------------

def test_accuracy_report_after_training(tmp_path):
    model_file = tmp_path / "test_model.pkl"
    with patch("agents.setup_time_predictor.MODEL_PATH", model_file), \
         patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p = SetupTimePredictor()
        p.train(_make_records(MIN_TRAINING_RECORDS + 10))
        report = p.accuracy_report()
    assert report["trained"] is True
    assert isinstance(report["mae_minutes"], float)
    assert report["n_training_records"] == MIN_TRAINING_RECORDS + 10
    assert report["fallback"] is None


# ---------------------------------------------------------------------------
# 8. Model round-trips through save / load
# ---------------------------------------------------------------------------

def test_model_roundtrip_save_load(tmp_path):
    model_file = tmp_path / "roundtrip_model.pkl"
    records = _make_records(MIN_TRAINING_RECORDS + 10)

    with patch("agents.setup_time_predictor.MODEL_PATH", model_file), \
         patch.object(SetupTimePredictor, "_load_model", lambda self: None):
        p1 = SetupTimePredictor()
        p1.train(records)
        pred1 = p1.predict("steel", "titanium", machine_id=2)

    # Load fresh instance from saved file
    with patch("agents.setup_time_predictor.MODEL_PATH", model_file):
        p2 = SetupTimePredictor()  # will load from file in _load_model
    assert p2._trained is True
    pred2 = p2.predict("steel", "titanium", machine_id=2)
    assert abs(pred1 - pred2) < 0.01  # same model, same prediction
