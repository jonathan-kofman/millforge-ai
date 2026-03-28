"""Claude-powered customer discovery synthesis agent."""

import json
import logging
import os
from typing import Optional

import anthropic

from discovery.prompts import (
    EXTRACT_INSIGHTS_SYSTEM,
    NEXT_QUESTIONS_SYSTEM,
    SYNTHESIZE_PATTERNS_SYSTEM,
)

logger = logging.getLogger("millforge.discovery")

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 4096


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))


def extract_insights(transcript: str, metadata: dict) -> list[dict]:
    """Run transcript through Claude and return a list of structured insights.

    Each insight has: category, content, severity (1–3), quote (str | null).
    Returns an empty list (not an exception) if the API call fails.
    """
    user_content = (
        f"Shop: {metadata.get('shop_name', 'Unknown')} | "
        f"Role: {metadata.get('role', 'Unknown')} | "
        f"Size: {metadata.get('shop_size', 'Unknown')}\n\n"
        f"Transcript:\n{transcript}"
    )
    try:
        response = _client().messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=EXTRACT_INSIGHTS_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        # Claude sometimes wraps JSON in a code block
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        logger.error("extract_insights failed: %s", exc)
        return []


def synthesize_patterns(insights: list[dict], interview_count: int) -> list[dict]:
    """Identify recurring patterns across all insights.

    Each pattern has: label, insight_ids, frequency, evidence_quotes, feature_tag.
    Returns an empty list if the API call fails.
    """
    if not insights:
        return []
    user_content = (
        f"Total interviews analyzed: {interview_count}\n\n"
        f"Aggregated insights (JSON):\n{json.dumps(insights, indent=2)}"
    )
    try:
        response = _client().messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=SYNTHESIZE_PATTERNS_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        logger.error("synthesize_patterns failed: %s", exc)
        return []


def generate_next_questions(
    patterns: list[dict], interview_count: int
) -> list[dict]:
    """Generate 5 targeted interview questions based on current pattern gaps.

    Each question has: question, rationale, follow_up.
    Returns a fallback list if the API call fails.
    """
    user_content = (
        f"Interviews completed so far: {interview_count}\n\n"
        f"Patterns identified so far:\n{json.dumps(patterns, indent=2)}"
        if patterns
        else f"Interviews completed so far: {interview_count}\n\nNo patterns identified yet — this is early-stage discovery."
    )
    try:
        response = _client().messages.create(
            model=_MODEL,
            max_tokens=_MAX_TOKENS,
            system=NEXT_QUESTIONS_SYSTEM,
            messages=[{"role": "user", "content": user_content}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw)
    except Exception as exc:
        logger.error("generate_next_questions failed: %s", exc)
        return [
            {
                "question": "Walk me through how you decide what runs next when you start the shift.",
                "rationale": "Surfaces scheduling workflow and whether pain is acute.",
                "follow_up": "How long does that process take? Has it ever caused a job to be late?",
            }
        ]
