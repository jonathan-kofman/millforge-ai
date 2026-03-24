"""
MillForge Anomaly Detection Agent

Analyses a batch of orders for unusual patterns that warrant operator attention:
- quantity_spike: order quantity >> batch average
- impossible_deadline: due_date in the past or too tight for processing
- duplicate_id: same order_id appears more than once
- material_clustering: >80 % of orders use the same material
- priority_inversion: large complex order with low urgency and tight deadline
- complexity_outlier: complexity >> batch average

Uses Claude for narrative summaries; falls back to a rule-based detector
when ANTHROPIC_API_KEY is absent (CI-safe).

Validation loop: validates anomaly list has plausible structure, retries ≤ 3 times.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean, stdev
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_RETRIES = 3

# Thresholds for rule-based detection
QUANTITY_SPIKE_FACTOR = 3.0   # order qty > 3× mean → spike
COMPLEXITY_SPIKE_FACTOR = 2.0  # complexity > 2× mean → outlier
MATERIAL_CLUSTER_THRESHOLD = 0.80  # > 80 % same material → clustering


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

@dataclass
class Anomaly:
    order_id: str
    anomaly_type: str  # quantity_spike | impossible_deadline | duplicate_id |
    #                     material_clustering | priority_inversion | complexity_outlier
    severity: str      # critical | warning | info
    description: str


@dataclass
class AnomalyReport:
    orders_analysed: int
    anomalies: List[Anomaly]
    summary: str
    analysed_at: datetime = field(default_factory=datetime.utcnow)
    validation_failures: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class AnomalyDetector:
    """
    Analyses order batches for anomalous patterns.

    Uses Claude to generate narrative summaries and catch subtle pattern
    issues; falls back to deterministic rule checks when no API key.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None
        if self._api_key:
            try:
                import anthropic  # noqa: PLC0415
                self._client = anthropic.Anthropic(api_key=self._api_key)
                logger.info("AnomalyDetector: Claude client initialised (%s)", MODEL)
            except ImportError:
                logger.warning("anthropic package not installed; using rule-based detector")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, orders: List[Dict]) -> AnomalyReport:
        """
        Detect anomalies in a list of order dicts.

        Each order dict must have at minimum:
            order_id, material, quantity, due_date (ISO string), priority, complexity

        Returns AnomalyReport with all detected anomalies.
        """
        failures: List[str] = []
        best: Optional[AnomalyReport] = None

        for attempt in range(MAX_RETRIES):
            # Rule-based pass always runs (fast, deterministic, catches obvious issues)
            rule_anomalies = self._rule_detect(orders)

            if self._client is not None:
                report = self._claude_detect(orders, rule_anomalies, failures)
            else:
                report = AnomalyReport(
                    orders_analysed=len(orders),
                    anomalies=rule_anomalies,
                    summary=self._build_summary(rule_anomalies),
                )

            errors = self._validate(report, len(orders))

            if not errors:
                report.validation_failures = []
                return report

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = report
            logger.warning(
                "AnomalyDetector validation failed attempt %d: %s", attempt + 1, errors
            )

        assert best is not None
        best.validation_failures = failures
        return best

    # ------------------------------------------------------------------
    # Rule-based detection (CI-safe fallback)
    # ------------------------------------------------------------------

    def _rule_detect(self, orders: List[Dict]) -> List[Anomaly]:
        anomalies: List[Anomaly] = []
        now = datetime.utcnow()

        # --- duplicate IDs ---
        seen_ids: Dict[str, int] = {}
        for o in orders:
            oid = str(o.get("order_id", ""))
            seen_ids[oid] = seen_ids.get(oid, 0) + 1
        for oid, count in seen_ids.items():
            if count > 1:
                anomalies.append(Anomaly(
                    order_id=oid,
                    anomaly_type="duplicate_id",
                    severity="critical",
                    description=f"order_id '{oid}' appears {count} times in the batch",
                ))

        # Compute batch stats
        quantities = [float(o.get("quantity", 0)) for o in orders]
        complexities = [float(o.get("complexity", 1.0)) for o in orders]
        qty_mean = mean(quantities) if quantities else 0
        qty_std = stdev(quantities) if len(quantities) > 1 else 0
        cpx_mean = mean(complexities) if complexities else 1.0

        # --- quantity spike ---
        for o in orders:
            oid = str(o.get("order_id", ""))
            qty = float(o.get("quantity", 0))
            if qty_mean > 0 and qty > qty_mean * QUANTITY_SPIKE_FACTOR and qty_std > 0:
                anomalies.append(Anomaly(
                    order_id=oid,
                    anomaly_type="quantity_spike",
                    severity="warning",
                    description=(
                        f"quantity {qty:.0f} is {qty / qty_mean:.1f}× the batch mean "
                        f"({qty_mean:.0f})"
                    ),
                ))

        # --- impossible deadline ---
        for o in orders:
            oid = str(o.get("order_id", ""))
            raw_due = o.get("due_date")
            if not raw_due:
                continue
            try:
                due = _parse_dt(raw_due)
                if due < now:
                    anomalies.append(Anomaly(
                        order_id=oid,
                        anomaly_type="impossible_deadline",
                        severity="critical",
                        description=f"due_date {due.date()} is in the past",
                    ))
                elif (due - now).total_seconds() < 3600:  # < 1 h away
                    anomalies.append(Anomaly(
                        order_id=oid,
                        anomaly_type="impossible_deadline",
                        severity="warning",
                        description=f"due_date is less than 1 hour from now",
                    ))
            except (ValueError, TypeError):
                pass

        # --- material clustering ---
        if orders:
            mat_counts: Dict[str, int] = {}
            for o in orders:
                mat = str(o.get("material", "unknown"))
                mat_counts[mat] = mat_counts.get(mat, 0) + 1
            top_mat, top_count = max(mat_counts.items(), key=lambda x: x[1])
            frac = top_count / len(orders)
            if frac >= MATERIAL_CLUSTER_THRESHOLD and len(orders) >= 3:
                anomalies.append(Anomaly(
                    order_id="BATCH",
                    anomaly_type="material_clustering",
                    severity="warning",
                    description=(
                        f"{top_count}/{len(orders)} orders ({frac:.0%}) are "
                        f"'{top_mat}' — may saturate that machine group"
                    ),
                ))

        # --- complexity outlier ---
        for o in orders:
            oid = str(o.get("order_id", ""))
            cpx = float(o.get("complexity", 1.0))
            if cpx_mean > 0 and cpx > cpx_mean * COMPLEXITY_SPIKE_FACTOR:
                anomalies.append(Anomaly(
                    order_id=oid,
                    anomaly_type="complexity_outlier",
                    severity="warning",
                    description=(
                        f"complexity {cpx:.1f} is {cpx / cpx_mean:.1f}× the batch mean "
                        f"({cpx_mean:.1f})"
                    ),
                ))

        # --- priority inversion ---
        for o in orders:
            oid = str(o.get("order_id", ""))
            qty = float(o.get("quantity", 0))
            cpx = float(o.get("complexity", 1.0))
            priority = int(o.get("priority", 5))
            raw_due = o.get("due_date")
            if not raw_due:
                continue
            try:
                due = _parse_dt(raw_due)
                hours_left = (due - now).total_seconds() / 3600
                is_low_priority = priority >= 7
                is_large = qty > qty_mean * 1.5 and cpx > 1.5
                is_tight = 0 < hours_left < 48
                if is_low_priority and is_large and is_tight:
                    anomalies.append(Anomaly(
                        order_id=oid,
                        anomaly_type="priority_inversion",
                        severity="warning",
                        description=(
                            f"large/complex order (qty={qty:.0f}, cpx={cpx:.1f}) "
                            f"has low priority ({priority}) but is due in "
                            f"{hours_left:.0f}h"
                        ),
                    ))
            except (ValueError, TypeError):
                pass

        return anomalies

    # ------------------------------------------------------------------
    # Claude-backed analysis
    # ------------------------------------------------------------------

    def _claude_detect(
        self,
        orders: List[Dict],
        rule_anomalies: List[Anomaly],
        prior_failures: List[str],
    ) -> AnomalyReport:
        rule_summary = [
            {"order_id": a.order_id, "type": a.anomaly_type,
             "severity": a.severity, "description": a.description}
            for a in rule_anomalies
        ]
        failure_note = (
            f"\n\nPrior validation failures to fix:\n{chr(10).join(prior_failures)}"
            if prior_failures else ""
        )

        prompt = f"""You are a production operations analyst for a precision metal mill.

Here is a batch of {len(orders)} incoming orders (JSON):
{json.dumps(orders, indent=2, default=str)}

Rule-based pre-screening found these anomalies:
{json.dumps(rule_summary, indent=2)}

Your job:
1. Confirm the rule-based anomalies are correct (remove any false positives).
2. Add any additional anomalies the rules missed (subtle patterns, business logic issues).
3. Write a concise 1–2 sentence operator summary.{failure_note}

Reply ONLY with valid JSON in this exact shape:
{{
  "anomalies": [
    {{
      "order_id": "<id or BATCH>",
      "anomaly_type": "<quantity_spike|impossible_deadline|duplicate_id|material_clustering|priority_inversion|complexity_outlier|other>",
      "severity": "<critical|warning|info>",
      "description": "<one sentence>"
    }}
  ],
  "summary": "<1-2 sentence operator summary>"
}}"""

        try:
            message = self._client.messages.create(  # type: ignore[union-attr]
                model=MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            return _parse_report(raw, len(orders))
        except Exception as exc:
            logger.error("Claude anomaly call failed: %s", exc, exc_info=True)
            return AnomalyReport(
                orders_analysed=len(orders),
                anomalies=rule_anomalies,
                summary=self._build_summary(rule_anomalies),
            )

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, report: AnomalyReport, expected_order_count: int) -> List[str]:
        errors: List[str] = []

        if report.orders_analysed != expected_order_count:
            errors.append(
                f"orders_analysed {report.orders_analysed} != "
                f"expected {expected_order_count}"
            )

        valid_severities = {"critical", "warning", "info"}
        valid_types = {
            "quantity_spike", "impossible_deadline", "duplicate_id",
            "material_clustering", "priority_inversion", "complexity_outlier", "other",
        }
        for i, a in enumerate(report.anomalies):
            if a.severity not in valid_severities:
                errors.append(f"anomaly[{i}] has invalid severity '{a.severity}'")
            if a.anomaly_type not in valid_types:
                errors.append(f"anomaly[{i}] has invalid type '{a.anomaly_type}'")
            if not a.description:
                errors.append(f"anomaly[{i}] has empty description")

        if not report.summary:
            errors.append("summary is empty")

        return errors

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_summary(anomalies: List[Anomaly]) -> str:
        if not anomalies:
            return "No anomalies detected. Batch looks healthy."
        criticals = [a for a in anomalies if a.severity == "critical"]
        warnings = [a for a in anomalies if a.severity == "warning"]
        parts = []
        if criticals:
            parts.append(f"{len(criticals)} critical issue(s)")
        if warnings:
            parts.append(f"{len(warnings)} warning(s)")
        return f"Detected {len(anomalies)} anomaly/anomalies: {', '.join(parts)}. Review before scheduling."


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_dt(raw: str) -> datetime:
    """Parse an ISO datetime string, stripping timezone info."""
    raw = str(raw).rstrip("Z").split("+")[0]
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    raise ValueError(f"Cannot parse datetime: {raw}")


def _parse_report(raw: str, orders_analysed: int) -> AnomalyReport:
    """Extract JSON from Claude's reply and build AnomalyReport."""
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw

    data = json.loads(json_str)
    anomalies = [
        Anomaly(
            order_id=str(a.get("order_id", "")),
            anomaly_type=str(a.get("anomaly_type", "other")),
            severity=str(a.get("severity", "info")),
            description=str(a.get("description", "")),
        )
        for a in data.get("anomalies", [])
    ]
    return AnomalyReport(
        orders_analysed=orders_analysed,
        anomalies=anomalies,
        summary=str(data.get("summary", "")),
    )
