"""
Shared LLM service for text generation tasks.

Used by:
- Logbook (#23) — AI shift summaries
- AS9100 (#5) — procedure generation
- Drawing Reader (#6) — GD&T interpretation assistance

Reuses the same Ollama HTTP pattern as discovery/agent.py.
"""

import json
import logging
import os
import urllib.request

logger = logging.getLogger("millforge.llm")

_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")
_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
_MAX_TOKENS = 4096


def _chat(system: str, user: str, max_tokens: int = _MAX_TOKENS) -> str:
    """Send a chat request to Ollama and return the response text."""
    payload = json.dumps({
        "model": _MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"num_predict": max_tokens},
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
    for i, ch in enumerate(raw):
        if ch in ("[", "{"):
            raw = raw[i:]
            break
    return json.loads(raw)


def summarize_shift(entries: list[dict]) -> str:
    """Generate a shift summary from logbook entries.

    Returns a concise morning briefing. Returns fallback text on any failure.
    """
    system = (
        "You are a shop floor shift summary generator. Given a list of logbook entries "
        "from a manufacturing shift, generate a concise morning briefing for the shop owner. "
        "Focus on: issues that need attention, machine status changes, production notes, "
        "and anything the next shift needs to know. Be direct and specific. "
        "Format as bullet points under headers: Issues, Production Notes, Handover Items."
    )
    entries_text = "\n\n".join(
        f"[{e.get('category', 'note').upper()}] {e.get('title', '')}\n"
        f"Machine: {e.get('machine_name', 'N/A')} | Severity: {e.get('severity', 'N/A')}\n"
        f"{e.get('body', '')}"
        for e in entries
    )
    try:
        return _chat(system, entries_text)
    except Exception as exc:
        logger.error("Shift summary generation failed: %s", exc)
        return f"Summary unavailable — {len(entries)} entries logged this shift."


def generate_procedure(clause_number: str, clause_title: str,
                       clause_description: str, shop_context: dict) -> str:
    """Generate an AS9100D QMS procedure for a specific clause.

    Returns markdown procedure text. Returns fallback on failure.
    """
    system = (
        "You are an AS9100D quality management system expert. Generate a complete, "
        "implementable QMS procedure for a small machine shop (5-20 employees). "
        "The procedure must include: Purpose, Scope, Responsibilities, Procedure Steps, "
        "Records Required, and Review Frequency. Use plain language a machinist can follow. "
        "Format in markdown."
    )
    user = (
        f"Clause: {clause_number} — {clause_title}\n"
        f"Description: {clause_description}\n\n"
        f"Shop context:\n"
        f"- Shop name: {shop_context.get('shop_name', 'N/A')}\n"
        f"- Machine count: {shop_context.get('machine_count', 'N/A')}\n"
        f"- Materials: {shop_context.get('materials', 'N/A')}\n"
        f"- Shifts per day: {shop_context.get('shifts_per_day', 'N/A')}\n"
    )
    try:
        return _chat(system, user, max_tokens=8192)
    except Exception as exc:
        logger.error("Procedure generation failed: %s", exc)
        return (
            f"# {clause_number} — {clause_title}\n\n"
            f"*Procedure generation requires Ollama. Run `ollama serve` and retry.*"
        )


def extract_structured(text: str, schema_description: str) -> dict:
    """Use LLM to extract structured data from unstructured text.

    Returns parsed JSON dict. Returns empty dict on failure.
    """
    system = (
        "You are a data extraction assistant. Extract structured data from the text "
        "according to the schema described. Return ONLY valid JSON, no commentary."
    )
    user = f"Schema: {schema_description}\n\nText:\n{text}"
    try:
        raw = _chat(system, user)
        result = _parse_json(raw)
        return result if isinstance(result, dict) else {}
    except Exception as exc:
        logger.error("Structured extraction failed: %s", exc)
        return {}
