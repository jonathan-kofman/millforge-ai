"""
MillForge Contract Generator Agent

Generates customer-facing legal documents:
  - Master Service Agreement (MSA)
  - SLA schedules
  - Pricing/Order Form
  - Pilot agreement (30-day trial terms)

Documents are returned as formatted plain text / Markdown.
No external dependencies, no FastAPI imports.
"""

import logging
from datetime import datetime, date, timezone
from typing import Optional

logger = logging.getLogger(__name__)


class ContractGenerator:

    # ------------------------------------------------------------------
    # MSA
    # ------------------------------------------------------------------

    def generate_msa(
        self,
        customer_name: str,
        customer_address: str,
        effective_date: Optional[date] = None,
        governing_state: str = "Massachusetts",
    ) -> dict:
        """
        Generate a Master Service Agreement for a MillForge customer.
        Returns the document as a Markdown string.
        """
        if effective_date is None:
            effective_date = date.today()
        eff_str = effective_date.strftime("%B %d, %Y")

        doc = f"""# MillForge Master Service Agreement

**Effective Date:** {eff_str}
**Customer:** {customer_name}
**Customer Address:** {customer_address}
**Vendor:** MillForge, Inc. ("MillForge")
**Vendor Address:** Boston, Massachusetts

---

## 1. Services

MillForge grants Customer a non-exclusive, non-transferable subscription to the
MillForge production intelligence platform ("Service") as specified in the applicable
Order Form. The Service includes AI-driven scheduling, automated quoting, quality
vision inspection, inventory management, energy optimisation, and related modules
as enabled per the subscribed tier.

## 2. Subscription and Fees

2.1 Fees are as set forth in the Order Form. Invoices are due Net-30.
2.2 MillForge may update pricing with 60 days written notice. Customer may
terminate without penalty if pricing increases exceed 10% in any 12-month period.
2.3 All fees are non-refundable except as stated in Section 10 (Termination).

## 3. Data and Security

3.1 Customer retains ownership of all production data, order records, inspection
images, and machine telemetry ("Customer Data").
3.2 MillForge processes Customer Data solely to provide the Service. MillForge
will not sell, license, or share Customer Data with third parties except as
required by law.
3.3 MillForge maintains SOC 2 Type II controls and performs annual penetration tests.
3.4 Customer Data is encrypted at rest (AES-256) and in transit (TLS 1.3+).

## 4. Uptime and Support

4.1 MillForge targets 99.5% monthly uptime for the core scheduling and quoting APIs.
4.2 Scheduled maintenance windows (max 2 hours/month) are excluded from uptime calculations.
4.3 Support tiers are as specified in the Order Form SLA Schedule.

## 5. Intellectual Property

5.1 MillForge retains all rights to the platform, algorithms, models, and documentation.
5.2 Customer retains all rights to Customer Data and any custom ARIA normalizers
or configuration Customer provides to MillForge.
5.3 MillForge may use aggregate, anonymised performance metrics to improve the platform.

## 6. Confidentiality

Each party agrees to maintain the confidentiality of the other party's non-public
business information using at least the same degree of care it uses for its own
confidential information, but in no event less than reasonable care.

## 7. Warranties and Disclaimers

7.1 MillForge warrants that the Service will perform materially in accordance with
the published documentation during the subscription term.
7.2 EXCEPT AS STATED HEREIN, THE SERVICE IS PROVIDED "AS IS." MILLFORGE DISCLAIMS
ALL OTHER WARRANTIES, EXPRESS OR IMPLIED, INCLUDING MERCHANTABILITY AND FITNESS
FOR A PARTICULAR PURPOSE.

## 8. Limitation of Liability

IN NO EVENT WILL EITHER PARTY'S LIABILITY EXCEED THE FEES PAID BY CUSTOMER IN
THE 12 MONTHS PRECEDING THE CLAIM. NEITHER PARTY IS LIABLE FOR INDIRECT, INCIDENTAL,
SPECIAL, OR CONSEQUENTIAL DAMAGES.

## 9. Indemnification

Each party will defend, indemnify, and hold harmless the other party against
third-party claims arising from (a) its breach of this Agreement, or (b) its
gross negligence or wilful misconduct.

## 10. Term and Termination

10.1 This Agreement begins on the Effective Date and continues until terminated.
10.2 Either party may terminate with 30 days written notice at the end of a subscription period.
10.3 MillForge may terminate immediately for non-payment (after 15-day cure period) or material breach.
10.4 Upon termination, MillForge will provide Customer Data export for 30 days.

## 11. Governing Law

This Agreement is governed by the laws of {governing_state}, without regard to its
conflict of law provisions. Disputes will be resolved by binding arbitration
under AAA Commercial Rules in Boston, Massachusetts.

## 12. General

12.1 This Agreement, together with all Order Forms, constitutes the entire agreement
between the parties.
12.2 MillForge may update these terms with 30 days notice. Continued use constitutes acceptance.
12.3 Neither party may assign this Agreement without the other's written consent,
except in connection with a merger or acquisition.

---

**MILLFORGE, INC.**

Signature: _________________________ Date: _____________
Name: Jonathan Kofman
Title: CEO

**{customer_name.upper()}**

Signature: _________________________ Date: _____________
Name: _________________________
Title: _________________________
"""

        return {
            "document_type": "msa",
            "customer_name": customer_name,
            "effective_date": eff_str,
            "governing_state": governing_state,
            "content_markdown": doc,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # SLA Schedule
    # ------------------------------------------------------------------

    def generate_sla(self, tier: str) -> dict:
        """
        Generate the SLA schedule for a given pricing tier.
        """
        sla_map = {
            "starter": {
                "uptime_sla_percent": 99.0,
                "support_channel": "Email",
                "first_response_hours": 24,
                "resolution_target_hours": 72,
                "scheduled_maintenance_window": "Sundays 02:00–04:00 UTC",
                "credits": "5% of monthly fee per hour of excess downtime (cap 30%)",
            },
            "growth": {
                "uptime_sla_percent": 99.5,
                "support_channel": "Email + Slack",
                "first_response_hours": 4,
                "resolution_target_hours": 24,
                "scheduled_maintenance_window": "Sundays 02:00–04:00 UTC",
                "credits": "10% of monthly fee per hour of excess downtime (cap 50%)",
            },
            "enterprise": {
                "uptime_sla_percent": 99.9,
                "support_channel": "Email + Slack + Phone + Dedicated CSM",
                "first_response_hours": 1,
                "resolution_target_hours": 8,
                "scheduled_maintenance_window": "Customer-approved windows only",
                "credits": "15% of monthly fee per hour of excess downtime (cap 100%)",
            },
            "custom": {
                "uptime_sla_percent": 99.95,
                "support_channel": "24/7 dedicated engineering line",
                "first_response_hours": 0.5,
                "resolution_target_hours": 4,
                "scheduled_maintenance_window": "Contractually agreed",
                "credits": "Contractually negotiated",
            },
        }

        sla = sla_map.get(tier.lower(), sla_map["starter"])

        doc = f"""# MillForge SLA Schedule — {tier.title()} Tier

**Uptime Commitment:** {sla["uptime_sla_percent"]}% monthly
**Support Channel:** {sla["support_channel"]}
**First Response:** Within {sla["first_response_hours"]} hour(s)
**Resolution Target:** Within {sla["resolution_target_hours"]} hour(s) (P1 incidents)
**Maintenance Window:** {sla["scheduled_maintenance_window"]}
**Service Credits:** {sla["credits"]}

### Incident Severity Definitions

| Level | Definition | Response |
|-------|-----------|----------|
| P1 — Critical | Scheduling or quoting API completely unavailable | {sla["first_response_hours"]}h |
| P2 — High | Core feature degraded; workaround exists | {sla["first_response_hours"] * 2}h |
| P3 — Medium | Non-critical feature impaired | {sla["resolution_target_hours"]}h |
| P4 — Low | Cosmetic issues, documentation requests | 5 business days |

### Exclusions

SLA credits do not apply to:
- Customer-caused outages or configuration errors
- Force majeure events
- Scheduled maintenance within defined windows
- Issues caused by third-party integrations (EIA API, Electricity Maps, Yahoo Finance)
"""

        return {
            "document_type": "sla_schedule",
            "tier": tier,
            "sla_terms": sla,
            "content_markdown": doc,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Order Form / Pricing Schedule
    # ------------------------------------------------------------------

    def generate_order_form(
        self,
        customer_name: str,
        tier: str,
        machine_count: int,
        billing_cycle: str = "annual",
        start_date: Optional[date] = None,
        add_ons: Optional[list[str]] = None,
    ) -> dict:
        """
        Generate a signed order form / pricing schedule.
        """
        from agents.business_agent import PRICING_TIERS

        if start_date is None:
            start_date = date.today()

        tier_data = next((t for t in PRICING_TIERS if t["id"] == tier.lower()), None)
        if tier_data is None:
            return {"error": f"Unknown tier '{tier}'. Valid: starter, growth, enterprise, custom."}

        if billing_cycle == "annual":
            base_price = tier_data.get("price_annual_usd") or (tier_data.get("price_monthly_usd", 0) * 10)
            billing_label = "Annual (2 months free)"
        else:
            base_price = (tier_data.get("price_monthly_usd") or 0) * 12
            billing_label = "Monthly"

        add_on_lines = []
        add_on_total = 0
        if add_ons:
            add_on_prices = {
                "contract_management": 199 * 12,
                "market_quotes_unlimited": 299 * 12,
                "sso_saml": 500 * 12,
            }
            for ao in add_ons:
                price = add_on_prices.get(ao, 0)
                add_on_lines.append({"item": ao, "annual_price_usd": price})
                add_on_total += price

        total = (base_price or 0) + add_on_total

        add_on_rows = "".join(
            f"| {ao['item'].replace('_', ' ').title()} | Add-on | ${ao['annual_price_usd']:,.0f}/yr |\n"
            for ao in add_on_lines
        )
        feature_list = "".join(f"- {f}\n" for f in tier_data["features"])

        doc = f"""# MillForge Order Form

**Customer:** {customer_name}
**Order Date:** {start_date.strftime("%B %d, %Y")}
**Service Start:** {start_date.strftime("%B %d, %Y")}

---

## Subscription

| Item | Detail | Price |
|------|--------|-------|
| MillForge {tier_data["name"]} | {machine_count} machines · {billing_label} | ${base_price:,.0f}/yr |
{add_on_rows}| **Total** | | **${total:,.0f}/yr** |

## Features Included
{feature_list}

## Payment Terms

Net-30 from invoice date. Annual subscription invoiced on the Service Start date.
ACH preferred. Wire transfer accepted. Credit card accepted (3% surcharge).

---

This Order Form is governed by the MillForge Master Service Agreement in effect
between the parties as of the Order Date.

**MILLFORGE, INC.**
Signature: _________________________ Date: _____________

**{customer_name.upper()}**
Signature: _________________________ Date: _____________
"""

        return {
            "document_type": "order_form",
            "customer_name": customer_name,
            "tier": tier,
            "machine_count": machine_count,
            "billing_cycle": billing_cycle,
            "annual_total_usd": total,
            "content_markdown": doc,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # ------------------------------------------------------------------
    # Pilot Agreement
    # ------------------------------------------------------------------

    def generate_pilot_agreement(
        self,
        customer_name: str,
        pilot_days: int = 30,
        tier: str = "growth",
        start_date: Optional[date] = None,
    ) -> dict:
        """
        Generate a short-form 30-day pilot agreement.
        """
        if start_date is None:
            start_date = date.today()
        from datetime import timedelta
        end_date = start_date + timedelta(days=pilot_days)

        doc = f"""# MillForge Pilot Agreement

**Customer:** {customer_name}
**Pilot Period:** {start_date.strftime("%B %d, %Y")} — {end_date.strftime("%B %d, %Y")} ({pilot_days} days)
**Tier Evaluated:** {tier.title()}
**Fee:** No charge during pilot period

---

## Terms

1. MillForge grants Customer access to the {tier.title()} tier for {pilot_days} days at no charge.
2. Customer agrees to provide feedback via weekly check-in call (30 min/week).
3. Customer Data is handled per MillForge's standard Privacy Policy and MSA terms.
4. At pilot end, Customer may (a) subscribe at published pricing, (b) negotiate custom terms, or (c) discontinue with no obligation.
5. MillForge will export Customer Data for 14 days after pilot end upon request.
6. Either party may terminate the pilot with 3 days written notice.

## Success Metrics (Agreed)

- On-time delivery rate before vs. after MillForge scheduling
- Hours per week saved on manual scheduling
- Number of jobs auto-quoted without human intervention

---

**MILLFORGE, INC.**
Signature: _________________________ Date: _____________

**{customer_name.upper()}**
Signature: _________________________ Date: _____________
"""

        return {
            "document_type": "pilot_agreement",
            "customer_name": customer_name,
            "tier": tier,
            "pilot_days": pilot_days,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "content_markdown": doc,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
