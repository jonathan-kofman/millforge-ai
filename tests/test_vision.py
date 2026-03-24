"""
Tests for QualityVisionAgent — ONNX pipeline and heuristic fallback.

Run with: pytest tests/test_vision.py -v
"""

import sys
import os
import numpy as np
import pytest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.quality_vision import (
    QualityVisionAgent,
    InspectionResult,
    DEFECT_TYPES,
    MATERIAL_PASS_THRESHOLDS,
    DEFAULT_PASS_THRESHOLD,
    YOLO_CLASS_MAP,
    INPUT_SIZE,
    CONF_THRESHOLD,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def agent():
    """Heuristic-mode agent (no model file)."""
    return QualityVisionAgent()


@pytest.fixture
def onnx_agent(tmp_path):
    """Agent with a mocked ONNX session."""
    model_file = tmp_path / "model.onnx"
    model_file.write_bytes(b"fake-onnx-bytes")

    agent = QualityVisionAgent.__new__(QualityVisionAgent)
    agent.model_path = str(model_file)
    agent.MAX_RETRIES = 3

    # Build a fake session that returns a clean "no defects" output
    mock_session = MagicMock()
    mock_session.get_inputs.return_value = [MagicMock(name="images")]
    # YOLOv8 output shape (1, 4+6, 8400) — all zeros → no detections
    mock_session.run.return_value = [np.zeros((1, 10, 8400), dtype=np.float32)]

    agent._session = mock_session
    agent._input_name = "images"
    return agent


# ---------------------------------------------------------------------------
# Heuristic mode
# ---------------------------------------------------------------------------

class TestHeuristicMode:

    def test_returns_inspection_result(self, agent):
        result = agent.inspect("http://example.com/part.jpg")
        assert isinstance(result, InspectionResult)

    def test_confidence_in_range(self, agent):
        result = agent.inspect("http://example.com/part.jpg", material="steel")
        assert 0.0 <= result.confidence <= 1.0

    def test_defects_are_valid_categories(self, agent):
        for url in ["http://a.com/1.jpg", "http://b.com/2.jpg", "http://c.com/3.jpg"]:
            result = agent.inspect(url, material="aluminum")
            for d in result.defects_detected:
                assert d in DEFECT_TYPES

    def test_passed_and_defects_consistent(self, agent):
        result = agent.inspect("http://example.com/part.jpg", material="steel")
        if result.passed:
            assert result.defects_detected == []

    def test_deterministic_same_url(self, agent):
        url = "http://example.com/deterministic-test.jpg"
        r1 = agent.inspect(url)
        r2 = agent.inspect(url)
        assert r1.confidence == r2.confidence
        assert r1.defects_detected == r2.defects_detected

    def test_different_urls_can_differ(self, agent):
        results = [agent.inspect(f"http://example.com/part_{i}.jpg") for i in range(5)]
        confidences = [r.confidence for r in results]
        # Not all identical (probabilistic, but deterministic per URL)
        assert len(set(confidences)) > 1

    def test_per_material_threshold_titanium(self, agent):
        # Titanium has a higher threshold (0.90) — more likely to fail
        threshold = MATERIAL_PASS_THRESHOLDS["titanium"]
        url = "http://example.com/titanium_part.jpg"
        result = agent.inspect(url, material="titanium")
        if result.passed:
            assert result.confidence >= threshold

    def test_per_material_threshold_copper(self, agent):
        threshold = MATERIAL_PASS_THRESHOLDS["copper"]
        url = "http://example.com/copper_part.jpg"
        result = agent.inspect(url, material="copper")
        if not result.passed:
            assert result.confidence < threshold

    def test_no_validation_failures_on_valid_result(self, agent):
        result = agent.inspect("http://example.com/good.jpg", material="steel")
        assert result.validation_failures == []


# ---------------------------------------------------------------------------
# ONNX inference path
# ---------------------------------------------------------------------------

class TestONNXMode:

    def test_no_detections_returns_pass(self, onnx_agent, monkeypatch):
        blank = np.zeros((1, 3, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
        monkeypatch.setattr(onnx_agent, "_preprocess", lambda *a, **kw: blank)
        result = onnx_agent._onnx_inspect(
            image_url="http://example.com/clean.jpg",
            material="steel",
            threshold=0.82,
        )
        assert result.passed
        assert result.defects_detected == []
        assert result.confidence == 0.95

    def test_high_confidence_detections_map_to_defects(self, onnx_agent, monkeypatch):
        # Build output with one strong detection: class 0 (surface_crack)
        blank = np.zeros((1, 3, INPUT_SIZE, INPUT_SIZE), dtype=np.float32)
        monkeypatch.setattr(onnx_agent, "_preprocess", lambda *a, **kw: blank)

        raw = np.zeros((1, 10, 8400), dtype=np.float32)
        raw[0, 4, 0] = 0.95   # class 0 score at anchor 0
        onnx_agent._session.run.return_value = [raw]

        result = onnx_agent._onnx_inspect(
            image_url="http://example.com/cracked.jpg",
            material="steel",
            threshold=0.82,
        )
        assert "surface_crack" in result.defects_detected

    def test_preprocess_output_shape(self, onnx_agent):
        # Create a tiny in-memory RGB image
        from PIL import Image
        import io
        img = Image.new("RGB", (100, 80), color=(128, 64, 32))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)

        with patch("builtins.open", side_effect=lambda p, *a, **kw: buf):
            with patch("PIL.Image.open", return_value=img):
                blob = onnx_agent._preprocess("/fake/path/image.png")

        assert blob.shape == (1, 3, INPUT_SIZE, INPUT_SIZE)
        assert blob.dtype == np.float32
        assert blob.min() >= 0.0
        assert blob.max() <= 1.0

    def test_postprocess_filters_low_confidence(self, onnx_agent):
        raw = np.zeros((1, 10, 8400), dtype=np.float32)
        raw[0, 4, 0] = CONF_THRESHOLD - 0.01  # below threshold
        detections = onnx_agent._postprocess(raw)
        assert detections == []

    def test_postprocess_returns_valid_categories(self, onnx_agent):
        raw = np.zeros((1, 10, 8400), dtype=np.float32)
        raw[0, 4, 0] = 0.80   # class 0 above threshold
        raw[0, 5, 1] = 0.70   # class 1 above threshold
        detections = onnx_agent._postprocess(raw)
        for cat, _ in detections:
            assert cat in DEFECT_TYPES


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

class TestValidationLoop:

    def test_validation_fails_on_bad_confidence(self, agent):
        """_validate catches out-of-range confidence."""
        bad = InspectionResult(
            image_url="http://example.com/x.jpg",
            passed=False,
            confidence=1.5,          # invalid
            defects_detected=["porosity"],
            defect_severities={"porosity": "major"},
            recommendation="Reject.",
        )
        errors = agent._validate(bad, {"image_url": "http://example.com/x.jpg"})
        assert any("confidence" in e for e in errors)

    def test_validation_fails_on_unknown_defect(self, agent):
        """_validate catches defect categories not in the taxonomy."""
        bad = InspectionResult(
            image_url="http://example.com/x.jpg",
            passed=False,
            confidence=0.70,
            defects_detected=["rust"],   # not in DEFECT_TYPES
            defect_severities={"rust": "minor"},
            recommendation="Reject.",
        )
        errors = agent._validate(bad, {"image_url": "http://example.com/x.jpg"})
        assert any("rust" in e for e in errors)

    def test_validation_fails_passed_with_defects(self, agent):
        """_validate catches passed=True with non-empty defect list."""
        bad = InspectionResult(
            image_url="http://example.com/x.jpg",
            passed=True,
            confidence=0.92,
            defects_detected=["inclusions"],  # contradicts passed=True
            defect_severities={"inclusions": "major"},
            recommendation="Approve.",
        )
        errors = agent._validate(bad, {"image_url": "http://example.com/x.jpg"})
        assert any("passed=True" in e for e in errors)

    def test_retry_collects_failures_and_returns_best(self, agent, monkeypatch):
        """When _do_inspect always returns invalid output, failures are recorded."""
        bad_result = InspectionResult(
            image_url="http://example.com/bad.jpg",
            passed=True,
            confidence=2.0,         # invalid — triggers validation failure every time
            defects_detected=[],
            defect_severities={},
            recommendation="Approve.",
        )
        monkeypatch.setattr(agent, "_do_inspect", lambda *a, **kw: bad_result)

        result = agent.inspect("http://example.com/bad.jpg", material="steel")
        assert len(result.validation_failures) > 0
        # Should have failures from all 3 attempts
        assert sum(1 for f in result.validation_failures if "confidence" in f) == agent.MAX_RETRIES

    def test_retry_stops_on_first_valid_result(self, agent, monkeypatch):
        """Stops retrying as soon as a valid result is produced."""
        call_count = {"n": 0}
        good_result = InspectionResult(
            image_url="http://example.com/ok.jpg",
            passed=True,
            confidence=0.92,
            defects_detected=[],
            defect_severities={},
            recommendation="Approve.",
        )
        bad_result = InspectionResult(
            image_url="http://example.com/ok.jpg",
            passed=True,
            confidence=1.5,   # invalid on first call only
            defects_detected=[],
            defect_severities={},
            recommendation="Approve.",
        )

        def side_effect(*a, **kw):
            call_count["n"] += 1
            return bad_result if call_count["n"] == 1 else good_result

        monkeypatch.setattr(agent, "_do_inspect", side_effect)

        result = agent.inspect("http://example.com/ok.jpg")
        assert call_count["n"] == 2                  # stopped after 2nd attempt
        assert result.validation_failures == []       # valid result returned


# ---------------------------------------------------------------------------
# Severity scoring
# ---------------------------------------------------------------------------

class TestDefectSeverities:

    def test_critical_defects_have_critical_severity(self, agent):
        """surface_crack and delamination should be critical."""
        # Use a URL that hashes to a failing result — if not, test via _make_result directly
        result = agent._make_result(
            image_url="http://example.com/crack.jpg",
            confidence=0.75,
            defects=["surface_crack", "delamination"],
            threshold=0.82,
        )
        assert result.defect_severities["surface_crack"] == "critical"
        assert result.defect_severities["delamination"] == "critical"

    def test_major_defects_have_major_severity(self, agent):
        result = agent._make_result(
            image_url="http://example.com/porous.jpg",
            confidence=0.75,
            defects=["porosity", "inclusions", "dimensional_deviation"],
            threshold=0.82,
        )
        assert result.defect_severities["porosity"] == "major"
        assert result.defect_severities["inclusions"] == "major"
        assert result.defect_severities["dimensional_deviation"] == "major"

    def test_minor_defects_have_minor_severity(self, agent):
        result = agent._make_result(
            image_url="http://example.com/rough.jpg",
            confidence=0.75,
            defects=["surface_roughness"],
            threshold=0.82,
        )
        assert result.defect_severities["surface_roughness"] == "minor"

    def test_no_defects_means_empty_severities(self, agent):
        result = agent._make_result(
            image_url="http://example.com/clean.jpg",
            confidence=0.95,
            defects=[],
            threshold=0.82,
        )
        assert result.defect_severities == {}

    def test_severity_keys_match_defects_detected(self, agent):
        """defect_severities keys must equal defects_detected."""
        result = agent._make_result(
            image_url="http://example.com/multi.jpg",
            confidence=0.75,
            defects=["surface_crack", "porosity"],
            threshold=0.82,
        )
        assert set(result.defect_severities.keys()) == set(result.defects_detected)

    def test_validation_catches_severity_mismatch(self, agent):
        """_validate should flag a severity dict referencing a non-detected defect."""
        bad = InspectionResult(
            image_url="http://example.com/x.jpg",
            passed=False,
            confidence=0.75,
            defects_detected=["porosity"],
            defect_severities={"porosity": "major", "surface_crack": "critical"},
            recommendation="Reject.",
        )
        errors = agent._validate(bad, {})
        assert any("surface_crack" in e for e in errors)

    def test_validation_catches_invalid_severity_value(self, agent):
        """_validate should flag a severity value not in {critical, major, minor}."""
        bad = InspectionResult(
            image_url="http://example.com/x.jpg",
            passed=False,
            confidence=0.75,
            defects_detected=["porosity"],
            defect_severities={"porosity": "extreme"},
            recommendation="Reject.",
        )
        errors = agent._validate(bad, {})
        assert any("invalid severity" in e for e in errors)
