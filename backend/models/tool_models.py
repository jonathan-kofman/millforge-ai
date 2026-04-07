"""
Pydantic schemas for the Tool Wear Monitoring system.

Separate from schemas.py to keep that file focused on core scheduling/quoting.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Inbound
# ---------------------------------------------------------------------------

class SpectralReading(BaseModel):
    """22-feature sensor snapshot from a CNC machine."""

    vibration_rms: float = Field(..., ge=0, description="Vibration RMS amplitude")
    vibration_peak_freq: float = Field(..., ge=0, description="Peak vibration frequency (Hz)")
    vibration_band_energy_0: float = Field(0.0, ge=0)
    vibration_band_energy_1: float = Field(0.0, ge=0)
    vibration_band_energy_2: float = Field(0.0, ge=0)
    vibration_band_energy_3: float = Field(0.0, ge=0)
    vibration_band_energy_4: float = Field(0.0, ge=0)
    vibration_band_energy_5: float = Field(0.0, ge=0)
    vibration_band_energy_6: float = Field(0.0, ge=0)
    vibration_band_energy_7: float = Field(0.0, ge=0)
    acoustic_rms: float = Field(..., ge=0, description="Acoustic emission RMS")
    acoustic_peak_freq: float = Field(..., ge=0, description="Peak acoustic frequency (Hz)")
    acoustic_band_energy_0: float = Field(0.0, ge=0)
    acoustic_band_energy_1: float = Field(0.0, ge=0)
    acoustic_band_energy_2: float = Field(0.0, ge=0)
    acoustic_band_energy_3: float = Field(0.0, ge=0)
    acoustic_band_energy_4: float = Field(0.0, ge=0)
    acoustic_band_energy_5: float = Field(0.0, ge=0)
    acoustic_band_energy_6: float = Field(0.0, ge=0)
    acoustic_band_energy_7: float = Field(0.0, ge=0)
    spindle_load_pct: float = Field(..., ge=0, le=200, description="Spindle load %")
    feed_rate_actual: float = Field(..., ge=0, description="Actual feed rate mm/min")


class WearReading(BaseModel):
    """Sensor snapshot submitted by machine or operator."""

    tool_id: str
    reading: SpectralReading
    timestamp: Optional[datetime] = None


class ToolRegisterRequest(BaseModel):
    tool_id: str
    machine_id: int = Field(..., ge=1)
    tool_type: str = "end_mill"
    material: str = "steel"
    expected_life_minutes: float = Field(480.0, gt=0)


# ---------------------------------------------------------------------------
# Outbound
# ---------------------------------------------------------------------------

class ToolStatus(BaseModel):
    tool_id: str
    machine_id: int
    tool_type: str
    material: str
    wear_score: float = Field(..., description="0-100 EMA-smoothed wear score")
    alert_level: str = Field(..., description="GREEN | YELLOW | RED | CRITICAL")
    rul_minutes: Optional[float] = Field(None, description="Predicted remaining useful life")
    rul_confidence: float = Field(0.0, description="R² of RUL regression [0, 1]")
    baseline_ready: bool
    reading_count: int
    registered_at: str


class ToolChangeRecommendation(BaseModel):
    tool_id: str
    machine_id: int
    change_required: bool
    wear_score: float
    alert_level: str
    rul_minutes: Optional[float]
    rul_confidence: float
    reason: str
    job_duration_minutes: float


class SimulateResponse(BaseModel):
    tool_id: str
    wear_scores: List[float]
    final_wear_score: float
    final_alert_level: str
    message: str
