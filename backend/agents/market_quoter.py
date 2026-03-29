"""
MillForge Market Quoter Agent

Finds the cheapest available prices for:
  - Raw materials (from the 1,100+ supplier DB + spot price APIs)
  - Energy procurement (via EIA API / grid data)
  - Full job cost (materials + energy + setup)

Data sources (in priority order):
  1. Metals spot prices — Yahoo Finance futures API (no key required)
  2. Supplier DB — 1,100+ verified US suppliers with geo-sorting
  3. EIA API v2 — real-time electricity pricing (falls back to mock curve)

All fetch functions return None on failure — callers always get a usable
response via the mock fallback path.

No FastAPI imports. Pure Python business logic.
"""

import json
import logging
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Spot price constants (USD/lb) — used as fallback when live APIs are down
# Based on early 2025 market averages
# ---------------------------------------------------------------------------

FALLBACK_SPOT_PRICES_USD_PER_LB: dict[str, float] = {
    "steel":           0.42,   # hot-rolled coil
    "aluminum":        1.18,
    "titanium":       15.50,
    "copper":          4.35,
    "brass":           2.80,
    "bronze":          3.10,
    "stainless_steel": 1.65,
    "carbon_steel":    0.45,
    "tool_steel":      2.20,
    "cast_iron":       0.38,
    "nickel":          7.50,
    "zinc":            1.30,
    "lead":            0.95,
    "tin":             8.90,
    "tungsten":       19.80,
}

# Yahoo Finance ticker symbols for metals futures (USD/troy oz or USD/lb as noted)
_YAHOO_TICKERS: dict[str, dict] = {
    "aluminum": {"symbol": "ALI=F",  "unit": "usd_per_lb",    "divisor": 1.0},
    "copper":   {"symbol": "HG=F",   "unit": "usd_per_lb",    "divisor": 1.0},
    # Gold and silver for reference / industrial use
    "gold":     {"symbol": "GC=F",   "unit": "usd_per_troy_oz", "divisor": 1.0},
    "silver":   {"symbol": "SI=F",   "unit": "usd_per_troy_oz", "divisor": 1.0},
    # Tin (LME via CME)
    "tin":      {"symbol": "TIN=F",  "unit": "usd_per_lb",    "divisor": 1.0},
    "nickel":   {"symbol": "NI=F",   "unit": "usd_per_lb",    "divisor": 1.0},
}

# ---------------------------------------------------------------------------
# Module-level spot price cache (1-hour TTL)
# ---------------------------------------------------------------------------

_spot_cache: dict = {}
_SPOT_CACHE_TTL = 3600  # seconds


def _fetch_spot_price(material: str) -> Optional[float]:
    """
    Fetch live spot price for a material from Yahoo Finance.
    Returns price in USD/lb, or None on any failure.
    """
    ticker_info = _YAHOO_TICKERS.get(material)
    if not ticker_info:
        return None
    symbol = urllib.parse.quote(ticker_info["symbol"])
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
        f"?interval=1d&range=1d"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MillForge/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        price = (
            data["chart"]["result"][0]["meta"]["regularMarketPrice"]
        )
        return float(price)
    except Exception as exc:
        logger.debug("Spot price fetch failed for %s: %s", material, exc)
        return None


def _get_spot_price(material: str) -> tuple[float, str]:
    """
    Return (price_usd_per_lb, data_source) with caching.
    Falls back to FALLBACK_SPOT_PRICES if live fetch fails.
    """
    now = time.time()
    cached = _spot_cache.get(material)
    if cached and now - cached["ts"] < _SPOT_CACHE_TTL:
        return cached["price"], cached["source"]

    live_price = _fetch_spot_price(material)
    if live_price is not None:
        _spot_cache[material] = {"price": live_price, "ts": now, "source": "yahoo_finance"}
        return live_price, "yahoo_finance"

    fallback = FALLBACK_SPOT_PRICES_USD_PER_LB.get(material, 1.0)
    _spot_cache[material] = {"price": fallback, "ts": now, "source": "fallback_2025_avg"}
    return fallback, "fallback_2025_avg"


# ---------------------------------------------------------------------------
# Supplier price modelling
# ---------------------------------------------------------------------------

# Typical mill-form markup over spot price (varies by supplier category)
SUPPLIER_MARKUP_FACTORS: dict[str, float] = {
    "service_center":   1.18,  # Olympic Steel, Ryerson — value-added processing
    "distributor":      1.12,  # Metals USA, TW Metals
    "direct_mill":      1.05,  # Nucor, US Steel — near-spot pricing
    "specialty":        1.35,  # titanium, tool steel specialists
    "default":          1.15,
}

# Typical freight rates (USD/cwt = per 100 lbs)
FREIGHT_USD_PER_CWT: dict[str, float] = {
    "local_0_100mi":    4.50,
    "regional_100_500mi": 7.80,
    "national_500_plus": 12.40,
}

MILL_FORM_SURCHARGES_USD_PER_LB: dict[str, float] = {
    "bar_stock":    0.04,
    "sheet":        0.06,
    "plate":        0.05,
    "tube":         0.09,
    "pipe":         0.08,
    "extrusion":    0.07,
    "default":      0.05,
}


class MarketQuoter:

    def get_spot_prices(self, materials: Optional[list[str]] = None) -> dict:
        """
        Return current spot prices for the requested materials.
        Defaults to all metals in FALLBACK_SPOT_PRICES if list not provided.
        """
        if materials is None:
            materials = list(FALLBACK_SPOT_PRICES_USD_PER_LB.keys())

        prices = {}
        sources = {}
        for mat in materials:
            price, source = _get_spot_price(mat)
            prices[mat] = round(price, 4)
            sources[mat] = source

        return {
            "prices_usd_per_lb": prices,
            "data_sources": sources,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def quote_materials(
        self,
        db,
        material: str,
        quantity_lbs: float,
        delivery_state: Optional[str] = None,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        mill_form: str = "bar_stock",
        top_n: int = 5,
    ) -> dict:
        """
        Find the cheapest suppliers for a given material and quantity.

        Ranks options by total landed cost (spot × markup + freight + form surcharge).
        Uses geo-distance from lat/lng if provided, otherwise uses delivery_state.
        Returns the top N options with full cost breakdown.
        """
        from agents.supplier_directory import SupplierDirectory, haversine_miles

        spot_price, spot_source = _get_spot_price(material)
        form_surcharge = MILL_FORM_SURCHARGES_USD_PER_LB.get(mill_form, MILL_FORM_SURCHARGES_USD_PER_LB["default"])

        directory = SupplierDirectory()

        # Pull suppliers that carry this material
        if lat is not None and lng is not None:
            suppliers_with_dist, _ = directory.nearby(
                db, lat=lat, lng=lng, radius_miles=2000, material=material, limit=100
            )
            options_raw = [
                {"supplier": s, "distance_miles": dist}
                for s, dist in suppliers_with_dist
            ]
        else:
            suppliers, total = directory.search(
                db, material=material, state=delivery_state, verified_only=False, limit=100
            )
            # Assign a rough distance bucket for freight purposes
            options_raw = [
                {"supplier": s, "distance_miles": 300}  # regional assumption when no geo
                for s in suppliers
            ]

        if not options_raw:
            return {
                "material": material,
                "quantity_lbs": quantity_lbs,
                "options": [],
                "spot_price_usd_per_lb": round(spot_price, 4),
                "spot_source": spot_source,
                "message": f"No suppliers found for '{material}' in the MillForge directory.",
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }

        options = []
        for item in options_raw:
            sup = item["supplier"]
            dist = item["distance_miles"]

            # Freight tier
            if dist < 100:
                freight_rate = FREIGHT_USD_PER_CWT["local_0_100mi"]
                freight_tier = "local"
            elif dist < 500:
                freight_rate = FREIGHT_USD_PER_CWT["regional_100_500mi"]
                freight_tier = "regional"
            else:
                freight_rate = FREIGHT_USD_PER_CWT["national_500_plus"]
                freight_tier = "national"

            # Markup heuristic based on supplier category
            categories = sup.categories or []
            if "metals" in categories and sup.verified:
                markup = SUPPLIER_MARKUP_FACTORS["service_center"]
            elif "metals" in categories:
                markup = SUPPLIER_MARKUP_FACTORS["distributor"]
            else:
                markup = SUPPLIER_MARKUP_FACTORS["default"]

            unit_price = spot_price * markup + form_surcharge
            material_cost = unit_price * quantity_lbs
            freight_cost = (quantity_lbs / 100) * freight_rate
            total_cost = material_cost + freight_cost

            options.append({
                "rank": None,  # filled below
                "supplier_name": sup.name,
                "supplier_city": sup.city,
                "supplier_state": sup.state,
                "verified": sup.verified,
                "distance_miles": round(dist, 1),
                "freight_tier": freight_tier,
                "pricing": {
                    "spot_price_usd_per_lb": round(spot_price, 4),
                    "markup_factor": round(markup, 2),
                    "form_surcharge_usd_per_lb": round(form_surcharge, 4),
                    "unit_price_usd_per_lb": round(unit_price, 4),
                    "material_cost_usd": round(material_cost, 2),
                    "freight_cost_usd": round(freight_cost, 2),
                    "total_landed_cost_usd": round(total_cost, 2),
                },
                "supplier_contact": {
                    "phone": sup.phone,
                    "website": sup.website,
                    "email": sup.email,
                },
            })

        # Sort by total landed cost, assign ranks
        options.sort(key=lambda o: o["pricing"]["total_landed_cost_usd"])
        for i, opt in enumerate(options[:top_n], start=1):
            opt["rank"] = i

        best = options[0] if options else None
        savings_vs_avg = None
        if len(options) >= 2:
            avg_cost = sum(o["pricing"]["total_landed_cost_usd"] for o in options[:top_n]) / min(top_n, len(options))
            savings_vs_avg = round(avg_cost - options[0]["pricing"]["total_landed_cost_usd"], 2)

        return {
            "material": material,
            "quantity_lbs": quantity_lbs,
            "mill_form": mill_form,
            "spot_price_usd_per_lb": round(spot_price, 4),
            "spot_data_source": spot_source,
            "cheapest_option": best,
            "savings_vs_average_usd": savings_vs_avg,
            "options": options[:top_n],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def quote_energy(
        self,
        kwh_needed: float,
        state: Optional[str] = None,
        flexible_hours: int = 4,
    ) -> dict:
        """
        Find the cheapest window to buy grid electricity for a production run.
        Uses the EnergyOptimizer's rate data.
        """
        from agents.energy_optimizer import EnergyOptimizer

        optimizer = EnergyOptimizer()
        rates = optimizer._get_hourly_rates()
        sorted_hours = sorted(range(24), key=lambda h: rates[h])
        cheapest_hours = sorted_hours[:flexible_hours]
        most_expensive_hours = sorted_hours[-flexible_hours:]

        cheap_avg = sum(rates[h] for h in cheapest_hours) / flexible_hours
        peak_avg = sum(rates[h] for h in most_expensive_hours) / flexible_hours

        cheap_cost = kwh_needed * cheap_avg
        peak_cost = kwh_needed * peak_avg
        savings = peak_cost - cheap_cost

        return {
            "kwh_needed": kwh_needed,
            "flexible_hours": flexible_hours,
            "cheapest_window": {
                "hours_utc": sorted(cheapest_hours),
                "avg_rate_usd_per_kwh": round(cheap_avg, 4),
                "total_cost_usd": round(cheap_cost, 2),
            },
            "peak_window": {
                "hours_utc": sorted(most_expensive_hours),
                "avg_rate_usd_per_kwh": round(peak_avg, 4),
                "total_cost_usd": round(peak_cost, 2),
            },
            "potential_savings_usd": round(savings, 2),
            "recommendation": (
                f"Run energy-intensive jobs during hours {sorted(cheapest_hours)} UTC "
                f"to save ${savings:.2f} vs peak pricing."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def quote_full_job(
        self,
        db,
        material: str,
        quantity_lbs: float,
        estimated_machine_hours: float,
        machine_power_kw: float = 75.0,
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        mill_form: str = "bar_stock",
    ) -> dict:
        """
        All-in cost estimate for a job: materials + energy + setup overhead.
        Returns the cheapest sourcing option with total cost breakdown.
        """
        mat_quote = self.quote_materials(
            db, material=material, quantity_lbs=quantity_lbs,
            lat=lat, lng=lng, mill_form=mill_form, top_n=3,
        )
        kwh_needed = machine_power_kw * estimated_machine_hours
        energy_quote = self.quote_energy(kwh_needed=kwh_needed)

        best_material = mat_quote.get("cheapest_option")
        material_cost = best_material["pricing"]["total_landed_cost_usd"] if best_material else 0.0
        energy_cost = energy_quote["cheapest_window"]["total_cost_usd"]

        # Setup / overhead estimate: 20% of materials + energy
        overhead_cost = (material_cost + energy_cost) * 0.20
        total_cost = material_cost + energy_cost + overhead_cost

        return {
            "material": material,
            "quantity_lbs": quantity_lbs,
            "estimated_machine_hours": estimated_machine_hours,
            "cost_breakdown": {
                "materials_usd": round(material_cost, 2),
                "energy_usd": round(energy_cost, 2),
                "overhead_usd": round(overhead_cost, 2),
                "total_usd": round(total_cost, 2),
            },
            "cheapest_material_supplier": best_material,
            "energy_recommendation": energy_quote["recommendation"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
