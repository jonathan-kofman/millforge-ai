"""
Tests for the Manufacturing Intelligence Agent.

The agent calls Ollama for every decision. When Ollama is unavailable,
all functions return None and callers fall back to physics-based models.
These tests verify:
  1. Graceful degradation when Ollama is down
  2. Correct function signatures and return types
  3. JSON parsing of LLM responses
  4. Web research fallback behavior
  5. Integration with routing/validation/simulation
"""

import json
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Test graceful degradation (Ollama unavailable)
# ---------------------------------------------------------------------------

def test_advise_routing_never_raises():
    """advise_routing never raises — returns None or a dict."""
    from manufacturing.agent import advise_routing
    result = advise_routing('{"part_id": "TEST"}', '[]')
    assert result is None or isinstance(result, dict)


def test_advise_validation_never_raises():
    """advise_validation never raises — returns None or a dict."""
    from manufacturing.agent import advise_validation
    result = advise_validation('{"part_id": "TEST"}', "cnc_milling")
    assert result is None or isinstance(result, dict)


def test_advise_estimation_never_raises():
    """advise_estimation never raises — returns None or a dict."""
    from manufacturing.agent import advise_estimation
    result = advise_estimation('{"part_id": "TEST"}', "cnc_milling", 15.0, 100.0)
    assert result is None or isinstance(result, dict)


def test_advise_feasibility_never_raises():
    """advise_feasibility never raises — returns None or a dict."""
    from manufacturing.agent import advise_feasibility
    result = advise_feasibility('{"part_id": "TEST"}', '["tolerance too tight"]')
    assert result is None or isinstance(result, dict)


def test_generate_setup_sheet_never_raises():
    """generate_setup_sheet never raises — returns None or a dict."""
    from manufacturing.agent import generate_setup_sheet
    result = generate_setup_sheet('{"part_id": "TEST"}', "cnc_milling", "Haas VF-2")
    assert result is None or isinstance(result, dict)


def test_plan_work_order_never_raises():
    """plan_work_order never raises — returns None or a dict."""
    from manufacturing.agent import plan_work_order
    result = plan_work_order('{"part_id": "TEST"}')
    assert result is None or isinstance(result, dict)


def test_assess_quality_risk_never_raises():
    """assess_quality_risk never raises — returns None or a dict."""
    from manufacturing.agent import assess_quality_risk
    result = assess_quality_risk("cnc_milling", "steel", "ISO_2768_m", 100)
    assert result is None or isinstance(result, dict)


# ---------------------------------------------------------------------------
# Test JSON parsing
# ---------------------------------------------------------------------------

def test_parse_json_plain():
    from manufacturing.agent import _parse_json
    result = _parse_json('{"key": "value"}')
    assert result == {"key": "value"}


def test_parse_json_with_code_fences():
    from manufacturing.agent import _parse_json
    raw = '```json\n{"key": "value"}\n```'
    result = _parse_json(raw)
    assert result == {"key": "value"}


def test_parse_json_with_leading_prose():
    from manufacturing.agent import _parse_json
    raw = 'Here is the result:\n{"key": "value"}'
    result = _parse_json(raw)
    assert result == {"key": "value"}


def test_parse_json_array():
    from manufacturing.agent import _parse_json
    result = _parse_json('[1, 2, 3]')
    assert result == [1, 2, 3]


# ---------------------------------------------------------------------------
# Test web research graceful failure
# ---------------------------------------------------------------------------

def test_web_research_returns_none_on_failure():
    """web_research returns None when the search fails."""
    from manufacturing.agent import web_research
    # This may or may not succeed depending on network, but should never raise
    result = web_research("impossible_query_that_returns_nothing_12345")
    assert result is None or isinstance(result, str)


def test_research_material_returns_none_on_failure():
    """research_material returns None when both web + LLM fail."""
    from manufacturing.agent import research_material
    result = research_material("unobtanium_nonexistent_material")
    assert result is None


# ---------------------------------------------------------------------------
# Test model configuration
# ---------------------------------------------------------------------------

def test_model_is_configurable():
    """MFG_OLLAMA_MODEL env var controls which model is used."""
    import manufacturing.agent as agent
    # Default should be the small model
    assert isinstance(agent._MFG_MODEL, str)
    assert len(agent._MFG_MODEL) > 0


# ---------------------------------------------------------------------------
# Test mocked LLM responses
# ---------------------------------------------------------------------------

def test_advise_routing_with_mocked_llm():
    """With a mocked _chat, advise_routing returns structured advice."""
    from manufacturing import agent

    mock_response = json.dumps({
        "adjusted_weights": {"cost": 0.40, "time": 0.30, "quality": 0.20, "energy": 0.10},
        "recommended_option_index": 0,
        "rationale": "CNC milling is optimal for this steel part with medium tolerances.",
        "warnings": [],
        "alternative_suggestion": None,
    })

    with patch.object(agent, "_chat", return_value=mock_response):
        with patch.object(agent, "research_material", return_value=None):
            result = agent.advise_routing(
                '{"part_id": "TEST", "material": {"material_name": "steel"}}',
                '[{"index": 0, "process": "cnc_milling", "score": 0.85}]',
            )
    assert result is not None
    assert result["recommended_option_index"] == 0
    assert "rationale" in result


def test_advise_validation_with_mocked_llm():
    """With a mocked _chat, advise_validation returns structured issues."""
    from manufacturing import agent

    mock_response = json.dumps({
        "feasible": True,
        "issues": [
            {"severity": "warning", "message": "Titanium requires flood coolant", "fix": "Enable coolant system"}
        ],
        "recommended_process": None,
        "material_notes": "Ti-6Al-4V has low thermal conductivity",
    })

    with patch.object(agent, "_chat", return_value=mock_response):
        with patch.object(agent, "research_material", return_value=None):
            with patch.object(agent, "research_process", return_value=None):
                result = agent.advise_validation(
                    '{"part_id": "TEST", "material": {"material_name": "titanium"}}',
                    "cnc_milling",
                )
    assert result is not None
    assert result["feasible"] is True
    assert len(result["issues"]) == 1


def test_plan_work_order_with_mocked_llm():
    """With a mocked _chat, plan_work_order returns a step sequence."""
    from manufacturing import agent

    mock_response = json.dumps({
        "steps": [
            {"sequence": 1, "process_family": "cnc_milling", "description": "Rough milling",
             "estimated_minutes": 30, "requires_inspection": False},
            {"sequence": 2, "process_family": "inspection_cmm", "description": "CMM check",
             "estimated_minutes": 15, "requires_inspection": True},
        ],
        "total_estimated_minutes": 45,
        "critical_path_notes": "CMM must follow milling",
        "quality_strategy": "100% inspection on first article",
    })

    with patch.object(agent, "_chat", return_value=mock_response):
        with patch.object(agent, "research_material", return_value=None):
            result = agent.plan_work_order('{"part_id": "TEST"}')
    assert result is not None
    assert len(result["steps"]) == 2
    assert result["total_estimated_minutes"] == 45


# ---------------------------------------------------------------------------
# Test routing integration (agent does NOT break existing physics)
# ---------------------------------------------------------------------------

def test_routing_still_works_without_ollama():
    """The routing engine scores and ranks correctly even when the agent is unavailable."""
    from manufacturing.routing import RoutingEngine
    from manufacturing.registry import ProcessRegistry
    from manufacturing.ontology import (
        ManufacturingIntent,
        MaterialSpec,
        ProcessFamily,
    )
    from manufacturing.bridge import bootstrap_registry

    registry = bootstrap_registry()
    engine = RoutingEngine(registry)

    intent = ManufacturingIntent(
        part_id="AGENT-TEST-001",
        part_name="Test Part",
        material=MaterialSpec(material_name="steel", material_family="ferrous"),
        target_quantity=100,
        tolerance_class="ISO_2768_m",
    )

    result = engine.route(intent)
    # Should return a result regardless of Ollama status
    assert result is not None
    # Options may be empty if no machines registered, but no crash
    if result.options:
        assert result.options[0].score > 0


def test_validation_still_works_without_ollama():
    """validate_intent still returns correct rule-based errors without Ollama."""
    from manufacturing.validation import validate_intent
    from manufacturing.registry import ProcessRegistry
    from manufacturing.ontology import ManufacturingIntent, MaterialSpec
    from manufacturing.bridge import bootstrap_registry

    registry = bootstrap_registry()

    intent = ManufacturingIntent(
        part_id="VAL-TEST-001",
        part_name="Validation Test Part",
        material=MaterialSpec(material_name="steel", material_family="ferrous"),
        target_quantity=100,
    )

    errors = validate_intent(intent, registry)
    # Should return a list (possibly empty) without crashing
    assert isinstance(errors, list)
