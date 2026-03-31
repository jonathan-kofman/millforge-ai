"""
Manufacturing Intelligence Agent — Ollama-powered reasoning for all
manufacturing decisions.

Every decision in the manufacturing layer flows through this agent:
  - Process routing (which process + machine for a given part)
  - Validation (is this feasible? what are the risks?)
  - Estimation (cycle time, cost, setup time)
  - Work order planning (multi-step sequencing)
  - Setup sheet generation (operator instructions)
  - Web research (material properties, process capabilities)

When Ollama is unavailable, returns None so callers can fall back to
physics-based models.  No hardcoded decisions live here — only LLM calls.

Uses llama3.2:latest by default (small, fast, low memory).
Override with MFG_OLLAMA_MODEL env var.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.parse
from typing import Any, Optional

logger = logging.getLogger("millforge.manufacturing.agent")

# ---------------------------------------------------------------------------
# Configuration — fully environment-driven, zero hardcoded defaults for model
# ---------------------------------------------------------------------------

_OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
# Small, fast model — avoids OOM on developer machines.
# Override via MFG_OLLAMA_MODEL env var if you want a different model.
_MFG_MODEL = os.getenv("MFG_OLLAMA_MODEL", "llama3.2:latest")
_MAX_TOKENS = 512   # keep responses short to save memory
_TIMEOUT = 30       # seconds — fail fast, fall back to physics

# Web search API keys — all optional; falls back to Wikipedia + DuckDuckGo
_BING_KEY = os.getenv("BING_SEARCH_KEY", "")          # Azure Cognitive Services
_SERP_KEY = os.getenv("SERPAPI_KEY", "")               # SerpAPI (Google results)
_WEB_TIMEOUT = 8   # seconds per HTTP call


def _chat(system: str, user: str, temperature: float = 0.3) -> str:
    """Send a chat request to Ollama and return the raw response text."""
    model = _MFG_MODEL
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {
            "num_predict": _MAX_TOKENS,
            "temperature": temperature,
        },
    }).encode()

    req = urllib.request.Request(
        f"{_OLLAMA_URL}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        data = json.loads(resp.read())
    return data["message"]["content"].strip()


def _parse_json(raw: str) -> dict | list:
    """Strip markdown fences and leading prose, then parse JSON."""
    # Strip code fences
    if "```" in raw:
        parts = raw.split("```")
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("json"):
                stripped = stripped[4:].strip()
            if stripped and stripped[0] in ("{", "["):
                return json.loads(stripped)

    # Find first JSON object/array
    for i, ch in enumerate(raw):
        if ch in ("{", "["):
            return json.loads(raw[i:])

    return json.loads(raw)


# ---------------------------------------------------------------------------
# Web access — fetch material data, process specs, live prices, standards
# ---------------------------------------------------------------------------

_HEADERS = {
    "User-Agent": "MillForge/1.0 (manufacturing-intelligence; +https://millforge.ai)",
    "Accept": "application/json, text/plain, */*",
}


def fetch_url(url: str, *, max_chars: int = 3000) -> Optional[str]:
    """
    Fetch a URL and return plain text (HTML tags stripped, truncated).
    Returns None on any failure.
    """
    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_WEB_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        # Strip HTML tags crudely — good enough for manufacturing specs
        import re
        text = re.sub(r"<[^>]+>", " ", raw)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:max_chars] if text else None
    except Exception as exc:
        logger.debug("fetch_url failed for %s: %s", url, exc)
        return None


def web_research(query: str) -> Optional[str]:
    """
    Multi-source web research for manufacturing context.

    Source priority:
      1. Bing Search API (BING_SEARCH_KEY env var) — richest results
      2. SerpAPI (SERPAPI_KEY env var) — Google results
      3. Wikipedia API — excellent for materials, alloys, processes
      4. DuckDuckGo Instant Answer — last-resort fallback

    Returns concatenated text snippets, or None if all sources fail.
    """
    encoded = urllib.parse.quote_plus(query)
    results: list[str] = []

    # 1. Bing Search API
    if _BING_KEY and not results:
        try:
            url = f"https://api.bing.microsoft.com/v7.0/search?q={encoded}&count=5&mkt=en-US"
            req = urllib.request.Request(url, headers={**_HEADERS, "Ocp-Apim-Subscription-Key": _BING_KEY})
            with urllib.request.urlopen(req, timeout=_WEB_TIMEOUT) as resp:
                data = json.loads(resp.read())
            for item in data.get("webPages", {}).get("value", [])[:4]:
                snippet = item.get("snippet", "")
                if snippet:
                    results.append(snippet)
            logger.debug("Bing returned %d snippets for '%s'", len(results), query)
        except Exception as exc:
            logger.debug("Bing search failed: %s", exc)

    # 2. SerpAPI (Google)
    if _SERP_KEY and not results:
        try:
            url = f"https://serpapi.com/search.json?q={encoded}&api_key={_SERP_KEY}&num=5"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_WEB_TIMEOUT) as resp:
                data = json.loads(resp.read())
            for item in data.get("organic_results", [])[:4]:
                snippet = item.get("snippet", "")
                if snippet:
                    results.append(snippet)
            logger.debug("SerpAPI returned %d snippets for '%s'", len(results), query)
        except Exception as exc:
            logger.debug("SerpAPI search failed: %s", exc)

    # 3. Wikipedia — best for alloys, materials, manufacturing processes
    if not results:
        try:
            # Try direct page summary first
            page_title = urllib.parse.quote(query.replace(" ", "_"))
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{page_title}"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_WEB_TIMEOUT) as resp:
                data = json.loads(resp.read())
            if data.get("extract"):
                results.append(data["extract"])
        except Exception:
            pass

        if not results:
            try:
                # Wikipedia full-text search
                url = (
                    f"https://en.wikipedia.org/w/api.php"
                    f"?action=query&list=search&srsearch={encoded}"
                    f"&format=json&srlimit=3&srprop=snippet"
                )
                req = urllib.request.Request(url, headers=_HEADERS)
                with urllib.request.urlopen(req, timeout=_WEB_TIMEOUT) as resp:
                    data = json.loads(resp.read())
                import re
                for hit in data.get("query", {}).get("search", [])[:2]:
                    snippet = re.sub(r"<[^>]+>", "", hit.get("snippet", ""))
                    if snippet:
                        results.append(snippet)
            except Exception as exc:
                logger.debug("Wikipedia search failed: %s", exc)

    # 4. DuckDuckGo Instant Answer — last resort
    if not results:
        try:
            url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1"
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=_WEB_TIMEOUT) as resp:
                data = json.loads(resp.read())
            if data.get("Abstract"):
                results.append(data["Abstract"])
            for topic in data.get("RelatedTopics", [])[:3]:
                if isinstance(topic, dict) and topic.get("Text"):
                    results.append(topic["Text"])
        except Exception as exc:
            logger.debug("DuckDuckGo failed: %s", exc)

    if not results:
        logger.debug("All web sources returned nothing for '%s'", query)
        return None

    return "\n\n".join(results)


def research_material(material_name: str) -> Optional[dict]:
    """
    Research material properties via web + LLM interpretation.
    Returns structured material data or None.
    """
    web_data = web_research(f"{material_name} material properties machinability manufacturing")
    if not web_data:
        return None

    try:
        system = (
            "You are a materials engineer. Given web search results about a material, "
            "extract structured manufacturing-relevant properties.\n\n"
            "Return JSON:\n"
            '{"material": "name", "family": "ferrous|nonferrous|polymer|composite|ceramic", '
            '"machinability_rating": 0.0-1.0, "hardness_range": "HRC range", '
            '"thermal_conductivity": "W/mK", "weldability": "excellent|good|fair|poor|not_recommended", '
            '"common_processes": ["list of suitable processes"], '
            '"notes": "key manufacturing considerations"}\n\n'
            "Return ONLY valid JSON."
        )
        raw = _chat(system, f"Material: {material_name}\n\nSearch results:\n{web_data}", temperature=0.2)
        return _parse_json(raw)
    except Exception as exc:
        logger.debug("Material research LLM failed: %s", exc)
        return None


def research_process(process_name: str, context: str = "") -> Optional[dict]:
    """
    Research a manufacturing process via web + LLM.
    Returns structured process data or None.
    """
    web_data = web_research(f"{process_name} manufacturing process capabilities tolerances")
    if not web_data:
        return None

    try:
        system = (
            "You are a manufacturing process engineer. Given web search results about a process, "
            "extract structured capabilities.\n\n"
            "Return JSON:\n"
            '{"process": "name", "typical_tolerances_mm": [0.01, 0.1], '
            '"compatible_materials": ["list"], "incompatible_materials": ["list"], '
            '"typical_batch_sizes": {"min": 1, "max": 100000}, '
            '"setup_time_range_minutes": [15, 60], '
            '"notes": "key process considerations"}\n\n'
            "Return ONLY valid JSON."
        )
        user_msg = f"Process: {process_name}"
        if context:
            user_msg += f"\nContext: {context}"
        user_msg += f"\n\nSearch results:\n{web_data}"
        raw = _chat(system, user_msg, temperature=0.2)
        return _parse_json(raw)
    except Exception as exc:
        logger.debug("Process research LLM failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Core agentic functions — every manufacturing decision flows through here
# ---------------------------------------------------------------------------

def advise_routing(
    intent_json: str,
    candidates_json: str,
) -> Optional[dict]:
    """
    LLM-powered routing advisor. Given a manufacturing intent and scored
    candidates, adjusts weights and recommends the best option.

    Returns structured advice dict, or None if Ollama unavailable.
    """
    from manufacturing.prompts import ROUTING_ADVISOR_SYSTEM

    # Optionally enrich with web research on the material
    try:
        intent = json.loads(intent_json)
        material_name = intent.get("material", {}).get("material_name", "")
        if material_name:
            mat_data = research_material(material_name)
            if mat_data:
                intent["_web_material_data"] = mat_data
                intent_json = json.dumps(intent)
    except Exception:
        pass

    user_msg = (
        f"Manufacturing Intent:\n{intent_json}\n\n"
        f"Candidate Options (with raw scores):\n{candidates_json}"
    )
    try:
        raw = _chat(ROUTING_ADVISOR_SYSTEM, user_msg)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Routing advisor failed: %s", exc)
        return None


def advise_validation(
    intent_json: str,
    process_family: str,
) -> Optional[dict]:
    """
    LLM-powered validation advisor. Assesses feasibility of a manufacturing
    intent for a given process, with web-enriched material knowledge.

    Returns structured validation dict, or None if Ollama unavailable.
    """
    from manufacturing.prompts import VALIDATION_ADVISOR_SYSTEM

    # Enrich with web research
    try:
        intent = json.loads(intent_json)
        material_name = intent.get("material", {}).get("material_name", "")
        if material_name:
            mat_data = research_material(material_name)
            proc_data = research_process(process_family, f"for {material_name}")
            enrichment = ""
            if mat_data:
                enrichment += f"\nMaterial research: {json.dumps(mat_data)}"
            if proc_data:
                enrichment += f"\nProcess research: {json.dumps(proc_data)}"
            if enrichment:
                intent_json = intent_json.rstrip("}") + f', "_web_research": {json.dumps(enrichment)}' + "}"
    except Exception:
        pass

    user_msg = (
        f"Manufacturing Intent:\n{intent_json}\n\n"
        f"Selected Process: {process_family}"
    )
    try:
        raw = _chat(VALIDATION_ADVISOR_SYSTEM, user_msg)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Validation advisor failed: %s", exc)
        return None


def advise_estimation(
    intent_json: str,
    process_family: str,
    baseline_cycle_time_minutes: float,
    baseline_cost_usd: float,
) -> Optional[dict]:
    """
    LLM-powered estimation advisor. Reviews physics-based estimates
    and adjusts based on manufacturing knowledge.

    Returns adjusted estimates dict, or None if Ollama unavailable.
    """
    from manufacturing.prompts import ESTIMATION_ADVISOR_SYSTEM

    user_msg = (
        f"Manufacturing Intent:\n{intent_json}\n\n"
        f"Process: {process_family}\n"
        f"Baseline cycle time: {baseline_cycle_time_minutes:.1f} minutes/unit\n"
        f"Baseline total cost: ${baseline_cost_usd:.2f}"
    )
    try:
        raw = _chat(ESTIMATION_ADVISOR_SYSTEM, user_msg)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Estimation advisor failed: %s", exc)
        return None


def advise_cost(
    intent_json: str,
    process_family: str,
    baseline_cost_usd: float,
) -> Optional[dict]:
    """
    LLM-powered cost advisor. Reviews a physics-based cost estimate and
    adjusts for material premiums, scrap rate, and process efficiency.

    Returns adjustment dict with factor and reasoning, or None if Ollama unavailable.
    """
    from manufacturing.prompts import COST_ADVISOR_SYSTEM

    user_msg = (
        f"Manufacturing Intent:\n{intent_json}\n\n"
        f"Process: {process_family}\n"
        f"Physics-based cost estimate: ${baseline_cost_usd:.2f} total"
    )
    try:
        raw = _chat(COST_ADVISOR_SYSTEM, user_msg)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Cost advisor failed: %s", exc)
        return None


def advise_feasibility(
    intent_json: str,
    issues_json: str,
) -> Optional[dict]:
    """
    LLM-powered feasibility advisor. When a job is flagged as infeasible,
    suggests workarounds with web-researched alternatives.

    Returns workaround suggestions dict, or None if Ollama unavailable.
    """
    from manufacturing.prompts import FEASIBILITY_ADVISOR_SYSTEM

    user_msg = (
        f"Manufacturing Intent:\n{intent_json}\n\n"
        f"Issues Found:\n{issues_json}"
    )
    try:
        raw = _chat(FEASIBILITY_ADVISOR_SYSTEM, user_msg)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Feasibility advisor failed: %s", exc)
        return None


def generate_setup_sheet(
    intent_json: str,
    process_family: str,
    machine_name: str,
) -> Optional[dict]:
    """
    LLM-generated setup sheet with operator instructions.
    No templates — fully generated from manufacturing context.
    """
    from manufacturing.prompts import SETUP_SHEET_SYSTEM

    # Research the process for context
    proc_data = research_process(process_family)
    enrichment = ""
    if proc_data:
        enrichment = f"\nProcess reference data: {json.dumps(proc_data)}"

    user_msg = (
        f"Manufacturing Intent:\n{intent_json}\n\n"
        f"Process: {process_family}\n"
        f"Machine: {machine_name}"
        f"{enrichment}"
    )
    try:
        raw = _chat(SETUP_SHEET_SYSTEM, user_msg, temperature=0.4)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Setup sheet generation failed: %s", exc)
        return None


def plan_work_order(
    intent_json: str,
) -> Optional[dict]:
    """
    LLM-powered work order planner. Generates a multi-step manufacturing
    plan from a manufacturing intent — no hardcoded sequencing logic.

    Returns step sequence dict, or None if Ollama unavailable.
    """
    from manufacturing.prompts import WORK_ORDER_PLANNER_SYSTEM

    # Enrich with material + process web research
    try:
        intent = json.loads(intent_json)
        material_name = intent.get("material", {}).get("material_name", "")
        if material_name:
            mat_data = research_material(material_name)
            if mat_data:
                intent_json = intent_json.rstrip("}") + f', "_material_research": {json.dumps(mat_data)}' + "}"
    except Exception:
        pass

    try:
        raw = _chat(WORK_ORDER_PLANNER_SYSTEM, intent_json, temperature=0.4)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Work order planning failed: %s", exc)
        return None


def assess_quality_risk(
    process_family: str,
    material_name: str,
    tolerance_class: str,
    batch_size: int,
) -> Optional[dict]:
    """
    LLM-powered quality risk assessment. Identifies likely defects and
    recommends inspection strategy — fully agentic, no hardcoded defect maps.
    """
    system = (
        "You are a manufacturing quality engineer. Given a process, material, tolerance, "
        "and batch size, assess quality risks and recommend inspection strategy.\n\n"
        "Return JSON:\n"
        '{"risk_level": "low|medium|high|critical", '
        '"likely_defects": [{"defect": "name", "probability": "low|medium|high", "cause": "why"}], '
        '"inspection_strategy": {"method": "description", "frequency": "every Nth part or 100%", '
        '"critical_dimensions": ["what to measure"]}, '
        '"process_controls": ["preventive measures to reduce defects"]}\n\n'
        "Return ONLY valid JSON."
    )
    # Research the material-process combo
    web_data = web_research(f"{process_family} {material_name} common defects quality issues")
    user_msg = (
        f"Process: {process_family}\n"
        f"Material: {material_name}\n"
        f"Tolerance: {tolerance_class}\n"
        f"Batch size: {batch_size}"
    )
    if web_data:
        user_msg += f"\n\nReference data:\n{web_data}"

    try:
        raw = _chat(system, user_msg)
        return _parse_json(raw)
    except Exception as exc:
        logger.warning("Quality risk assessment failed: %s", exc)
        return None
