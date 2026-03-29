"""Ollama-powered customer discovery synthesis agent."""

import json
import logging
import os
import urllib.request

from discovery.prompts import (
    EXTRACT_INSIGHTS_SYSTEM,
    NEXT_QUESTIONS_SYSTEM,
    SYNTHESIZE_PATTERNS_SYSTEM,
)

logger = logging.getLogger("millforge.discovery")

_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
_MAX_TOKENS = 4096


def _chat(system: str, user: str) -> str:
    """Send a chat request to Ollama and return the response text."""
    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_predict": _MAX_TOKENS},
    }).encode()

    req = urllib.request.Request(
        f"{_OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"].strip()


def _parse_json(raw: str) -> list | dict:
    """Strip markdown code fences and parse JSON."""
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    # Find the first [ or { to handle leading prose
    for i, ch in enumerate(raw):
        if ch in ("[", "{"):
            raw = raw[i:]
            break
    return json.loads(raw)


def extract_insights(transcript: str, metadata: dict) -> list[dict]:
    """Run transcript through Ollama and return structured insights.

    Each insight: category, content, severity (1-3), quote (str | null).
    Returns [] on any failure.
    """
    user_content = (
        f"Shop: {metadata.get('shop_name', 'Unknown')} | "
        f"Role: {metadata.get('role', 'Unknown')} | "
        f"Size: {metadata.get('shop_size', 'Unknown')}\n\n"
        f"Transcript:\n{transcript}"
    )
    try:
        raw = _chat(EXTRACT_INSIGHTS_SYSTEM, user_content)
        return _parse_json(raw)
    except Exception as exc:
        logger.error("extract_insights failed: %s", exc)
        return []


def synthesize_patterns(insights: list[dict], interview_count: int) -> list[dict]:
    """Identify recurring patterns across all insights.

    Each pattern: label, insight_ids, frequency, evidence_quotes, feature_tag.
    Returns [] on failure.
    """
    if not insights:
        return []
    user_content = (
        f"Total interviews analyzed: {interview_count}\n\n"
        f"Aggregated insights (JSON):\n{json.dumps(insights, indent=2)}"
    )
    try:
        raw = _chat(SYNTHESIZE_PATTERNS_SYSTEM, user_content)
        return _parse_json(raw)
    except Exception as exc:
        logger.error("synthesize_patterns failed: %s", exc)
        return []


def generate_next_questions(patterns: list[dict], interview_count: int) -> list[dict]:
    """Generate 5 targeted interview questions based on current pattern gaps.

    Each question: question, rationale, follow_up.
    Returns a single fallback question on failure.
    """
    user_content = (
        f"Interviews completed so far: {interview_count}\n\n"
        f"Patterns identified so far:\n{json.dumps(patterns, indent=2)}"
        if patterns
        else f"Interviews completed so far: {interview_count}\n\nNo patterns identified yet — this is early-stage discovery."
    )
    try:
        raw = _chat(NEXT_QUESTIONS_SYSTEM, user_content)
        return _parse_json(raw)
    except Exception as exc:
        logger.error("generate_next_questions failed: %s", exc)
        return [
            {
                "question": "Walk me through how you decide what runs next when you start the shift.",
                "rationale": "Surfaces scheduling workflow and whether pain is acute.",
                "follow_up": "How long does that process take? Has it ever caused a job to be late?",
            }
        ]
