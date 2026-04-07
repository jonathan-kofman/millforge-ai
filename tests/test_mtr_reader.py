"""Tests for MTR Reader agent and router."""

import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from agents.mtr_reader import MTRReaderAgent, MTRExtraction


# ---------------------------------------------------------------------------
# Agent unit tests
# ---------------------------------------------------------------------------

class TestMTRReaderAgent:
    """Test MTR extraction and verification logic."""

    def setup_method(self):
        self.agent = MTRReaderAgent()

    def test_verify_passing_316l(self):
        """316L MTR that meets all spec requirements."""
        extraction = MTRExtraction(
            material_spec="ASTM A276 316L",
            chemistry={"C": 0.025, "Mn": 1.50, "Cr": 17.0, "Ni": 12.0, "Mo": 2.5},
            mechanicals={"tensile_ksi": 80, "yield_ksi": 35, "elongation_pct": 45},
        )
        result = self.agent.verify_against_spec(extraction, spec_key="A276_316L")
        assert result.status == "pass"
        assert result.overall_pass is True
        assert len(result.details) > 0

    def test_verify_failing_carbon_too_high(self):
        """316L with carbon above spec limit."""
        extraction = MTRExtraction(
            chemistry={"C": 0.050, "Cr": 17.0, "Ni": 12.0, "Mo": 2.5},
            mechanicals={"tensile_ksi": 80},
        )
        result = self.agent.verify_against_spec(extraction, spec_key="A276_316L")
        assert result.status == "fail"
        assert result.overall_pass is False
        # Find the carbon check
        carbon_check = next((c for c in result.details if "C" in c.property_name), None)
        assert carbon_check is not None
        assert carbon_check.passed is False

    def test_verify_failing_tensile_too_low(self):
        """304 with tensile strength below spec minimum."""
        extraction = MTRExtraction(
            chemistry={"C": 0.05, "Cr": 18.5, "Ni": 9.0},
            mechanicals={"tensile_ksi": 60},  # min is 75
        )
        result = self.agent.verify_against_spec(extraction, spec_key="A276_304")
        assert result.status == "fail"
        tensile_check = next((c for c in result.details if "tensile" in c.property_name), None)
        assert tensile_check is not None
        assert tensile_check.passed is False

    def test_verify_unknown_spec(self):
        """Unknown spec returns review status."""
        extraction = MTRExtraction(chemistry={"C": 0.03})
        result = self.agent.verify_against_spec(extraction, spec_key="FAKE_SPEC_999")
        assert result.status == "review"
        assert result.overall_pass is False

    def test_auto_detect_spec_a276_316l(self):
        """Auto-detect spec from extraction text."""
        extraction = MTRExtraction(material_spec="ASTM A276 316L")
        key = self.agent._auto_detect_spec(extraction)
        assert key == "A276_316L"

    def test_auto_detect_spec_none(self):
        """No spec string returns None."""
        extraction = MTRExtraction()
        key = self.agent._auto_detect_spec(extraction)
        assert key is None

    def test_supported_specs_not_empty(self):
        """Should have at least the ASTM and AMS specs we shipped."""
        specs = self.agent.supported_specs()
        assert len(specs) >= 10
        keys = [s["key"] for s in specs]
        assert "A276_316L" in keys
        assert "A276_304" in keys

    def test_verify_6061_aluminum(self):
        """6061-T6 aluminum verification."""
        extraction = MTRExtraction(
            chemistry={"Si": 0.6, "Mg": 1.0, "Cu": 0.28},
            mechanicals={"tensile_ksi": 45, "yield_ksi": 40, "elongation_pct": 12},
        )
        result = self.agent.verify_against_spec(extraction, spec_key="B209_6061-T6")
        assert result.status == "pass"
        assert result.overall_pass is True

    def test_auto_match_job_by_material(self):
        """Match MTR to job by material keyword."""
        extraction = MTRExtraction(material_spec="ASTM A276 316L Stainless")
        jobs = [
            {"id": 1, "material": "aluminum", "title": "Bracket"},
            {"id": 2, "material": "316l", "title": "Fitting"},
            {"id": 3, "material": "steel", "title": "Shaft"},
        ]
        matched = self.agent.auto_match_job(extraction, jobs)
        assert matched == 2

    def test_auto_match_job_no_match(self):
        """No matching job returns None."""
        extraction = MTRExtraction(material_spec="Inconel 718")
        jobs = [
            {"id": 1, "material": "aluminum", "title": "Bracket"},
        ]
        matched = self.agent.auto_match_job(extraction, jobs)
        assert matched is None

    def test_file_hash_deterministic(self):
        """Same bytes should produce same hash."""
        data = b"test PDF content"
        h1 = self.agent.file_hash(data)
        h2 = self.agent.file_hash(data)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest


# ---------------------------------------------------------------------------
# Router integration tests
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    """TestClient with in-memory SQLite."""
    from database import Base, engine
    from main import app
    from fastapi.testclient import TestClient

    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


class TestMTRRouter:
    """Integration tests for the MTR router endpoints."""

    def test_list_mtrs_empty(self, client):
        """List MTRs should return empty list initially."""
        resp = client.get("/api/quality/mtr")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_specs(self, client):
        """Should return supported spec list."""
        resp = client.get("/api/quality/mtr/specs")
        assert resp.status_code == 200
        specs = resp.json()
        assert len(specs) > 0

    def test_upload_rejects_non_pdf(self, client):
        """Should reject non-PDF file uploads."""
        resp = client.post(
            "/api/quality/mtr/upload",
            files={"file": ("test.txt", b"not a pdf", "text/plain")},
        )
        assert resp.status_code == 400

    def test_get_nonexistent_mtr(self, client):
        """Should return 404 for missing MTR."""
        resp = client.get("/api/quality/mtr/99999")
        assert resp.status_code == 404
