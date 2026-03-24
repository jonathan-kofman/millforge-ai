"""
MillForge Natural Language Schedule Override Agent

Translates a plain-English instruction into priority overrides for a batch of
orders, then returns the modified order list for the caller to schedule.

Examples:
  "rush the titanium orders"        → titanium orders get priority 1
  "defer low priority steel"        → steel orders with priority >= 7 get priority 10
  "urgent: all aerospace orders"    → orders with 'aerospace' in dimensions → priority 1
  "push copper to end of queue"     → copper orders → priority 9

Uses Claude when ANTHROPIC_API_KEY is present; falls back to a keyword
heuristic (CI-safe, deterministic).

Returns a PriorityOverride list — the caller applies them and runs the scheduler.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"
MAX_RETRIES = 3

MATERIALS = {"steel", "aluminum", "titanium", "copper"}
URGENCY_KEYWORDS = {"rush", "urgent", "asap", "expedite", "critical", "emergency", "priority"}
DEFER_KEYWORDS = {"defer", "delay", "postpone", "push", "deprioritize", "later", "end"}


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

@dataclass
class PriorityOverride:
    order_id: str
    new_priority: int  # 1 (highest) – 10 (lowest)
    reason: str


@dataclass
class NLScheduleResult:
    instruction: str
    overrides: List[PriorityOverride]
    summary: str
    validation_failures: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class NLSchedulerAgent:
    """
    Translates natural-language scheduling instructions into priority overrides.
    """

    def __init__(self, api_key: Optional[str] = None):
        self._api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        self._client = None
        if self._api_key:
            try:
                import anthropic  # noqa: PLC0415
                self._client = anthropic.Anthropic(api_key=self._api_key)
                logger.info("NLSchedulerAgent: Claude client initialised (%s)", MODEL)
            except ImportError:
                logger.warning("anthropic package not installed; using keyword heuristic")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def interpret(
        self,
        instruction: str,
        orders: List[Dict],
    ) -> NLScheduleResult:
        """
        Parse the instruction and return priority overrides for the given orders.

        Args:
            instruction: Plain-English scheduling override.
            orders: List of order dicts (must have order_id, material, priority).

        Returns:
            NLScheduleResult with a list of PriorityOverride objects.
        """
        failures: List[str] = []
        best: Optional[NLScheduleResult] = None

        for attempt in range(MAX_RETRIES):
            if self._client is not None:
                result = self._claude_interpret(instruction, orders, failures)
            else:
                result = self._heuristic_interpret(instruction, orders)

            errors = self._validate(result, orders)
            if not errors:
                result.validation_failures = []
                return result

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = result
            logger.warning(
                "NLSchedulerAgent validation failed attempt %d: %s", attempt + 1, errors
            )

        assert best is not None
        best.validation_failures = failures
        return best

    # ------------------------------------------------------------------
    # Keyword heuristic (CI-safe)
    # ------------------------------------------------------------------

    def _heuristic_interpret(
        self,
        instruction: str,
        orders: List[Dict],
    ) -> NLScheduleResult:
        text = instruction.lower()
        overrides: List[PriorityOverride] = []

        # Determine intent: urgency or deferral
        is_urgent = any(kw in text for kw in URGENCY_KEYWORDS)
        is_defer = any(kw in text for kw in DEFER_KEYWORDS)
        new_priority = 1 if is_urgent else (9 if is_defer else None)

        # Determine which materials / keywords are targeted
        targeted_materials = {mat for mat in MATERIALS if mat in text}
        # Also pick up phrases like "aerospace", "low priority"
        low_priority_filter = "low priority" in text or "low-priority" in text

        for o in orders:
            oid = str(o.get("order_id", ""))
            mat = str(o.get("material", "")).lower()
            cur_priority = int(o.get("priority", 5))

            if targeted_materials and mat not in targeted_materials:
                continue

            if low_priority_filter and cur_priority < 6:
                continue  # only affect genuinely low-priority orders

            if new_priority is not None and new_priority != cur_priority:
                overrides.append(PriorityOverride(
                    order_id=oid,
                    new_priority=new_priority,
                    reason=f"heuristic: '{instruction[:60]}'"
                ))

        action = "urgent" if is_urgent else ("deferred" if is_defer else "unchanged")
        mats = ", ".join(sorted(targeted_materials)) or "all materials"
        summary = (
            f"{len(overrides)} order(s) marked as {action} "
            f"({mats} targeted by instruction)."
        )

        return NLScheduleResult(
            instruction=instruction,
            overrides=overrides,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Claude-backed interpretation
    # ------------------------------------------------------------------

    def _claude_interpret(
        self,
        instruction: str,
        orders: List[Dict],
        prior_failures: List[str],
    ) -> NLScheduleResult:
        order_summary = [
            {"order_id": o.get("order_id"), "material": o.get("material"),
             "quantity": o.get("quantity"), "priority": o.get("priority"),
             "complexity": o.get("complexity")}
            for o in orders
        ]
        failure_note = (
            f"\n\nPrior validation failures to fix:\n{chr(10).join(prior_failures)}"
            if prior_failures else ""
        )

        prompt = f"""You are a production scheduling AI for a precision metal mill.

The operator issued this instruction: "{instruction}"

Current order list:
{json.dumps(order_summary, indent=2)}

Your job: decide which orders need their priority adjusted to honour the instruction.
Priority scale: 1 = most urgent, 10 = lowest priority.{failure_note}

Rules:
- Only include orders whose priority should actually change.
- new_priority must be an integer in [1, 10].
- Give a brief reason per override.
- Write a 1-sentence summary of what you did.

Reply ONLY with valid JSON in this exact shape:
{{
  "overrides": [
    {{"order_id": "<id>", "new_priority": <int 1-10>, "reason": "<one sentence>"}}
  ],
  "summary": "<1-sentence summary>"
}}"""

        try:
            message = self._client.messages.create(  # type: ignore[union-attr]
                model=MODEL,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = message.content[0].text
            return _parse_result(raw, instruction)
        except Exception as exc:
            logger.error("Claude NL schedule call failed: %s", exc, exc_info=True)
            return self._heuristic_interpret(instruction, orders)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(
        self,
        result: NLScheduleResult,
        orders: List[Dict],
    ) -> List[str]:
        errors: List[str] = []
        valid_ids = {str(o.get("order_id", "")) for o in orders}

        for i, ov in enumerate(result.overrides):
            if ov.order_id not in valid_ids:
                errors.append(
                    f"override[{i}] references unknown order_id '{ov.order_id}'"
                )
            if not (1 <= ov.new_priority <= 10):
                errors.append(
                    f"override[{i}] has invalid new_priority {ov.new_priority} "
                    f"(must be 1-10)"
                )
            if not ov.reason:
                errors.append(f"override[{i}] has empty reason")

        if not result.summary:
            errors.append("summary is empty")

        return errors


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_result(raw: str, instruction: str) -> NLScheduleResult:
    match = re.search(r"```(?:json)?\s*([\s\S]+?)```", raw)
    json_str = match.group(1) if match else raw

    data = json.loads(json_str)
    overrides = [
        PriorityOverride(
            order_id=str(ov.get("order_id", "")),
            new_priority=int(ov.get("new_priority", 5)),
            reason=str(ov.get("reason", "")),
        )
        for ov in data.get("overrides", [])
    ]
    return NLScheduleResult(
        instruction=instruction,
        overrides=overrides,
        summary=str(data.get("summary", "")),
    )
