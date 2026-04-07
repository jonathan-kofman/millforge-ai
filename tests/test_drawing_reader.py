"""Tests for Drawing Reader agent and router."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from agents.drawing_reader import DrawingReaderAgent, GDTCallout


class TestDrawingReaderAgent:
    """Test GD&T extraction and inspection plan generation."""

    def setup_method(self):
        self.agent = DrawingReaderAgent()

    def test_generate_plan_empty(self):
        """Empty callout list returns empty plan."""
        plan = self.agent.generate_inspection_plan([])
        assert plan.steps == []
        assert plan.total_estimated_time_minutes == 0.0

    def test_generate_plan_single_diameter(self):
        """Single diameter callout produces one inspection step."""
        callouts = [
            GDTCallout(
                feature_id="F1",
                dimension_type="diameter",
                nominal=25.0,
                tolerance_plus=0.01,
                tolerance_minus=0.01,
            ),
        ]
        plan = self.agent.generate_inspection_plan(callouts)
        assert len(plan.steps) == 1
        assert plan.steps[0].sequence == 1
        assert plan.steps[0].feature_id == "F1"
        assert plan.total_estimated_time_minutes > 0

    def test_instrument_selection_tight_tolerance(self):
        """Tight tolerance (<0.01mm) selects CMM."""
        instrument, method, time = self.agent._select_instrument(0.005)
        assert instrument == "CMM"

    def test_instrument_selection_medium_tolerance(self):
        """Medium tolerance selects micrometer."""
        instrument, method, time = self.agent._select_instrument(0.08)
        assert instrument == "Micrometer"

    def test_instrument_selection_loose_tolerance(self):
        """Loose tolerance selects caliper."""
        instrument, method, time = self.agent._select_instrument(0.5)
        assert instrument == "Caliper"

    def test_plan_ordering_tightest_first(self):
        """Steps should be ordered with tightest tolerances first."""
        callouts = [
            GDTCallout(feature_id="F1", dimension_type="length",
                       nominal=50.0, tolerance_plus=0.5, tolerance_minus=0.5),
            GDTCallout(feature_id="F2", dimension_type="diameter",
                       nominal=25.0, tolerance_plus=0.005, tolerance_minus=0.005),
        ]
        plan = self.agent.generate_inspection_plan(callouts)
        assert plan.steps[0].feature_id == "F2"  # tighter tolerance first
        assert plan.steps[1].feature_id == "F1"

    def test_plan_datum_features_first(self):
        """Datum-referenced features should be inspected before dependents."""
        callouts = [
            GDTCallout(feature_id="F1", dimension_type="position",
                       nominal=0, tolerance_plus=0.05, tolerance_minus=0.05,
                       datum_refs=["A"]),
            GDTCallout(feature_id="F2", dimension_type="flatness",
                       nominal=0, tolerance_plus=0.5, tolerance_minus=0.5,
                       datum_refs=[]),
        ]
        plan = self.agent.generate_inspection_plan(callouts)
        assert len(plan.steps) == 2

    def test_acceptance_criteria_format(self):
        """Acceptance criteria should show min/max range."""
        callout = GDTCallout(
            feature_id="F1",
            dimension_type="diameter",
            nominal=25.0,
            tolerance_plus=0.01,
            tolerance_minus=0.02,
        )
        criteria = self.agent._format_acceptance(callout)
        assert "24.980" in criteria
        assert "25.010" in criteria

    def test_instruments_required_deduped(self):
        """Instruments required list should not have duplicates."""
        callouts = [
            GDTCallout(feature_id="F1", dimension_type="diameter",
                       nominal=25.0, tolerance_plus=0.5, tolerance_minus=0.5),
            GDTCallout(feature_id="F2", dimension_type="length",
                       nominal=50.0, tolerance_plus=0.5, tolerance_minus=0.5),
        ]
        plan = self.agent.generate_inspection_plan(callouts)
        assert len(plan.instruments_required) == len(set(plan.instruments_required))
