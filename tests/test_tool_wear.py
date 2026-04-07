"""
Tests for the Tool Wear Monitoring system.

Coverage:
  1-4:   ToolWearAgent — registration, ingestion, baseline learning
  5-8:   Wear scoring — EMA smoothing, alert levels
  9-11:  RUL prediction — linear regression, confidence
  12-14: Change recommendation logic
  15:    Simulation
  16-17: ToolAwareScheduler post-processing
"""

import sys
import os
import numpy as np
import pytest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.tool_wear_agent import (
    ToolWearAgent,
    ToolState,
    _feature_vector,
    _mahalanobis_diagonal,
    _alert_level,
    EMA_ALPHA,
    MIN_BASELINE_READINGS,
)
from agents.tool_aware_scheduler import build_tool_aware_schedule


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_reading(vibration_rms=1.0, acoustic_rms=1.0, spindle_load_pct=50.0,
                  feed_rate_actual=100.0, scale=1.0):
    r = {}
    r["vibration_rms"] = vibration_rms * scale
    r["vibration_peak_freq"] = 1000.0 * scale
    for i in range(8):
        r[f"vibration_band_energy_{i}"] = 0.1 * scale
    r["acoustic_rms"] = acoustic_rms * scale
    r["acoustic_peak_freq"] = 2000.0 * scale
    for i in range(8):
        r[f"acoustic_band_energy_{i}"] = 0.05 * scale
    r["spindle_load_pct"] = spindle_load_pct * scale
    r["feed_rate_actual"] = feed_rate_actual * scale
    return r


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# 1. Registration
# ---------------------------------------------------------------------------

def test_register_tool():
    agent = ToolWearAgent()
    state = agent.register_tool("T1", machine_id=1, tool_type="end_mill", material="steel")
    assert state.tool_id == "T1"
    assert state.machine_id == 1
    assert not state.is_baseline_ready


def test_register_tool_returns_existing_on_re_register():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    state2 = agent.register_tool("T1", machine_id=1)
    assert state2.tool_id == "T1"
    assert len(agent.list_tools()) == 1


# ---------------------------------------------------------------------------
# 2. Ingestion before baseline
# ---------------------------------------------------------------------------

def test_ingest_before_baseline_returns_zero():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    reading = _make_reading()
    score = agent.ingest_reading("T1", reading)
    assert score == 0.0


def test_ingest_unknown_tool_returns_none():
    agent = ToolWearAgent()
    score = agent.ingest_reading("MISSING", _make_reading())
    assert score is None


# ---------------------------------------------------------------------------
# 3. Baseline learning
# ---------------------------------------------------------------------------

def test_baseline_activates_after_min_readings():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    reading = _make_reading()
    for _ in range(MIN_BASELINE_READINGS):
        agent.ingest_reading("T1", reading)
    state = agent.get_tool("T1")
    assert state.is_baseline_ready
    assert state.baseline_mean is not None
    assert state.baseline_var is not None


def test_baseline_not_ready_before_min_readings():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    reading = _make_reading()
    for _ in range(MIN_BASELINE_READINGS - 1):
        agent.ingest_reading("T1", reading)
    state = agent.get_tool("T1")
    assert not state.is_baseline_ready


# ---------------------------------------------------------------------------
# 4. Feature vector
# ---------------------------------------------------------------------------

def test_feature_vector_length():
    reading = _make_reading()
    feat = _feature_vector(reading)
    assert feat.shape == (22,)


def test_feature_vector_missing_keys_default_zero():
    feat = _feature_vector({"vibration_rms": 1.0, "acoustic_rms": 0.5,
                            "vibration_peak_freq": 100.0, "acoustic_peak_freq": 200.0,
                            "spindle_load_pct": 40.0, "feed_rate_actual": 80.0})
    assert feat[0] == 1.0   # vibration_rms
    assert feat[10] == 0.5  # acoustic_rms


# ---------------------------------------------------------------------------
# 5. EMA smoothing
# ---------------------------------------------------------------------------

def test_ema_smoothing_is_applied():
    state = ToolState(tool_id="T", machine_id=1)
    # Inject baseline
    base = np.ones(22)
    for _ in range(MIN_BASELINE_READINGS):
        state.ingest(base, _now())
    assert state.is_baseline_ready
    assert state.wear_score_ema == 0.0  # identical to baseline → no drift

    # Inject strongly drifted reading
    drifted = np.ones(22) * 10.0
    score = state.ingest(drifted, _now())
    # EMA formula: 0.3 * raw_score + 0.7 * 0
    # We can't predict the exact raw_score but EMA must be < raw_score
    assert 0.0 < score <= 100.0


# ---------------------------------------------------------------------------
# 6. Alert levels
# ---------------------------------------------------------------------------

def test_alert_green():
    assert _alert_level(0.0) == "GREEN"
    assert _alert_level(39.9) == "GREEN"


def test_alert_yellow():
    assert _alert_level(40.0) == "YELLOW"
    assert _alert_level(69.9) == "YELLOW"


def test_alert_red():
    assert _alert_level(70.0) == "RED"
    assert _alert_level(89.9) == "RED"


def test_alert_critical():
    assert _alert_level(90.0) == "CRITICAL"
    assert _alert_level(100.0) == "CRITICAL"


# ---------------------------------------------------------------------------
# 7. Mahalanobis — diagonal
# ---------------------------------------------------------------------------

def test_mahalanobis_diagonal_identical_returns_zero():
    x = np.array([1.0, 2.0, 3.0])
    mean = np.array([1.0, 2.0, 3.0])
    var = np.array([1.0, 1.0, 1.0])
    assert _mahalanobis_diagonal(x, mean, var) == pytest.approx(0.0)


def test_mahalanobis_diagonal_single_sigma():
    x = np.array([2.0])
    mean = np.array([1.0])
    var = np.array([1.0])
    assert _mahalanobis_diagonal(x, mean, var) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 8. Wear score increases with drift
# ---------------------------------------------------------------------------

def test_wear_score_increases_with_drift():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    # Establish baseline
    base = _make_reading(scale=1.0)
    for _ in range(MIN_BASELINE_READINGS):
        agent.ingest_reading("T1", base)
    # Ingest drifted readings
    drift_scores = []
    for mult in [2.0, 4.0, 8.0]:
        score = agent.ingest_reading("T1", _make_reading(scale=mult))
        drift_scores.append(score)
    # Scores should generally increase
    assert drift_scores[-1] > drift_scores[0]


# ---------------------------------------------------------------------------
# 9. RUL — not enough data
# ---------------------------------------------------------------------------

def test_rul_not_enough_data():
    state = ToolState(tool_id="T", machine_id=1)
    rul, conf = state.rul_minutes()
    assert rul is None
    assert conf == 0.0


# ---------------------------------------------------------------------------
# 10. RUL with stable tool (flat wear)
# ---------------------------------------------------------------------------

def test_rul_stable_tool_returns_none():
    state = ToolState(tool_id="T", machine_id=1)
    # Inject 10 identical wear scores (flat → slope ≈ 0)
    for _ in range(10):
        state.raw_scores.append(10.0)
        state.reading_times.append(_now())
    rul, conf = state.rul_minutes()
    # Flat or negative slope → no finite RUL
    assert rul is None


# ---------------------------------------------------------------------------
# 11. RUL with rising wear
# ---------------------------------------------------------------------------

def test_rul_rising_wear():
    state = ToolState(tool_id="T", machine_id=1)
    base_time = _now()
    for i in range(20):
        state.raw_scores.append(float(i * 4))  # linearly rising 0→76
        state.reading_times.append(base_time + timedelta(minutes=i))
    state.wear_score_ema = state.raw_scores[-1]
    rul, conf = state.rul_minutes()
    assert rul is not None
    assert rul > 0.0
    assert 0.0 <= conf <= 1.0


# ---------------------------------------------------------------------------
# 12. Change recommendation — GREEN tool
# ---------------------------------------------------------------------------

def test_change_recommendation_green_tool():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    rec = agent.change_recommendation("T1", job_duration_minutes=60.0)
    # Baseline not ready → wear_score = 0 → no change
    assert rec["change_required"] is False


# ---------------------------------------------------------------------------
# 13. Change recommendation — CRITICAL tool
# ---------------------------------------------------------------------------

def test_change_recommendation_critical_tool():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    state = agent.get_tool("T1")
    state.wear_score_ema = 95.0  # CRITICAL
    state.baseline_mean = np.ones(22)
    state.baseline_var = np.ones(22)
    rec = agent.change_recommendation("T1", job_duration_minutes=60.0)
    assert rec["change_required"] is True
    assert rec["alert_level"] == "CRITICAL"


# ---------------------------------------------------------------------------
# 14. Reset clears state
# ---------------------------------------------------------------------------

def test_reset_clears_wear_state():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    state = agent.get_tool("T1")
    state.wear_score_ema = 80.0
    state.raw_scores = [70.0, 75.0, 80.0]
    agent.reset_tool("T1")
    assert state.wear_score_ema == 0.0
    assert len(state.raw_scores) == 0
    assert not state.is_baseline_ready


# ---------------------------------------------------------------------------
# 15. Simulation
# ---------------------------------------------------------------------------

def test_simulate_wear_progression():
    agent = ToolWearAgent()
    scores = agent.simulate_wear_progression("SIM-TOOL", steps=30)
    assert len(scores) == 30
    # First scores should be 0 (baseline learning phase)
    assert scores[0] == 0.0
    # By the end there should be some wear
    assert scores[-1] > 0.0


# ---------------------------------------------------------------------------
# 16. ToolAwareScheduler — no tools → passthrough
# ---------------------------------------------------------------------------

class _FakeScheduledOrder:
    def __init__(self, order_id, machine_id, processing_start, completion_time, processing_minutes):
        self.order_id = order_id
        self.machine_id = machine_id
        self.processing_start = processing_start
        self.completion_time = completion_time
        self.processing_minutes = processing_minutes


class _FakeSchedule:
    def __init__(self, orders):
        self.scheduled_orders = orders


def test_tool_aware_no_tools():
    agent = ToolWearAgent()
    base = _now()
    orders = [
        _FakeScheduledOrder("O1", 1, base, base + timedelta(hours=1), 60),
        _FakeScheduledOrder("O2", 1, base + timedelta(hours=1), base + timedelta(hours=2), 60),
    ]
    schedule = _FakeSchedule(orders)
    result = build_tool_aware_schedule(schedule, agent)
    assert result["tool_changes"] == []
    assert result["tool_warnings"] == []
    assert len(result["scheduled_orders"]) == 2


# ---------------------------------------------------------------------------
# 17. ToolAwareScheduler — RED tool triggers change
# ---------------------------------------------------------------------------

def test_tool_aware_red_tool_inserts_change():
    agent = ToolWearAgent()
    agent.register_tool("T1", machine_id=1)
    state = agent.get_tool("T1")
    # Force RED wear on machine 1
    state.wear_score_ema = 75.0
    state.baseline_mean = np.ones(22)
    state.baseline_var = np.ones(22)

    base = _now()
    orders = [
        _FakeScheduledOrder("O1", 1, base, base + timedelta(hours=1), 60),
        _FakeScheduledOrder("O2", 1, base + timedelta(hours=1), base + timedelta(hours=2), 60),
    ]
    schedule = _FakeSchedule(orders)
    result = build_tool_aware_schedule(schedule, agent)
    # Should have at least one tool change and one warning
    assert len(result["tool_changes"]) >= 1
    assert len(result["tool_warnings"]) >= 1
    tc = result["tool_changes"][0]
    assert tc["tool_id"] == "T1"
    assert tc["machine_id"] == 1
