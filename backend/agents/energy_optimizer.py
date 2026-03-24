"""
MillForge Energy Optimizer Agent

Fetches real LMP (Locational Marginal Price) data from PJM via the
gridstatus open-source library. Falls back to a simulated curve if
gridstatus is unavailable or the network call fails.

Energy intelligence capabilities:
  - Real-time PJM LMP pricing (1-hour TTL cache)
  - Negative pricing window detection
  - Energy arbitrage modeling (mill as grid asset)
  - On-site generation scenario NPV (solar / battery / wind / SMR)
  - Carbon footprint tracking (Electricity Maps API → EPA 2023 fallback)
  - Schedule-level energy analysis (current cost vs optimal, carbon delta)
"""

import json
import logging
import time
import urllib.request
import os
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
# Carbon intensity — EPA 2023 US average grid (kg CO2/kWh)
# Electricity Maps API (optional): ELECTRICITY_MAPS_API_KEY env var
# ---------------------------------------------------------------------------
US_GRID_CARBON_INTENSITY = 0.386  # kg CO2/kWh (EPA 2023, US average)

_carbon_cache: Dict = {"intensity": None, "fetched_at": None}


def _fetch_carbon_intensity() -> Optional[float]:
    """
    Fetch real-time carbon intensity from Electricity Maps API (PJM Mid-Atlantic zone).
    Returns kg CO2/kWh, or None on failure.
    """
    try:
        api_key = os.getenv("ELECTRICITY_MAPS_API_KEY", "").strip()
        if not api_key:
            return None
        url = "https://api.electricitymap.org/v3/carbon-intensity/latest?zone=US-MIDA-PJM"
        req = urllib.request.Request(url, headers={"auth-token": api_key})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data["carbonIntensity"] / 1000.0  # gCO2/kWh → kgCO2/kWh
    except Exception as exc:
        logger.debug("Electricity Maps fetch failed (%s) — using EPA constant", exc)
        return None


def _get_carbon_intensity() -> tuple[float, str]:
    """Return (kg_co2_per_kwh, data_source). Cached for 1 hour."""
    now = time.monotonic()
    if _carbon_cache["fetched_at"] and now - _carbon_cache["fetched_at"] < _CACHE_TTL:
        return _carbon_cache["intensity"], _carbon_cache["data_source"]
    live = _fetch_carbon_intensity()
    if live is not None:
        _carbon_cache["intensity"] = live
        _carbon_cache["fetched_at"] = now
        _carbon_cache["data_source"] = "electricity_maps"
        return live, "electricity_maps"
    _carbon_cache["intensity"] = US_GRID_CARBON_INTENSITY
    _carbon_cache["fetched_at"] = now
    _carbon_cache["data_source"] = "epa_2023_average"
    return US_GRID_CARBON_INTENSITY, "epa_2023_average"


# ---------------------------------------------------------------------------
# On-site generation scenario defaults (capex, LCOE, discount rate)
# ---------------------------------------------------------------------------
SCENARIO_DEFAULTS: Dict = {
    "solar":         {"capex_usd": 600_000,   "lcoe": 0.045, "discount_rate": 0.08},
    "battery":       {"capex_usd": 400_000,   "lcoe": 0.060, "discount_rate": 0.08},
    "solar_battery": {"capex_usd": 900_000,   "lcoe": 0.050, "discount_rate": 0.08},
    "wind":          {"capex_usd": 1_500_000, "lcoe": 0.035, "discount_rate": 0.08},
    "smr":           {"capex_usd": 5_000_000, "lcoe": 0.065, "discount_rate": 0.06},
    "grid_only":     {"capex_usd": 0,         "lcoe": None,  "discount_rate": 0.08},
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
    Discards result if any prices are negative (use _fetch_pjm_lmp_raw for those).
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


def _fetch_pjm_lmp_raw() -> Optional[List[float]]:
    """
    Like _fetch_pjm_lmp but preserves negative values.
    Used for negative pricing window detection.
    Returns None on any failure.
    """
    try:
        import gridstatus  # noqa: PLC0415
        pjm = gridstatus.PJM()
        df = pjm.get_lmp(
            date="today",
            market="REAL_TIME_5_MIN",
            locations=["AEP"],
        )
        df = df.copy()
        df["hour"] = df["time"].dt.hour
        hourly = df.groupby("hour")["lmp"].mean()
        mean_lmp = hourly.mean()
        rates_mwh = [hourly.get(h, mean_lmp) for h in range(24)]
        return [r / 1000.0 for r in rates_mwh]  # keep negatives
    except Exception as exc:
        logger.debug("PJM raw fetch failed (%s)", exc)
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

    # ---------------------------------------------------------------------------
    # Section 1: Schedule-level energy analysis
    # ---------------------------------------------------------------------------

    def compute_schedule_energy_analysis(
        self,
        scheduled_orders: list,  # List[ScheduledOrder] from agents.scheduler
        battery_soc_percent: Optional[float] = None,
    ) -> Dict:
        """
        Compute energy cost for a full schedule and compare to optimal (cheapest window).

        Returns a dict with:
          total_energy_kwh, current_schedule_cost_usd, optimal_schedule_cost_usd,
          potential_savings_usd, carbon_footprint_kg_co2, carbon_data_source,
          data_source, battery_recommendation (if soc provided).
        """
        self._refresh_rates()
        carbon_intensity, carbon_source = _get_carbon_intensity()

        total_kwh = 0.0
        total_cost = 0.0
        min_rate = min(self.hourly_rates)
        optimal_cost = 0.0

        for s in scheduled_orders:
            duration_h = (s.completion_time - s.setup_start).total_seconds() / 3600
            material = s.order.material.lower()
            power_kw = MACHINE_POWER_KW.get(material, MACHINE_POWER_KW["default"])

            profile = self._do_estimate(s.setup_start, duration_h, material)
            total_kwh += profile.estimated_kwh
            total_cost += profile.estimated_cost_usd
            optimal_cost += power_kw * duration_h * min_rate

        carbon_kg = total_kwh * carbon_intensity
        # Carbon saved vs optimal (cheapest window also has lowest marginal carbon)
        carbon_optimal = total_kwh * carbon_intensity * (optimal_cost / total_cost if total_cost > 0 else 1.0)
        carbon_delta = round(carbon_kg - carbon_optimal, 3)

        result: Dict = {
            "total_energy_kwh": round(total_kwh, 2),
            "current_schedule_cost_usd": round(total_cost, 2),
            "optimal_schedule_cost_usd": round(optimal_cost, 2),
            "potential_savings_usd": round(max(0.0, total_cost - optimal_cost), 2),
            "carbon_footprint_kg_co2": round(carbon_kg, 3),
            "carbon_delta_kg_co2": round(max(0.0, carbon_delta), 3),
            "carbon_data_source": carbon_source,
            "data_source": self.data_source,
        }

        if battery_soc_percent is not None:
            soc = battery_soc_percent
            if soc > 50:
                msg = f"Battery SOC {soc:.0f}% — prioritize stored energy for peak-hour jobs to maximize savings."
            elif soc < 20:
                msg = f"Battery SOC {soc:.0f}% — schedule energy-intensive runs during off-peak to recharge."
            else:
                msg = f"Battery SOC {soc:.0f}% — nominal. No immediate action required."
            result["battery_recommendation"] = msg

        return result

    # ---------------------------------------------------------------------------
    # Section 2: Negative pricing window detection
    # ---------------------------------------------------------------------------

    def get_negative_pricing_windows(self) -> Dict:
        """
        Return hours where PJM LMP is negative (grid pays you to consume).
        Uses raw PJM data (including negatives). Falls back to mock if unavailable.
        """
        raw = _fetch_pjm_lmp_raw()
        if raw is not None:
            windows = [
                {"hour": h, "rate_usd_per_kwh": round(r, 5), "duration_hours": 1}
                for h, r in enumerate(raw) if r < 0
            ]
            max_credit = abs(min(raw)) * 1000.0 if any(r < 0 for r in raw) else 0.0
            data_source = "PJM_realtime"
        else:
            # Mock data has no negatives; return empty result for fallback
            windows = []
            max_credit = 0.0
            data_source = "simulated_fallback"

        return {
            "windows": windows,
            "total_windows": len(windows),
            "max_credit_usd_per_mwh": round(max_credit, 2),
            "recommendation": (
                f"{len(windows)} negative-price window(s) detected — "
                "schedule high-load jobs now to earn grid credits."
                if windows
                else "No negative pricing windows detected. Monitor for curtailment events."
            ),
            "data_source": data_source,
        }

    # ---------------------------------------------------------------------------
    # Section 3: Energy arbitrage modeling (mill as grid asset)
    # ---------------------------------------------------------------------------

    def get_arbitrage_analysis(
        self,
        daily_energy_kwh: float,
        flexible_load_percent: float = 0.3,
    ) -> Dict:
        """
        Model the mill as a grid-responsive asset.

        Computes the annual savings achievable by shifting `flexible_load_percent`
        of daily energy consumption from peak to off-peak hours (demand response).
        """
        self._refresh_rates()
        rates = self.hourly_rates

        # Peak = top-4 hours; off-peak = bottom-4 hours
        peak_hours = sorted(range(24), key=lambda h: rates[h], reverse=True)[:4]
        off_peak_hours = sorted(range(24), key=lambda h: rates[h])[:4]

        peak_avg = sum(rates[h] for h in peak_hours) / 4
        off_peak_avg = sum(rates[h] for h in off_peak_hours) / 4
        delta = peak_avg - off_peak_avg

        flexible_kwh = daily_energy_kwh * flexible_load_percent
        daily_savings = flexible_kwh * delta
        annual_savings = daily_savings * 250  # ~250 operating days/year

        return {
            "daily_energy_kwh": round(daily_energy_kwh, 1),
            "flexible_load_percent": round(flexible_load_percent * 100, 1),
            "flexible_kwh_per_day": round(flexible_kwh, 1),
            "daily_savings_usd": round(daily_savings, 2),
            "annual_savings_usd": round(annual_savings, 2),
            "peak_to_offpeak_delta_usd_per_kwh": round(delta, 4),
            "optimal_shift_hours": off_peak_hours,
            "peak_hours": peak_hours,
            "data_source": self.data_source,
        }

    # ---------------------------------------------------------------------------
    # Section 4: On-site generation scenario NPV
    # ---------------------------------------------------------------------------

    def get_scenario_npv(
        self,
        scenario: str,
        annual_energy_kwh: float,
        capex_usd: Optional[float] = None,
    ) -> Dict:
        """
        10-year NPV analysis for on-site generation vs grid-only.

        Supported scenarios: solar, battery, solar_battery, wind, smr, grid_only.
        LCOE values are US averages (2024 LAZARD LCOE v17).
        """
        self._refresh_rates()
        defaults = SCENARIO_DEFAULTS.get(scenario, SCENARIO_DEFAULTS["grid_only"])
        grid_rate = sum(self.hourly_rates) / len(self.hourly_rates)

        if scenario == "grid_only":
            annual_cost = annual_energy_kwh * grid_rate
            return {
                "scenario": "grid_only",
                "capex_usd": 0.0,
                "annual_energy_cost_usd": round(annual_cost, 2),
                "annual_savings_usd": 0.0,
                "payback_years": None,
                "npv_10yr_usd": 0.0,
                "lcoe_usd_per_kwh": round(grid_rate, 4),
                "recommendation": (
                    f"Grid-only baseline: ${annual_cost:,.0f}/yr. "
                    "Compare against on-site generation scenarios."
                ),
                "data_source": self.data_source,
            }

        lcoe = defaults["lcoe"]
        effective_capex = capex_usd if capex_usd is not None else defaults["capex_usd"]
        discount_rate = defaults["discount_rate"]

        # Annual savings = energy × (grid_rate - lcoe)
        annual_savings = annual_energy_kwh * (grid_rate - lcoe)
        payback_years = (
            round(effective_capex / annual_savings, 1)
            if annual_savings > 0 else None
        )

        # 10-year NPV
        npv = -effective_capex + sum(
            annual_savings / (1 + discount_rate) ** yr
            for yr in range(1, 11)
        )

        roi_msg = "Positive 10-yr ROI." if npv > 0 else "Negative 10-yr ROI at current grid rates."
        payback_msg = f"Payback: {payback_years} yr." if payback_years else "No payback (negative savings)."

        return {
            "scenario": scenario,
            "capex_usd": round(effective_capex, 0),
            "annual_savings_usd": round(annual_savings, 2),
            "payback_years": payback_years,
            "npv_10yr_usd": round(npv, 2),
            "lcoe_usd_per_kwh": lcoe,
            "recommendation": f"10-yr NPV ${npv:,.0f}. {payback_msg} {roi_msg}",
            "data_source": self.data_source,
        }

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
