"""
/api/energy endpoints — energy cost estimation, negative pricing, arbitrage, and on-site generation scenarios.
"""

import logging
import os
from fastapi import APIRouter, HTTPException

from models.schemas import (
    EnergyEstimateRequest, EnergyEstimateResponse,
    NegativePricingResponse, NegativePricingWindow,
    ArbitrageRequest, ArbitrageResponse,
    ScenarioRequest, ScenarioResponse,
)
from agents.energy_optimizer import EnergyOptimizer, _get_hourly_rates as _fetch_rates

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/energy", tags=["Energy"])

_optimizer = EnergyOptimizer()


@router.post(
    "/estimate",
    response_model=EnergyEstimateResponse,
    summary="Estimate energy cost for a production run",
)
async def estimate_energy(req: EnergyEstimateRequest) -> EnergyEstimateResponse:
    """
    Estimate the energy cost for a machine run of the given material and duration.
    Returns kWh, USD cost, and an optimization recommendation.
    """
    logger.info(
        "Energy estimate: material=%s duration=%.1fh start=%s",
        req.material.value, req.duration_hours, req.start_time.isoformat(),
    )
    try:
        start = req.start_time.replace(tzinfo=None) if req.start_time.tzinfo else req.start_time
        profile = _optimizer.estimate_energy_cost(start, req.duration_hours, req.material.value)
    except Exception as exc:
        logger.error("Energy estimate error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Energy estimation error")

    response = EnergyEstimateResponse(
        start_time=profile.start_time,
        end_time=profile.end_time,
        material=profile.material,
        estimated_kwh=round(profile.estimated_kwh, 2),
        estimated_cost_usd=round(profile.estimated_cost_usd, 2),
        peak_rate=profile.peak_rate,
        off_peak_rate=profile.off_peak_rate,
        recommendation=profile.recommendation,
        data_source=profile.data_source,
        validation_failures=profile.validation_failures,
    )
    try:
        from routers.analytics import record_event
        from database import SessionLocal
        with SessionLocal() as ev_db:
            record_event(
                ev_db,
                user_id=None,
                event_category="energy",
                event_type="energy_analysis",
                payload={
                    "material": req.material.value,
                    "duration_hours": req.duration_hours,
                    "kwh": round(profile.estimated_kwh, 2),
                    "cost_usd": round(profile.estimated_cost_usd, 2),
                },
            )
    except Exception:
        pass
    return response


@router.get(
    "/negative-pricing-windows",
    response_model=NegativePricingResponse,
    summary="Detect hours when PJM LMP goes negative (grid pays you to consume)",
)
async def get_negative_pricing_windows() -> NegativePricingResponse:
    """
    Returns hours in the current 24-hour window where PJM LMP is negative.
    A negative LMP means the grid is paying consumers to absorb excess generation —
    ideal for running energy-intensive jobs like titanium cutting.
    Uses live PJM data when available; falls back to simulated curve.
    """
    try:
        result = _optimizer.get_negative_pricing_windows()
    except Exception as exc:
        logger.error("Negative pricing error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Energy data error")

    windows = [
        NegativePricingWindow(
            hour=w["hour"],
            # agent returns $/kWh; schema uses $/MWh for readability
            rate_usd_per_mwh=round(w["rate_usd_per_kwh"] * 1000, 2),
            duration_hours=w.get("duration_hours", 1),
        )
        for w in result.get("windows", [])
    ]
    return NegativePricingResponse(
        windows=windows,
        total_windows=result["total_windows"],
        max_credit_usd_per_mwh=result["max_credit_usd_per_mwh"],
        recommendation=result["recommendation"],
        data_source=result["data_source"],
    )


@router.post(
    "/arbitrage-analysis",
    response_model=ArbitrageResponse,
    summary="Model peak-to-off-peak load shifting savings",
)
async def get_arbitrage_analysis(req: ArbitrageRequest) -> ArbitrageResponse:
    """
    Compute potential savings from shifting flexible mill load to off-peak hours.
    Returns daily and annual savings, optimal shift windows, and a recommendation.
    Works on real PJM LMP data when available.
    """
    try:
        result = _optimizer.get_arbitrage_analysis(
            req.daily_energy_kwh,
            req.flexible_load_percent,
        )
    except Exception as exc:
        logger.error("Arbitrage analysis error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Arbitrage analysis error")

    # Derive peak/off-peak rates from the hourly rates for the response
    rates, _ = _fetch_rates()
    peak_rate = max(rates)
    off_peak_rate = min(rates)
    savings = result["annual_savings_usd"]
    recommendation = (
        f"Shifting {req.flexible_load_percent * 100:.0f}% of load off-peak saves "
        f"~${savings:,.0f}/yr. Optimal windows: hours {result['optimal_shift_hours']}."
    )

    return ArbitrageResponse(
        daily_savings_usd=result["daily_savings_usd"],
        annual_savings_usd=result["annual_savings_usd"],
        peak_rate_usd_per_kwh=round(peak_rate, 4),
        off_peak_rate_usd_per_kwh=round(off_peak_rate, 4),
        optimal_shift_hours=result["optimal_shift_hours"],
        recommendation=recommendation,
        data_source=result["data_source"],
    )


@router.get(
    "/carbon-intensity",
    summary="Get current carbon intensity of the grid",
)
async def get_carbon_intensity():
    """
    Returns the current carbon intensity (grams of CO2 per kWh) for the grid zone.
    Uses the Electricity Maps API when configured; falls back to US grid average estimate.
    """
    api_key = os.getenv("ELECTRICITY_MAPS_API_KEY")
    logger.info("Carbon intensity: API key present=%s", bool(api_key))
    if not api_key:
        return {
            "zone": "US-PJM",
            "carbon_intensity_gco2_per_kwh": 386,
            "data_source": "estimated_us_grid_average",
            "note": "Set ELECTRICITY_MAPS_API_KEY for live data"
        }
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://api.electricitymap.org/v3/carbon-intensity/latest",
                params={"zone": "US-PJM"},
                headers={"auth-token": api_key},
                timeout=5.0,
            )
        logger.info("Carbon intensity: Electricity Maps response status=%s", response.status_code)
        data = response.json()
        return {
            "zone": "US-PJM",
            "carbon_intensity_gco2_per_kwh": data.get("carbonIntensity", 386),
            "data_source": "electricity_maps_live",
            "datetime": data.get("datetime")
        }
    except Exception as exc:
        logger.warning("Carbon intensity fetch failed: %s", exc)
        return {
            "zone": "US-PJM",
            "carbon_intensity_gco2_per_kwh": 386,
            "data_source": "fallback_estimate"
        }


@router.get(
    "/rates",
    summary="Get 24-hour hourly electricity rate curve",
)
async def get_hourly_rates():
    """
    Returns the 24-hour hourly rate curve ($/kWh) used for energy scheduling decisions.
    Uses live EIA demand-based pricing when EIA_API_KEY is set; falls back to simulated curve.
    """
    try:
        rates, data_source = _fetch_rates()
    except Exception as exc:
        logger.error("Hourly rates error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Rate data error")
    return {
        "rates_usd_per_kwh": rates,
        "data_source": data_source,
        "hours": list(range(len(rates))),
    }


@router.post(
    "/scenario",
    response_model=ScenarioResponse,
    summary="10-year NPV for on-site generation scenarios (solar, battery, wind, SMR)",
)
async def get_scenario_npv(req: ScenarioRequest) -> ScenarioResponse:
    """
    Model the 10-year net present value of deploying on-site generation at the mill.
    Scenarios: solar, battery, solar+battery, wind, SMR, grid_only (baseline).
    Uses LAZARD LCOE v17 (2024) cost assumptions.
    """
    try:
        result = _optimizer.get_scenario_npv(
            req.scenario.value,
            req.annual_energy_kwh,
            req.capex_usd,
        )
    except Exception as exc:
        logger.error("Scenario NPV error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Scenario analysis error")

    return ScenarioResponse(
        scenario=result["scenario"],
        capex_usd=result["capex_usd"],
        lcoe_usd_per_kwh=result["lcoe_usd_per_kwh"],
        annual_savings_usd=result["annual_savings_usd"],
        npv_10yr_usd=result["npv_10yr_usd"],
        payback_years=result["payback_years"],
        recommendation=result["recommendation"],
        data_source=result.get("data_source", "lazard_lcoe_v17_2024"),
    )
