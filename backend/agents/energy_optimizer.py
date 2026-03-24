"""
MillForge Energy Optimizer Agent

Fetches real LMP (Locational Marginal Price) data from PJM via the
gridstatus open-source library. Falls back to a simulated curve if
gridstatus is unavailable or the network call fails.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Simulated fallback (used when gridstatus / network is unavailable)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# PJM LMP cache — module-level, 1-hour TTL
# ---------------------------------------------------------------------------
_CACHE_TTL = 3600  # seconds

_rates_cache: Dict = {
    "rates": None,        # List[float] | None
    "fetched_at": None,   # float (time.monotonic()) | None
    "data_source": "simulated_fallback",
}


def _fetch_pjm_lmp() -> Optional[List[float]]:
    """
    Fetch today's PJM real-time 5-min LMP for the AEP hub, aggregate to
    hourly averages, convert $/MWh → $/kWh, and return a 24-element list.

    Returns None on any failure — caller falls back to MOCK_HOURLY_RATES.
    """
    try:
        import gridstatus  # noqa: PLC0415
        pjm = gridstatus.PJM()
        df = pjm.get_lmp(
            date="today",
            market="REAL_TIME_5_MIN",
            locations=["AEP"],
        )
        # df has columns: time, location, lmp, energy, congestion, loss
        df = df.copy()
        df["hour"] = df["time"].dt.hour
        hourly = df.groupby("hour")["lmp"].mean()

        # Build a full 24-hour list; fill missing hours with mean
        mean_lmp = hourly.mean()
        rates_mwh = [hourly.get(h, mean_lmp) for h in range(24)]
        rates_kwh = [r / 1000.0 for r in rates_mwh]

        # Sanity check: PJM LMP is usually $10–$200/MWh → $0.01–$0.20/kWh
        if any(r < 0 for r in rates_kwh):
            logger.warning("PJM LMP contains negative prices — using simulated fallback")
            return None

        logger.info("PJM LMP fetched successfully (mean=%.4f $/kWh)", sum(rates_kwh) / 24)
        return rates_kwh

    except Exception as exc:
        logger.warning("gridstatus/PJM fetch failed (%s) — using simulated fallback", exc)
        return None


def _get_hourly_rates() -> tuple[List[float], str]:
    """
    Return (hourly_rates, data_source).  Uses module-level cache with 1-hour TTL.
    """
    now = time.monotonic()
    cached_at = _rates_cache["fetched_at"]
    if cached_at is not None and (now - cached_at) < _CACHE_TTL and _rates_cache["rates"]:
        return _rates_cache["rates"], _rates_cache["data_source"]

    # Cache miss or expired — try to fetch live data
    live = _fetch_pjm_lmp()
    if live is not None:
        _rates_cache["rates"] = live
        _rates_cache["fetched_at"] = now
        _rates_cache["data_source"] = "PJM_realtime"
        return live, "PJM_realtime"

    # Fallback
    _rates_cache["rates"] = MOCK_HOURLY_RATES
    _rates_cache["fetched_at"] = now
    _rates_cache["data_source"] = "simulated_fallback"
    return MOCK_HOURLY_RATES, "simulated_fallback"


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

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
    data_source: str = "simulated_fallback"
    validation_failures: List[str] = field(default_factory=list)

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
            "data_source": self.data_source,
        }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class EnergyOptimizer:
    """
    Energy Optimizer Agent.

    Fetches real PJM LMP data via the gridstatus open-source library and
    uses it to recommend energy-optimal production windows. Falls back to
    a simulated 24-hour pricing curve when live data is unavailable.

    Validation loop: output is validated after each attempt; retried up to
    MAX_RETRIES times before returning the best result with validation_failures.
    """

    MAX_RETRIES = 3

    def __init__(self):
        # Eagerly populate cache so the first API call is fast
        self.hourly_rates, self.data_source = _get_hourly_rates()
        logger.info(
            "EnergyOptimizer initialized (data_source=%s)", self.data_source
        )

    def _refresh_rates(self) -> None:
        """Refresh rates from cache (may fetch live data if TTL expired)."""
        self.hourly_rates, self.data_source = _get_hourly_rates()

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
        self._refresh_rates()

        failures: List[str] = []
        best: Optional[EnergyProfile] = None

        for attempt in range(self.MAX_RETRIES):
            profile = self._do_estimate(start_time, duration_hours, material)
            errors = self._validate_profile(profile, duration_hours)

            if not errors:
                profile.validation_failures = []
                return profile

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = profile
            logger.warning(
                "Energy profile validation failed attempt %d: %s", attempt + 1, errors
            )

        assert best is not None
        best.validation_failures = failures
        return best

    def _validate_profile(self, profile: EnergyProfile, duration_hours: float) -> List[str]:
        """Return a list of constraint violations (empty = valid)."""
        errors: List[str] = []

        if profile.estimated_kwh < 0:
            errors.append(f"estimated_kwh is negative: {profile.estimated_kwh}")

        if profile.estimated_cost_usd < 0:
            errors.append(f"estimated_cost_usd is negative: {profile.estimated_cost_usd}")

        if profile.peak_rate < profile.off_peak_rate:
            errors.append(
                f"peak_rate ({profile.peak_rate}) < off_peak_rate ({profile.off_peak_rate})"
            )

        if profile.end_time <= profile.start_time:
            errors.append("end_time is not after start_time")

        return errors

    def _do_estimate(
        self,
        start_time: datetime,
        duration_hours: float,
        material: str,
    ) -> EnergyProfile:
        """Core energy estimation logic."""
        rates = self.hourly_rates
        power_kw = MACHINE_POWER_KW.get(material.lower(), MACHINE_POWER_KW["default"])
        total_kwh = power_kw * duration_hours

        # Calculate weighted average rate across the window
        total_cost = 0.0
        hours_accounted = 0.0
        current = start_time

        while hours_accounted < duration_hours:
            hour_idx = current.hour % 24
            rate = rates[hour_idx]
            chunk = min(1.0, duration_hours - hours_accounted)
            total_cost += power_kw * chunk * rate
            hours_accounted += chunk
            current += timedelta(hours=chunk)

        end_time = start_time + timedelta(hours=duration_hours)
        peak_rate = max(rates)
        off_peak_rate = min(rates)

        # Recommendation: flag runs above the mean rate (works for both real
        # and simulated data — avoids hardcoded $/kWh thresholds)
        mean_rate = sum(rates) / len(rates)
        start_hour = start_time.hour
        if rates[start_hour] > mean_rate:
            recommendation = (
                f"Consider shifting this {material} run to off-peak hours "
                f"to save ~{self._saving_estimate(duration_hours, power_kw, rates):.2f} USD."
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
            data_source=self.data_source,
        )

    def _saving_estimate(self, hours: float, power_kw: float, rates: List[float]) -> float:
        """Estimate savings by running at off-peak vs current peak rate."""
        peak = max(rates)
        off_peak = min(rates)
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
        self._refresh_rates()
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        windows = []

        for offset in range(lookahead_hours):
            candidate_start = now + timedelta(hours=offset)
            profile = self.estimate_energy_cost(candidate_start, duration_hours, material)
            windows.append({
                "start_time": candidate_start.isoformat(),
                "estimated_cost_usd": round(profile.estimated_cost_usd, 2),
                "estimated_kwh": round(profile.estimated_kwh, 2),
                "data_source": profile.data_source,
            })

        return sorted(windows, key=lambda w: w["estimated_cost_usd"])[:5]
