"""
Tool Wear Agent — spectral drift anomaly detection + RUL prediction.

Ingests vibration and acoustic sensor readings from CNC machines,
tracks tool condition per (tool_id, machine_id) pair using Mahalanobis
distance on spectral features, predicts remaining useful life (RUL)
via linear regression, and emits tool-change recommendations.

Design notes:
- Uses diagonal covariance (not full) because baseline N=10 < 22 features.
  Full covariance would be singular. Diagonal = per-feature variance only.
- EMA smoothing alpha=0.3 prevents noise spikes from triggering false alerts.
- RUL linear regression runs on last 20 wear readings; confidence from R².
- Alert levels: GREEN <40, YELLOW 40-70, RED 70-90, CRITICAL >=90.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as scipy_stats

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALERT_THRESHOLDS = {
    "GREEN": (0, 40),
    "YELLOW": (40, 70),
    "RED": (70, 90),
    "CRITICAL": (90, 101),
}

MIN_BASELINE_READINGS = 10
EMA_ALPHA = 0.3
RUL_WINDOW = 20        # readings used for RUL regression
CHANGE_SAFETY_MARGIN = 1.2  # RUL must be > job_duration * 1.2 to skip change


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Feature vector helpers
# ---------------------------------------------------------------------------

def _feature_vector(reading: dict) -> np.ndarray:
    """
    Build 22-dimensional feature vector from a sensor reading dict.

    Expected keys (all float):
        vibration_rms, vibration_peak_freq,
        vibration_band_energy_0..7   (8 bands),
        acoustic_rms, acoustic_peak_freq,
        acoustic_band_energy_0..7    (8 bands),
        spindle_load_pct,
        feed_rate_actual
    """
    feats = [
        reading.get("vibration_rms", 0.0),
        reading.get("vibration_peak_freq", 0.0),
    ]
    for i in range(8):
        feats.append(reading.get(f"vibration_band_energy_{i}", 0.0))
    feats.append(reading.get("acoustic_rms", 0.0))
    feats.append(reading.get("acoustic_peak_freq", 0.0))
    for i in range(8):
        feats.append(reading.get(f"acoustic_band_energy_{i}", 0.0))
    feats.append(reading.get("spindle_load_pct", 0.0))
    feats.append(reading.get("feed_rate_actual", 0.0))
    return np.array(feats, dtype=float)


def _mahalanobis_diagonal(x: np.ndarray, mean: np.ndarray, var: np.ndarray) -> float:
    """
    Mahalanobis distance using diagonal covariance.
    var is per-feature variance (std**2). Near-zero variances are clamped.
    """
    safe_var = np.where(var < 1e-10, 1e-10, var)
    diff = x - mean
    return float(np.sqrt(np.sum(diff ** 2 / safe_var)))


def _alert_level(wear_score: float) -> str:
    for level, (lo, hi) in ALERT_THRESHOLDS.items():
        if lo <= wear_score < hi:
            return level
    return "CRITICAL"


# ---------------------------------------------------------------------------
# Per-tool state
# ---------------------------------------------------------------------------

@dataclass
class ToolState:
    tool_id: str
    machine_id: int
    material: str = "steel"

    # Baseline (learned from first MIN_BASELINE_READINGS)
    baseline_mean: Optional[np.ndarray] = field(default=None, repr=False)
    baseline_var: Optional[np.ndarray] = field(default=None, repr=False)
    _baseline_buffer: List[np.ndarray] = field(default_factory=list, repr=False)

    # Wear tracking
    wear_score_ema: float = 0.0          # 0-100 EMA-smoothed
    raw_scores: List[float] = field(default_factory=list)  # history for RUL
    reading_times: List[datetime] = field(default_factory=list)

    # Registration metadata
    registered_at: datetime = field(default_factory=_now)
    tool_type: str = "end_mill"
    expected_life_minutes: float = 480.0  # 8 hours typical end mill life

    @property
    def is_baseline_ready(self) -> bool:
        return self.baseline_mean is not None

    def ingest(self, feat: np.ndarray, ts: datetime) -> float:
        """
        Add one feature vector. If baseline not ready, accumulate.
        Returns current wear_score_ema (0 if still learning baseline).
        """
        if not self.is_baseline_ready:
            self._baseline_buffer.append(feat)
            if len(self._baseline_buffer) >= MIN_BASELINE_READINGS:
                arr = np.stack(self._baseline_buffer)
                self.baseline_mean = arr.mean(axis=0)
                self.baseline_var = arr.var(axis=0)
                self._baseline_buffer.clear()
            return 0.0

        dist = _mahalanobis_diagonal(feat, self.baseline_mean, self.baseline_var)
        # Normalise distance to 0-100 score. Distance >5 σ = score ~100.
        raw_score = min(100.0, dist * 20.0)
        # EMA smoothing
        self.wear_score_ema = EMA_ALPHA * raw_score + (1 - EMA_ALPHA) * self.wear_score_ema

        self.raw_scores.append(self.wear_score_ema)
        self.reading_times.append(ts)
        return self.wear_score_ema

    def rul_minutes(self) -> Tuple[Optional[float], float]:
        """
        Predict remaining useful life in minutes using linear regression
        on the last RUL_WINDOW wear scores.

        Returns (rul_minutes, confidence) where confidence is R² ∈ [0, 1].
        Returns (None, 0.0) if not enough data.
        """
        window = min(RUL_WINDOW, len(self.raw_scores))
        if window < 5:
            return None, 0.0

        scores = self.raw_scores[-window:]
        x = np.arange(len(scores), dtype=float)
        result = scipy_stats.linregress(x, scores)
        slope = result.slope
        r2 = max(0.0, result.rvalue ** 2)

        if slope <= 0:
            # Tool condition stable or improving — no finite RUL
            return None, r2

        # Readings per minute estimate — use timestamps if available
        times = self.reading_times[-window:]
        if len(times) >= 2:
            duration_min = (times[-1] - times[0]).total_seconds() / 60.0
            if duration_min > 0:
                slope_per_min = slope * (len(scores) / duration_min)
            else:
                slope_per_min = slope
        else:
            slope_per_min = slope

        remaining_score = 100.0 - self.wear_score_ema
        if slope_per_min <= 0:
            return None, r2

        rul = remaining_score / slope_per_min
        return max(0.0, rul), r2

    @property
    def alert_level(self) -> str:
        return _alert_level(self.wear_score_ema)

    def should_change_before_job(self, job_duration_minutes: float) -> bool:
        """True if predicted RUL < job_duration * safety_margin."""
        if self.wear_score_ema >= 90.0:
            return True
        rul, confidence = self.rul_minutes()
        if rul is None:
            return self.wear_score_ema >= 70.0
        if confidence < 0.5:
            # Low-confidence regression — only force change at RED
            return self.wear_score_ema >= 70.0
        return rul < job_duration_minutes * CHANGE_SAFETY_MARGIN

    def reset(self) -> None:
        """Call after physical tool change — resets wear tracking."""
        self.baseline_mean = None
        self.baseline_var = None
        self._baseline_buffer.clear()
        self.wear_score_ema = 0.0
        self.raw_scores.clear()
        self.reading_times.clear()


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class ToolWearAgent:
    """
    Manages per-tool state for all registered tools.

    All methods are synchronous and stateless w.r.t. the DB — the router
    layer handles persistence via SensorReading / ToolRecord ORM models.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolState] = {}

    # ------------------------------------------------------------------ #
    # Registration                                                        #
    # ------------------------------------------------------------------ #

    def register_tool(
        self,
        tool_id: str,
        machine_id: int,
        tool_type: str = "end_mill",
        material: str = "steel",
        expected_life_minutes: float = 480.0,
    ) -> ToolState:
        state = ToolState(
            tool_id=tool_id,
            machine_id=machine_id,
            tool_type=tool_type,
            material=material,
            expected_life_minutes=expected_life_minutes,
        )
        self._tools[tool_id] = state
        return state

    def get_tool(self, tool_id: str) -> Optional[ToolState]:
        return self._tools.get(tool_id)

    def list_tools(self) -> List[ToolState]:
        return list(self._tools.values())

    def reset_tool(self, tool_id: str) -> bool:
        """Call after physical tool change. Returns False if tool not found."""
        state = self._tools.get(tool_id)
        if state is None:
            return False
        state.reset()
        return True

    # ------------------------------------------------------------------ #
    # Ingestion                                                           #
    # ------------------------------------------------------------------ #

    def ingest_reading(
        self,
        tool_id: str,
        reading: dict,
        ts: Optional[datetime] = None,
    ) -> Optional[float]:
        """
        Process one sensor reading for tool_id.

        Returns wear_score_ema, or None if tool not registered.
        """
        state = self._tools.get(tool_id)
        if state is None:
            return None
        feat = _feature_vector(reading)
        return state.ingest(feat, ts or _now())

    # ------------------------------------------------------------------ #
    # Status                                                              #
    # ------------------------------------------------------------------ #

    def tool_status(self, tool_id: str) -> Optional[dict]:
        state = self._tools.get(tool_id)
        if state is None:
            return None
        rul, conf = state.rul_minutes()
        return {
            "tool_id": tool_id,
            "machine_id": state.machine_id,
            "tool_type": state.tool_type,
            "material": state.material,
            "wear_score": round(state.wear_score_ema, 2),
            "alert_level": state.alert_level,
            "rul_minutes": round(rul, 1) if rul is not None else None,
            "rul_confidence": round(conf, 3),
            "baseline_ready": state.is_baseline_ready,
            "reading_count": len(state.raw_scores),
            "registered_at": state.registered_at.isoformat(),
        }

    def fleet_status(self) -> List[dict]:
        return [self.tool_status(tid) for tid in self._tools]

    # ------------------------------------------------------------------ #
    # Change recommendation                                               #
    # ------------------------------------------------------------------ #

    def change_recommendation(self, tool_id: str, job_duration_minutes: float) -> dict:
        state = self._tools.get(tool_id)
        if state is None:
            return {"tool_id": tool_id, "change_required": False, "reason": "tool_not_found"}
        rul, conf = state.rul_minutes()
        change = state.should_change_before_job(job_duration_minutes)
        reason = "ok"
        if state.wear_score_ema >= 90.0:
            reason = "critical_wear"
        elif rul is not None and rul < job_duration_minutes * CHANGE_SAFETY_MARGIN:
            reason = f"rul_{round(rul)}min_below_job_{round(job_duration_minutes)}min"
        elif state.wear_score_ema >= 70.0:
            reason = "red_alert_threshold"
        return {
            "tool_id": tool_id,
            "machine_id": state.machine_id,
            "change_required": change,
            "wear_score": round(state.wear_score_ema, 2),
            "alert_level": state.alert_level,
            "rul_minutes": round(rul, 1) if rul is not None else None,
            "rul_confidence": round(conf, 3),
            "reason": reason,
            "job_duration_minutes": job_duration_minutes,
        }

    # ------------------------------------------------------------------ #
    # Simulation (for demo / testing)                                     #
    # ------------------------------------------------------------------ #

    def simulate_wear_progression(
        self,
        tool_id: str,
        steps: int = 30,
        noise_level: float = 0.05,
        drift_rate: float = 0.04,
    ) -> List[float]:
        """
        Inject synthetic wear progression readings into a tool and return
        the wear score history. Used by /simulate endpoint.

        Simulates linear spectral drift with noise. Registers tool if missing.
        """
        if tool_id not in self._tools:
            self.register_tool(tool_id, machine_id=1)

        state = self._tools[tool_id]
        state.reset()

        rng = np.random.default_rng(seed=42)
        scores: List[float] = []
        base = np.ones(22)

        for i in range(steps):
            drift = drift_rate * i
            noise = rng.normal(0, noise_level, 22)
            reading_arr = base + drift + noise

            # Inject first 10 as clean baseline (no drift)
            if i < 10:
                reading_arr = base + rng.normal(0, noise_level * 0.5, 22)

            feat = np.abs(reading_arr)
            score = state.ingest(feat, _now())
            scores.append(round(score, 2))

        return scores
