"""
MillForge Energy Optimizer Agent

Placeholder for energy-aware production scheduling.
Will integrate real-time energy pricing and machine power profiles
to minimize cost and carbon footprint.
"""

import logging
from dataclasses import dataclass
from typing import List, Dict
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# Simulated hourly energy prices ($/kWh) for a 24-hour window
# In production this would come from a grid pricing API
MOCK_HOURLY_RATES = [
    0.08, 0.07, 0.07, 0.06, 0.06, 0.07,  # 00:00 – 05:00 (off-peak)
    0.09, 0.12, 0.15, 0.16, 0.15, 0.14,  # 06:00 – 11:00 (morning ramp)
    0.14, 0.13, 0.14, 0.16, 0.18, 0.19,  # 12:00 – 17:00 (peak)
    0.17, 0.14, 0.12, 0.11, 0.10, 0.09,  # 18:00 – 23:00 (evening taper)
]

# Machine power draw in kW by operation type
MACHINE_POWER_KW: Dict[str, float] = {
    "steel": 85.0,
    "aluminum": 55.0,
    "titanium": 110.0,
    "copper": 65.0,
    "default": 70.0,
}


@dataclass
class EnergyProfile:
    """Energy usage and cost estimate for a production window."""
    start_time: datetime
    end_time: datetime
    material: str
    estimated_kwh: float
    estimated_cost_usd: float
    peak_rate: float
    off_peak_rate: float
    recommendation: str

    def to_dict(self) -> dict:
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "material": self.material,
            "estimated_kwh": round(self.estimated_kwh, 2),
            "estimated_cost_usd": round(self.estimated_cost_usd, 2),
            "peak_rate": self.peak_rate,
            "off_peak_rate": self.off_peak_rate,
            "recommendation": self.recommendation,
        }


class EnergyOptimizer:
    """
    Energy Optimizer Agent.

    Current state: Heuristic implementation using simulated energy prices.

    Planned implementation:
    - Integrate with grid pricing API (e.g., CAISO, ERCOT, or EnergyHub)
    - Fetch real-time and day-ahead electricity prices
    - Model machine-level power draw from sensor telemetry
    - Shift non-critical jobs to off-peak windows using a MILP formulation
    - Provide carbon intensity scores alongside cost estimates
    """

    def __init__(self):
        self.hourly_rates = MOCK_HOURLY_RATES
        logger.info("EnergyOptimizer initialized")

    def estimate_energy_cost(
        self,
        start_time: datetime,
        duration_hours: float,
        material: str,
    ) -> EnergyProfile:
        """
        Estimate energy cost for a production run.

        Args:
            start_time: When the machine starts running.
            duration_hours: How long the run takes.
            material: Material being processed (determines power draw).

        Returns:
            EnergyProfile with cost estimates and optimization recommendation.
        """
        power_kw = MACHINE_POWER_KW.get(material.lower(), MACHINE_POWER_KW["default"])
        total_kwh = power_kw * duration_hours

        # Calculate weighted average rate across the window
        total_cost = 0.0
        hours_accounted = 0.0
        current = start_time

        while hours_accounted < duration_hours:
            hour_idx = current.hour % 24
            rate = self.hourly_rates[hour_idx]
            chunk = min(1.0, duration_hours - hours_accounted)
            total_cost += power_kw * chunk * rate
            hours_accounted += chunk
            current += timedelta(hours=chunk)

        end_time = start_time + timedelta(hours=duration_hours)
        peak_rate = max(self.hourly_rates)
        off_peak_rate = min(self.hourly_rates)

        # Simple recommendation: flag runs that start during peak hours
        start_hour = start_time.hour
        if self.hourly_rates[start_hour] >= 0.15:
            recommendation = (
                f"Consider shifting this {material} run to off-peak hours "
                f"(00:00–06:00) to save ~{self._saving_estimate(duration_hours, power_kw):.2f} USD."
            )
        else:
            recommendation = "Run is scheduled during favorable energy pricing window."

        return EnergyProfile(
            start_time=start_time,
            end_time=end_time,
            material=material,
            estimated_kwh=total_kwh,
            estimated_cost_usd=total_cost,
            peak_rate=peak_rate,
            off_peak_rate=off_peak_rate,
            recommendation=recommendation,
        )

    def _saving_estimate(self, hours: float, power_kw: float) -> float:
        """Estimate savings by running at off-peak vs current peak rate."""
        peak = max(self.hourly_rates)
        off_peak = min(self.hourly_rates)
        return power_kw * hours * (peak - off_peak)

    def get_optimal_start_windows(
        self, duration_hours: float, material: str, lookahead_hours: int = 24
    ) -> List[Dict]:
        """
        Return the cheapest time windows within the next `lookahead_hours`.

        Args:
            duration_hours: Required production window length.
            material: Material type.
            lookahead_hours: How far ahead to look.

        Returns:
            List of dicts with start_hour, estimated_cost, sorted ascending by cost.
        """
        power_kw = MACHINE_POWER_KW.get(material.lower(), MACHINE_POWER_KW["default"])
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        windows = []

        for offset in range(lookahead_hours):
            candidate_start = now + timedelta(hours=offset)
            profile = self.estimate_energy_cost(candidate_start, duration_hours, material)
            windows.append({
                "start_time": candidate_start.isoformat(),
                "estimated_cost_usd": round(profile.estimated_cost_usd, 2),
                "estimated_kwh": round(profile.estimated_kwh, 2),
            })

        return sorted(windows, key=lambda w: w["estimated_cost_usd"])[:5]
