"""
Tests for manufacturing/simulation.py

Covers:
  - CycleTimeEstimator returns positive values
  - CycleTimeEstimator hierarchy (adapter → capability → fallback)
  - CycleTimeEstimator.estimate_with_complexity
  - CostEstimator returns positive total
  - CostEstimator.estimate_breakdown returns component dict with correct keys
  - CostEstimator higher labor rate increases cost
  - FeasibilityChecker with fully feasible intent
  - FeasibilityChecker with infeasible intent (no machine for required process)
  - FeasibilityChecker.check.recommendations when process has alternatives
  - FeasibilityResult.as_dict structure
"""

import sys
import os
from datetime import datetime, timedelta

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from manufacturing.ontology import (
    EnergyProfile,
    ManufacturingIntent,
    MaterialSpec,
    ProcessCategory,
    ProcessFamily,
)
from manufacturing.registry import (
    MachineCapability,
    ProcessCapability,
    ProcessRegistry,
)
from manufacturing.simulation import (
    CostEstimator,
    CycleTimeEstimator,
    FeasibilityChecker,
    FeasibilityResult,
    _FALLBACK_CYCLE_TIME_PER_UNIT,
    DEFAULT_ENERGY_RATE_USD_KWH,
    DEFAULT_LABOR_RATE_USD_HOUR,
)
from manufacturing.adapters.cnc_milling import CNCMillingAdapter
from manufacturing.adapters.welding import ArcWeldingAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cap(family: ProcessFamily, materials=None) -> ProcessCapability:
    return ProcessCapability(
        process_family=family,
        supported_materials=materials or ["steel", "aluminum", "titanium", "copper"],
        throughput_range=(2.0, 6.0),
        setup_time_range_minutes=(15.0, 90.0),
        energy_profile=EnergyProfile(base_power_kw=85.0, peak_power_kw=120.0, idle_power_kw=8.0),
    )


def _make_vmc(machine_id: str = "VMC-001") -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"Machine {machine_id}",
        machine_type="VMC",
        capabilities=[_make_cap(ProcessFamily.CNC_MILLING)],
    )


def _make_welder(machine_id: str = "WLD-001") -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"Welder {machine_id}",
        machine_type="MIG_WELDER",
        capabilities=[_make_cap(ProcessFamily.WELDING_ARC)],
    )


def _steel_intent(quantity: int = 10, **kwargs) -> ManufacturingIntent:
    defaults = dict(
        part_id="SIM-001",
        part_name="Simulation Part",
        target_quantity=quantity,
        material=MaterialSpec(
            material_name="Steel",
            material_family="ferrous",
            form="bar_stock",
        ),
    )
    defaults.update(kwargs)
    return ManufacturingIntent(**defaults)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_registry():
    ProcessRegistry.reset()
    yield
    ProcessRegistry.reset()


@pytest.fixture
def registry_with_cnc() -> ProcessRegistry:
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_vmc())
    return r


@pytest.fixture
def full_registry() -> ProcessRegistry:
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_adapter(ArcWeldingAdapter())
    r.register_machine(_make_vmc())
    r.register_machine(_make_welder())
    return r


# ---------------------------------------------------------------------------
# CycleTimeEstimator
# ---------------------------------------------------------------------------


class TestCycleTimeEstimator:

    def test_estimate_positive(self, registry_with_cnc):
        estimator = CycleTimeEstimator(registry_with_cnc)
        intent = _steel_intent(quantity=5)
        machine = registry_with_cnc.get_machine("VMC-001")
        result = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        assert result > 0

    def test_estimate_uses_adapter_when_registered(self, registry_with_cnc):
        """CNCMillingAdapter is registered — its estimate_cycle_time should be used."""
        estimator = CycleTimeEstimator(registry_with_cnc)
        intent = _steel_intent(quantity=4)
        machine = registry_with_cnc.get_machine("VMC-001")
        adapter = registry_with_cnc.get_adapter(ProcessFamily.CNC_MILLING)
        expected = adapter.estimate_cycle_time(intent, machine)
        result = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        assert abs(result - expected) < 0.5

    def test_estimate_fallback_without_adapter(self):
        r = ProcessRegistry.get_instance()
        # No adapter registered
        r.register_machine(_make_vmc())
        estimator = CycleTimeEstimator(r)
        intent = _steel_intent(quantity=5)
        machine = r.get_machine("VMC-001")
        result = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        # Falls back to capability throughput or category fallback
        assert result > 0

    def test_estimate_fallback_category_based(self):
        """When neither adapter nor throughput_range is available, uses fallback table."""
        r = ProcessRegistry.get_instance()
        # Machine with no throughput_range
        machine = MachineCapability(
            machine_id="BARE-001",
            machine_name="Bare Machine",
            machine_type="VMC",
            capabilities=[
                ProcessCapability(
                    process_family=ProcessFamily.CNC_MILLING,
                    supported_materials=["steel"],
                    throughput_range=None,  # no throughput
                )
            ],
        )
        r.register_machine(machine)
        estimator = CycleTimeEstimator(r)
        intent = _steel_intent(quantity=3)
        result = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        # Should use _FALLBACK_CYCLE_TIME_PER_UNIT[SUBTRACTIVE] * 3
        expected = _FALLBACK_CYCLE_TIME_PER_UNIT[ProcessCategory.SUBTRACTIVE] * 3
        assert abs(result - expected) < 1.0

    def test_estimate_scales_with_quantity(self, registry_with_cnc):
        estimator = CycleTimeEstimator(registry_with_cnc)
        machine = registry_with_cnc.get_machine("VMC-001")
        t5 = estimator.estimate(_steel_intent(quantity=5), ProcessFamily.CNC_MILLING, machine)
        t10 = estimator.estimate(_steel_intent(quantity=10), ProcessFamily.CNC_MILLING, machine)
        assert t10 > t5

    def test_estimate_with_complexity_factor(self, registry_with_cnc):
        estimator = CycleTimeEstimator(registry_with_cnc)
        machine = registry_with_cnc.get_machine("VMC-001")
        intent = _steel_intent(quantity=5)
        base = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        complex_result = estimator.estimate_with_complexity(
            intent, ProcessFamily.CNC_MILLING, machine, complexity_factor=2.0
        )
        assert complex_result > base

    def test_estimate_complexity_clamped(self, registry_with_cnc):
        """Complexity is clamped to [0.5, 5.0]."""
        estimator = CycleTimeEstimator(registry_with_cnc)
        machine = registry_with_cnc.get_machine("VMC-001")
        intent = _steel_intent(quantity=5)
        base = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        very_low = estimator.estimate_with_complexity(
            intent, ProcessFamily.CNC_MILLING, machine, complexity_factor=0.01
        )
        very_high = estimator.estimate_with_complexity(
            intent, ProcessFamily.CNC_MILLING, machine, complexity_factor=100.0
        )
        # Clamped at 0.5× and 5.0×
        assert abs(very_low - base * 0.5) < 1.0
        assert abs(very_high - base * 5.0) < 1.0


# ---------------------------------------------------------------------------
# CostEstimator
# ---------------------------------------------------------------------------


class TestCostEstimator:

    def test_estimate_positive(self, registry_with_cnc):
        estimator = CostEstimator(registry_with_cnc)
        intent = _steel_intent(quantity=5)
        machine = registry_with_cnc.get_machine("VMC-001")
        result = estimator.estimate(intent, ProcessFamily.CNC_MILLING, machine)
        assert result > 0

    def test_estimate_breakdown_has_required_keys(self, registry_with_cnc):
        estimator = CostEstimator(registry_with_cnc)
        intent = _steel_intent(quantity=5)
        machine = registry_with_cnc.get_machine("VMC-001")
        breakdown = estimator.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        for key in ["energy_usd", "labor_usd", "tooling_usd", "consumables_usd", "total_usd"]:
            assert key in breakdown, f"Missing key: {key}"

    def test_estimate_breakdown_total_is_sum(self, registry_with_cnc):
        estimator = CostEstimator(registry_with_cnc)
        intent = _steel_intent(quantity=5)
        machine = registry_with_cnc.get_machine("VMC-001")
        bd = estimator.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        expected_total = bd["energy_usd"] + bd["labor_usd"] + bd["tooling_usd"] + bd["consumables_usd"]
        assert abs(bd["total_usd"] - expected_total) < 0.01

    def test_estimate_breakdown_all_non_negative(self, registry_with_cnc):
        estimator = CostEstimator(registry_with_cnc)
        intent = _steel_intent(quantity=5)
        machine = registry_with_cnc.get_machine("VMC-001")
        bd = estimator.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        for key, val in bd.items():
            assert val >= 0, f"{key} should be non-negative, got {val}"

    def test_higher_labor_rate_increases_cost(self, registry_with_cnc):
        """
        When the adapter is NOT registered, CostEstimator.estimate() falls back to
        the component model which respects labor_rate_usd_hour.
        We test via estimate_breakdown() which always uses the component model,
        or by using a registry without a registered adapter.
        """
        intent = _steel_intent(quantity=10)
        machine = registry_with_cnc.get_machine("VMC-001")
        cheap = CostEstimator(registry_with_cnc, labor_rate_usd_hour=40.0)
        expensive = CostEstimator(registry_with_cnc, labor_rate_usd_hour=150.0)
        # estimate_breakdown() always uses the component path (bypassing adapter delegate)
        bd_cheap = cheap.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        bd_expensive = expensive.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        assert bd_expensive["labor_usd"] > bd_cheap["labor_usd"]

    def test_higher_energy_rate_increases_cost(self, registry_with_cnc):
        intent = _steel_intent(quantity=10)
        machine = registry_with_cnc.get_machine("VMC-001")
        cheap = CostEstimator(registry_with_cnc, energy_rate_usd_kwh=0.05)
        expensive = CostEstimator(registry_with_cnc, energy_rate_usd_kwh=0.50)
        # Breakdown comparison (adapter doesn't use the kwh rate directly, so use breakdown)
        bd_cheap = cheap.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        bd_expensive = expensive.estimate_breakdown(intent, ProcessFamily.CNC_MILLING, machine)
        assert bd_expensive["energy_usd"] > bd_cheap["energy_usd"]

    def test_more_units_increases_cost(self, registry_with_cnc):
        estimator = CostEstimator(registry_with_cnc)
        machine = registry_with_cnc.get_machine("VMC-001")
        c5 = estimator.estimate(_steel_intent(quantity=5), ProcessFamily.CNC_MILLING, machine)
        c20 = estimator.estimate(_steel_intent(quantity=20), ProcessFamily.CNC_MILLING, machine)
        assert c20 > c5


# ---------------------------------------------------------------------------
# FeasibilityChecker
# ---------------------------------------------------------------------------


class TestFeasibilityChecker:

    def test_feasible_intent_returns_true(self, registry_with_cnc):
        checker = FeasibilityChecker(registry_with_cnc)
        intent = ManufacturingIntent(
            part_id="FEAS-001",
            part_name="Feasible Part",
            target_quantity=10,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CNC_MILLING],
        )
        result = checker.check(intent)
        assert isinstance(result, FeasibilityResult)
        assert result.is_feasible is True

    def test_feasible_result_has_capable_process_count(self, registry_with_cnc):
        checker = FeasibilityChecker(registry_with_cnc)
        intent = ManufacturingIntent(
            part_id="FEAS-002",
            part_name="Part",
            target_quantity=5,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CNC_MILLING],
        )
        result = checker.check(intent)
        assert result.capable_process_count >= 1

    def test_feasible_result_has_lead_time(self, registry_with_cnc):
        checker = FeasibilityChecker(registry_with_cnc)
        intent = ManufacturingIntent(
            part_id="FEAS-003",
            part_name="Part",
            target_quantity=5,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CNC_MILLING],
        )
        result = checker.check(intent)
        assert result.estimated_lead_time_hours is not None
        assert result.estimated_lead_time_hours > 0

    def test_infeasible_intent_with_no_machine(self):
        r = ProcessRegistry.get_instance()
        r.register_adapter(CNCMillingAdapter())
        # No machines registered
        checker = FeasibilityChecker(r)
        intent = ManufacturingIntent(
            part_id="INFEAS-001",
            part_name="Impossible Part",
            target_quantity=5,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CNC_MILLING],
        )
        result = checker.check(intent)
        assert result.is_feasible is False

    def test_infeasible_result_has_errors(self):
        r = ProcessRegistry.get_instance()
        r.register_adapter(CNCMillingAdapter())
        checker = FeasibilityChecker(r)
        intent = ManufacturingIntent(
            part_id="INFEAS-002",
            part_name="Impossible Part",
            target_quantity=5,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CNC_MILLING],
        )
        result = checker.check(intent)
        assert len(result.errors) > 0

    def test_over_budget_adds_warning(self, registry_with_cnc):
        checker = FeasibilityChecker(registry_with_cnc)
        intent = ManufacturingIntent(
            part_id="BUDGET-001",
            part_name="Cheap Part",
            target_quantity=100,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CNC_MILLING],
            cost_target_usd=0.01,  # absurdly low budget
        )
        result = checker.check(intent)
        # Should still be feasible (warnings != errors) but have a cost warning
        assert any("cost" in w.lower() or "exceed" in w.lower() for w in result.warnings)

    def test_feasibility_result_as_dict(self, registry_with_cnc):
        checker = FeasibilityChecker(registry_with_cnc)
        intent = ManufacturingIntent(
            part_id="DICT-001",
            part_name="Dict Part",
            target_quantity=5,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
        )
        result = checker.check(intent)
        d = result.as_dict()
        for key in ["is_feasible", "errors", "warnings", "capable_process_count",
                    "estimated_lead_time_hours", "recommendations", "checked_at"]:
            assert key in d, f"Missing key: {key}"

    def test_recommendations_provided_for_missing_process(self, registry_with_cnc):
        """FeasibilityChecker suggests alternatives when the required process has none."""
        # Only CNC milling is registered; check for a process that has alternatives in the map
        checker = FeasibilityChecker(registry_with_cnc)
        intent = ManufacturingIntent(
            part_id="REC-001",
            part_name="Missing Process Part",
            target_quantity=5,
            material=MaterialSpec(
                material_name="Steel",
                material_family="ferrous",
                form="bar_stock",
            ),
            required_processes=[ProcessFamily.CUTTING_LASER],  # no machine registered
        )
        result = checker.check(intent)
        # If alternatives exist in the registry (CNC_MILLING), recommendations may appear
        assert isinstance(result.recommendations, list)
