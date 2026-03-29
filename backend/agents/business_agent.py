"""
MillForge Business Agent

Handles all business-layer intelligence:
  - SaaS pricing tier management and recommendations
  - Customer ROI projections (what MillForge saves them)
  - Revenue modeling and MRR projections
  - Market sizing and competitive benchmarks
  - Business health metrics from the live database

No FastAPI imports. Pure Python business logic.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Pricing tiers — single source of truth for all business logic
# ---------------------------------------------------------------------------

PRICING_TIERS: list[dict] = [
    {
        "id": "starter",
        "name": "Starter",
        "price_monthly_usd": 499,
        "price_annual_usd": 4_990,   # 2 months free
        "machine_limit": 5,
        "user_limit": 3,
        "features": [
            "AI scheduling (EDD + SA)",
            "Automated quoting",
            "Quality vision inspection",
            "Inventory reorder alerts",
            "Energy cost tracking",
            "Supplier directory (read)",
            "Email support",
        ],
        "best_for": "Single-operator shops with 1–5 machines",
    },
    {
        "id": "growth",
        "name": "Growth",
        "price_monthly_usd": 1_499,
        "price_annual_usd": 14_990,
        "machine_limit": 20,
        "user_limit": 15,
        "features": [
            "Everything in Starter",
            "Simulated Annealing scheduler (96.4% on-time)",
            "Anomaly gate (duplicate IDs, impossible deadlines)",
            "Rework auto-dispatch",
            "Market quotes API (500 queries/month)",
            "MTConnect live machine state",
            "Scheduling twin (ML self-calibration)",
            "Contract generator",
            "Priority support (4-hour SLA)",
        ],
        "best_for": "Mid-size job shops, 6–20 machines",
    },
    {
        "id": "enterprise",
        "name": "Enterprise",
        "price_monthly_usd": 3_999,
        "price_annual_usd": 39_990,
        "machine_limit": None,      # unlimited
        "user_limit": None,
        "features": [
            "Everything in Growth",
            "Unlimited machines and users",
            "Market quotes API (unlimited)",
            "Custom ARIA schema normalizers",
            "On-site energy procurement negotiation",
            "Dedicated CSM",
            "1-hour SLA",
            "Custom ERP integration (REST/CSV)",
            "SSO (SAML 2.0)",
            "Quarterly business review",
        ],
        "best_for": "High-volume job shops, multi-site, Tier 1 suppliers",
    },
    {
        "id": "custom",
        "name": "Custom / Defence",
        "price_monthly_usd": None,  # negotiated
        "price_annual_usd": None,
        "machine_limit": None,
        "user_limit": None,
        "features": [
            "Everything in Enterprise",
            "Air-gapped deployment option",
            "FedRAMP-aligned audit logging",
            "Custom model fine-tuning for proprietary defect classes",
            "Contractual uptime SLA (99.9%)",
            "Dedicated engineering support",
        ],
        "best_for": "Defence contractors, Tier 1 automotive/aerospace suppliers",
    },
]

# ---------------------------------------------------------------------------
# Market benchmarks (US job shop industry averages)
# ---------------------------------------------------------------------------

INDUSTRY_BENCHMARKS = {
    "avg_otd_percent": 74.0,          # industry average on-time delivery
    "millforge_otd_percent": 96.4,    # MillForge SA benchmark (deterministic)
    "avg_setup_overhead_percent": 22, # % of production time lost to changeovers
    "avg_scheduling_hours_per_week": 8,  # hours a human scheduler spends weekly
    "scheduler_hourly_cost_usd": 35,  # burdened labor cost for scheduling
    "avg_late_order_penalty_usd": 800, # cost of a single late delivery (rush, rework, relationship)
}


# ---------------------------------------------------------------------------
# Business Agent
# ---------------------------------------------------------------------------

class BusinessAgent:

    def get_pricing_tiers(self) -> list[dict]:
        """Return all pricing tiers."""
        return PRICING_TIERS

    def recommend_tier(self, machine_count: int, orders_per_month: int) -> dict:
        """
        Recommend the most appropriate tier based on shop size and order volume.
        Returns the tier dict plus a rationale string.
        """
        if machine_count <= 5 and orders_per_month <= 150:
            tier_id = "starter"
            rationale = (
                f"Your {machine_count}-machine shop at ~{orders_per_month} orders/month "
                "fits comfortably within Starter limits. Upgrade to Growth when you "
                "hit 6 machines or need the scheduling twin."
            )
        elif machine_count <= 20 and orders_per_month <= 800:
            tier_id = "growth"
            rationale = (
                f"Growth covers up to 20 machines. With {orders_per_month} orders/month "
                "you'll see the most value from the SA scheduler and market quotes API."
            )
        elif machine_count is not None and machine_count > 20:
            tier_id = "enterprise"
            rationale = (
                f"{machine_count} machines exceeds Growth limits. Enterprise gives you "
                "unlimited machines, unlimited market quotes, and a dedicated CSM."
            )
        else:
            tier_id = "growth"
            rationale = "Growth is the right starting point for shops of your size."

        tier = next(t for t in PRICING_TIERS if t["id"] == tier_id)
        return {**tier, "rationale": rationale}

    def calculate_roi(
        self,
        machine_count: int,
        orders_per_month: int,
        avg_order_value_usd: float,
        current_otd_percent: float,
        shifts_per_day: int = 2,
    ) -> dict:
        """
        Calculate annual ROI of deploying MillForge for a specific shop.

        Returns a breakdown of:
        - Revenue recovered from improved on-time delivery
        - Labor savings from automated scheduling
        - Avoided late-order penalties
        - Total annual benefit vs MillForge subscription cost
        """
        annual_orders = orders_per_month * 12
        current_late_count = annual_orders * ((100 - current_otd_percent) / 100)
        millforge_late_count = annual_orders * ((100 - INDUSTRY_BENCHMARKS["millforge_otd_percent"]) / 100)
        orders_saved = max(0, current_late_count - millforge_late_count)

        # Revenue recovered: each saved order avoids penalty and retains customer
        penalty_savings_usd = orders_saved * INDUSTRY_BENCHMARKS["avg_late_order_penalty_usd"]

        # Revenue at risk that gets recovered: each saved order has avg value
        revenue_recovered_usd = orders_saved * avg_order_value_usd * 0.08  # ~8% margin impact

        # Labor savings: automated scheduling frees the scheduler
        weekly_hours_saved = INDUSTRY_BENCHMARKS["avg_scheduling_hours_per_week"]
        annual_labor_savings_usd = (
            weekly_hours_saved * 52 * INDUSTRY_BENCHMARKS["scheduler_hourly_cost_usd"]
        )

        # Throughput gain from reduced setup overhead
        setup_gain_percent = INDUSTRY_BENCHMARKS["avg_setup_overhead_percent"] * 0.30  # conservative 30% reduction
        throughput_gain_usd = (annual_orders * avg_order_value_usd * 0.03) * (setup_gain_percent / 100)

        total_annual_benefit_usd = (
            penalty_savings_usd
            + revenue_recovered_usd
            + annual_labor_savings_usd
            + throughput_gain_usd
        )

        # MillForge cost
        tier = self.recommend_tier(machine_count, orders_per_month)
        annual_subscription_usd = tier.get("price_annual_usd") or (tier.get("price_monthly_usd", 0) * 10)

        net_annual_value_usd = total_annual_benefit_usd - annual_subscription_usd
        roi_percent = (
            (net_annual_value_usd / annual_subscription_usd * 100)
            if annual_subscription_usd > 0
            else 0
        )
        payback_months = (
            (annual_subscription_usd / (total_annual_benefit_usd / 12))
            if total_annual_benefit_usd > 0
            else None
        )

        return {
            "inputs": {
                "machine_count": machine_count,
                "orders_per_month": orders_per_month,
                "avg_order_value_usd": avg_order_value_usd,
                "current_otd_percent": current_otd_percent,
                "shifts_per_day": shifts_per_day,
            },
            "otd_improvement": {
                "before_percent": current_otd_percent,
                "after_percent": INDUSTRY_BENCHMARKS["millforge_otd_percent"],
                "improvement_pp": round(INDUSTRY_BENCHMARKS["millforge_otd_percent"] - current_otd_percent, 1),
                "late_orders_avoided_per_year": round(orders_saved, 1),
            },
            "annual_benefits_usd": {
                "late_penalty_avoided": round(penalty_savings_usd, 2),
                "revenue_recovered": round(revenue_recovered_usd, 2),
                "scheduling_labor_saved": round(annual_labor_savings_usd, 2),
                "throughput_gain": round(throughput_gain_usd, 2),
                "total": round(total_annual_benefit_usd, 2),
            },
            "millforge_cost_usd": {
                "annual_subscription": annual_subscription_usd,
                "recommended_tier": tier["id"],
            },
            "summary": {
                "net_annual_value_usd": round(net_annual_value_usd, 2),
                "roi_percent": round(roi_percent, 1),
                "payback_months": round(payback_months, 1) if payback_months else None,
                "break_even_message": (
                    f"MillForge pays for itself in {round(payback_months, 1)} months."
                    if payback_months and payback_months <= 12
                    else "Contact us to discuss a pilot program."
                ),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def project_revenue(
        self,
        months: int,
        starting_customers: int,
        monthly_new_customers: float,
        avg_monthly_revenue_per_customer_usd: float,
        churn_rate_monthly_percent: float = 2.0,
    ) -> dict:
        """
        Project MRR, ARR, and cumulative revenue over N months.
        Uses a simple cohort model with constant churn.
        """
        timeline = []
        customers = float(starting_customers)
        cumulative_revenue = 0.0

        for month in range(1, months + 1):
            churn = customers * (churn_rate_monthly_percent / 100)
            customers = customers - churn + monthly_new_customers
            mrr = customers * avg_monthly_revenue_per_customer_usd
            cumulative_revenue += mrr
            timeline.append({
                "month": month,
                "customers": round(customers, 1),
                "mrr_usd": round(mrr, 2),
                "arr_usd": round(mrr * 12, 2),
                "cumulative_revenue_usd": round(cumulative_revenue, 2),
            })

        final = timeline[-1]
        return {
            "projection_months": months,
            "assumptions": {
                "starting_customers": starting_customers,
                "monthly_new_customers": monthly_new_customers,
                "avg_monthly_revenue_per_customer_usd": avg_monthly_revenue_per_customer_usd,
                "churn_rate_monthly_percent": churn_rate_monthly_percent,
            },
            "summary": {
                "final_mrr_usd": final["mrr_usd"],
                "final_arr_usd": final["arr_usd"],
                "final_customers": final["customers"],
                "total_revenue_usd": final["cumulative_revenue_usd"],
            },
            "timeline": timeline,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_business_metrics(self, db) -> dict:
        """
        Pull live business KPIs from the database.
        Returns customer count, active jobs, inspection throughput, and uptime.
        """
        from db_models import User, Job, QCResult
        from sqlalchemy import func

        try:
            total_users = db.query(func.count(User.id)).scalar() or 0
            total_jobs = db.query(func.count(Job.id)).scalar() or 0
            active_jobs = (
                db.query(func.count(Job.id))
                .filter(Job.stage.in_(["queued", "in_progress", "qc_pending"]))
                .scalar() or 0
            )
            complete_jobs = (
                db.query(func.count(Job.id))
                .filter(Job.stage == "complete")
                .scalar() or 0
            )
            total_inspections = db.query(func.count(QCResult.id)).scalar() or 0
            passed_inspections = (
                db.query(func.count(QCResult.id))
                .filter(QCResult.passed == True)
                .scalar() or 0
            )
        except Exception as exc:
            logger.warning("Business metrics DB query failed: %s", exc)
            return {"error": str(exc), "generated_at": datetime.now(timezone.utc).isoformat()}

        return {
            "users": {
                "total": total_users,
            },
            "jobs": {
                "total": total_jobs,
                "active": active_jobs,
                "complete": complete_jobs,
                "completion_rate_percent": (
                    round(complete_jobs / total_jobs * 100, 1) if total_jobs else 0.0
                ),
            },
            "quality": {
                "total_inspections": total_inspections,
                "pass_rate_percent": (
                    round(passed_inspections / total_inspections * 100, 1)
                    if total_inspections else 0.0
                ),
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
