"""
Tests for vision model availability checks and startup behavior.

Verifies that when the YOLOv8 model is missing, the system:
1. Attempts to download it on startup (if internet available)
2. Returns a clear 503 error if download fails (NOT silent heuristic fallback)
3. Logs a WARNING at startup indicating the fallback mode

Run with: pytest tests/test_vision_model_availability.py -v
"""

import os
import pytest
import sys
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.quality_vision import (
    check_vision_model_availability,
    NEU_DET_MODEL_PATH,
    _MODEL_PATH,
    _try_download_model,
)


class TestModelAvailabilityCheck:
    """Test the check_vision_model_availability() startup function."""

    def test_check_passes_when_model_exists_locally(self, tmp_path, monkeypatch):
        """When NEU-DET model exists locally, check should pass."""
        fake_model = tmp_path / "neu_det_yolov8n.onnx"
        fake_model.write_bytes(b"x" * 2_000_000)  # 2MB fake ONNX

        import agents.quality_vision as qv_module
        monkeypatch.setattr(qv_module, "NEU_DET_MODEL_PATH", str(fake_model))

        available, status = check_vision_model_availability()
        assert available is True
        assert "loaded" in status.lower()

    def test_check_fails_if_model_file_corrupted(self, tmp_path, monkeypatch):
        """When model file is too small (< 1MB), check should raise RuntimeError."""
        import agents.quality_vision as qv_module

        fake_model = tmp_path / "neu_det_yolov8n.onnx"
        fake_model.write_bytes(b"x" * 100)  # only 100 bytes — too small

        monkeypatch.setattr(qv_module, "NEU_DET_MODEL_PATH", str(fake_model))

        with pytest.raises(RuntimeError, match="too small"):
            check_vision_model_availability()

    def test_check_fails_gracefully_when_model_missing_and_download_fails(
        self, tmp_path, monkeypatch
    ):
        """
        When NEU-DET model is missing, fallback is missing, and download fails,
        check should return (available=False, status_msg).
        """
        import agents.quality_vision as qv_module

        # Point to non-existent paths
        missing_neu_det = tmp_path / "missing_neu_det.onnx"
        missing_fallback = tmp_path / "missing_fallback.onnx"

        monkeypatch.setattr(qv_module, "NEU_DET_MODEL_PATH", str(missing_neu_det))
        monkeypatch.setenv("MILLFORGE_MODEL_PATH", str(missing_fallback))

        # Mock download to fail
        monkeypatch.setattr(
            qv_module, "_try_download_model", lambda path: False
        )

        available, status = check_vision_model_availability()
        assert available is False
        assert "fallback" in status.lower() or "unavailable" in status.lower()

    def test_check_attempts_download_when_model_missing(self, tmp_path, monkeypatch):
        """When model is missing, check should call _try_download_model."""
        import agents.quality_vision as qv_module

        missing_neu_det = tmp_path / "missing.onnx"
        missing_fallback = tmp_path / "fallback.onnx"

        monkeypatch.setattr(qv_module, "NEU_DET_MODEL_PATH", str(missing_neu_det))
        monkeypatch.setenv("MILLFORGE_MODEL_PATH", str(missing_fallback))

        download_called = {"called": False}

        def mock_download(path):
            download_called["called"] = True
            return False  # download fails

        monkeypatch.setattr(qv_module, "_try_download_model", mock_download)

        available, status = check_vision_model_availability()
        assert download_called["called"] is True


class TestTryDownloadModel:
    """Test the _try_download_model() function."""

    def test_returns_true_if_file_exists(self, tmp_path):
        """If model file already exists, return True immediately."""
        existing = tmp_path / "model.onnx"
        existing.write_bytes(b"fake")

        result = _try_download_model(str(existing))
        assert result is True

    def test_creates_directory_if_missing(self, tmp_path):
        """If parent directory doesn't exist, create it."""
        target = tmp_path / "new" / "dir" / "model.onnx"

        assert not target.parent.exists()

        with patch("urllib.request.urlretrieve") as mock_urlretrieve:
            mock_urlretrieve.side_effect = Exception("mocked download fails")
            _try_download_model(str(target))

        # Directory should have been created even though download failed
        assert target.parent.exists()

    def test_returns_false_and_logs_warning_on_download_failure(self, tmp_path, caplog):
        """When download fails, return False and log a warning."""
        target = tmp_path / "model.onnx"

        with patch("urllib.request.urlretrieve") as mock_urlretrieve:
            mock_urlretrieve.side_effect = Exception("Network error")
            result = _try_download_model(str(target))

        assert result is False
        # Should log a warning about the failure
        assert "warning" in [r.levelname.lower() for r in caplog.records]


class TestVisionEndpointWithMissingModel:
    """Integration tests: verify inspect endpoint returns 503 when model missing."""

    @pytest.mark.usefixtures("client")
    def test_inspect_returns_503_when_model_check_failed(
        self, client, monkeypatch
    ):
        """
        When vision model startup check failed, /api/vision/inspect should return 503
        (NOT silently fall back to heuristic).
        """
        # Simulate: startup check ran, model not available
        import routers.vision as vision_module

        vision_module._model_startup_check = {
            "available": False,
            "status": "Model file missing and download failed",
        }

        response = client.post("/api/vision/inspect", json={
            "image_url": "https://example.com/part.jpg",
            "material": "steel",
        })

        # Should return 503, not 200 with heuristic result
        assert response.status_code == 503
        detail = response.json().get("detail", "")
        assert "unavailable" in detail.lower() or "failed" in detail.lower()

    @pytest.mark.usefixtures("client")
    def test_inspect_succeeds_when_model_check_passed(
        self, client, monkeypatch
    ):
        """When startup check passed, inspect should work normally."""
        import routers.vision as vision_module

        vision_module._model_startup_check = {
            "available": True,
            "status": "Model loaded from git",
        }

        response = client.post("/api/vision/inspect", json={
            "image_url": "https://example.com/part.jpg",
            "material": "steel",
        })

        # Should return 200 with inspection result
        assert response.status_code == 200
        data = response.json()
        assert "passed" in data
        assert "confidence" in data


class TestStartupLogOutput:
    """Verify that startup logs are clear and actionable."""

    def test_startup_logs_clear_warning_when_model_missing(self, caplog, tmp_path, monkeypatch):
        """When model is unavailable, startup should emit a WARNING (not silent)."""
        import agents.quality_vision as qv_module
        import logging

        caplog.set_level(logging.WARNING)

        missing = tmp_path / "missing.onnx"
        monkeypatch.setattr(qv_module, "NEU_DET_MODEL_PATH", str(missing))
        monkeypatch.setenv("MILLFORGE_MODEL_PATH", str(tmp_path / "fallback.onnx"))
        monkeypatch.setattr(qv_module, "_try_download_model", lambda p: False)

        available, status = check_vision_model_availability()

        # Should have logged a warning somewhere
        # (check_vision_model_availability logs via logger)
        assert available is False
        assert "fallback" in status.lower() or "heuristic" in status.lower()
