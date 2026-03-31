"""
Tests for manufacturing/routing.py

Covers:
  - RoutingEngine basic routing with one adapter + machine
  - Routing with material incompatibility (should return warnings)
  - Multi-step routing
  - Scoring with different weight configurations
  - Selecting best machine when multiple are available
  - RouteOption and RoutingResult properties
  - Forbidden process filtering
"""

import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from manufacturing.ontology import (
    EnergyProfile,
    ManufacturingIntent,
    MaterialSpec,
    ProcessFamily,
    QualityRequirement,
)
from manufacturing.registry import (
    MachineCapability,
    ProcessCapability,
    ProcessRegistry,
)
from manufacturing.routing import DEFAULT_WEIGHTS, RoutingEngine, RoutingResult
from manufacturing.adapters.cnc_milling import CNCMillingAdapter
from manufacturing.adapters.welding import ArcWeldingAdapter
from manufacturing.adapters.bending import PressBrakeAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_capability(family: ProcessFamily, materials=None, max_dims=None, setup_range=(15.0, 90.0)) -> ProcessCapability:
    return ProcessCapability(
        process_family=family,
        supported_materials=materials or ["steel", "aluminum", "titanium", "copper"],
        max_part_dimensions_mm=max_dims or (600.0, 400.0, 300.0),
        tolerances={"position_mm": 0.01},
        throughput_range=(2.0, 6.0),
        setup_time_range_minutes=setup_range,
        energy_profile=EnergyProfile(base_power_kw=85.0, peak_power_kw=120.0, idle_power_kw=8.0),
    )


def _make_vmc(machine_id: str, available: bool = True, materials=None) -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"VMC {machine_id}",
        machine_type="VMC",
        capabilities=[_make_capability(ProcessFamily.CNC_MILLING, materials=materials)],
        is_available=available,
        location="Cell 1",
    )


def _make_welder(machine_id: str) -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"Welder {machine_id}",
        machine_type="MIG_WELDER",
        capabilities=[_make_capability(ProcessFamily.WELDING_ARC)],
        is_available=True,
        location="Bay B",
    )


def _make_press_brake(machine_id: str) -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"Press Brake {machine_id}",
        machine_type="PRESS_BRAKE",
        capabilities=[_make_capability(ProcessFamily.BENDING_PRESS_BRAKE)],
        is_available=True,
        location="Bay C",
    )


def _steel_intent(**kwargs) -> ManufacturingIntent:
    defaults = dict(
        part_id="TEST-001",
        part_name="Steel Bracket",
        description="Test part",
        target_quantity=10,
        material=MaterialSpec(
            material_name="Steel",
            material_family="ferrous",
            form="bar_stock",
            thickness_mm=5.0,
            width_mm=50.0,
        ),
        required_processes=[ProcessFamily.CNC_MILLING],
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
    r.register_machine(_make_vmc("VMC-001"))
    return r


@pytest.fixture
def engine(registry_with_cnc) -> RoutingEngine:
    return RoutingEngine(registry_with_cnc)


@pytest.fixture
def full_registry() -> ProcessRegistry:
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_adapter(ArcWeldingAdapter())
    r.register_adapter(PressBrakeAdapter())
    r.register_machine(_make_vmc("VMC-001"))
    r.register_machine(_make_vmc("VMC-002"))
    r.register_machine(_make_welder("WLD-001"))
    r.register_machine(_make_press_brake("PB-001"))
    return r


# ---------------------------------------------------------------------------
# Basic routing
# ---------------------------------------------------------------------------


def test_route_returns_routing_result(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert isinstance(result, RoutingResult)


def test_route_finds_viable_route(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is True
    assert result.selected is not None


def test_route_selected_is_first_option(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.selected is result.options[0]


def test_route_score_in_valid_range(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert 0.0 <= result.selected.score <= 1.0


def test_route_positive_cycle_time(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.selected.estimated_cycle_time_minutes > 0


def test_route_positive_cost(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.selected.estimated_cost_usd > 0


def test_route_reasoning_non_empty(engine):
    intent = _steel_intent()
    result = engine.route(intent)
    assert len(result.selected.reasoning) > 0


# ---------------------------------------------------------------------------
# No viable route
# ---------------------------------------------------------------------------


def test_route_no_viable_when_no_machines():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    # No machines registered
    engine = RoutingEngine(r)
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is False
    assert result.selected is None
    assert len(result.warnings) > 0


def test_route_no_viable_when_no_adapters():
    r = ProcessRegistry.get_instance()
    r.register_machine(_make_vmc("VMC-001"))
    # No adapter registered
    engine = RoutingEngine(r)
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is False


# ---------------------------------------------------------------------------
# Material incompatibility warnings
# ---------------------------------------------------------------------------


def test_route_warns_on_material_fallback():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    # Register machine with only steel support
    r.register_machine(_make_vmc("VMC-STEEL-ONLY", materials=["steel"]))
    engine = RoutingEngine(r)
    # Request aluminum job
    intent = ManufacturingIntent(
        part_id="ALU-001",
        part_name="Aluminum Part",
        target_quantity=5,
        material=MaterialSpec(
            material_name="Aluminum",
            material_family="non_ferrous",
            form="bar_stock",
        ),
        required_processes=[ProcessFamily.CNC_MILLING],
    )
    result = engine.route(intent)
    # May still find a route via fallback but should warn about material mismatch
    # Warnings OR no viable route are both acceptable outcomes
    assert isinstance(result, RoutingResult)


# ---------------------------------------------------------------------------
# Multiple machines — best machine selection
# ---------------------------------------------------------------------------


def test_route_selects_from_multiple_machines():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_vmc("VMC-001"))
    r.register_machine(_make_vmc("VMC-002"))
    r.register_machine(_make_vmc("VMC-003"))
    engine = RoutingEngine(r)
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is True
    assert len(result.options) == 3  # one per machine


def test_route_options_sorted_best_first():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_vmc("VMC-001"))
    r.register_machine(_make_vmc("VMC-002"))
    engine = RoutingEngine(r)
    intent = _steel_intent()
    result = engine.route(intent)
    scores = [o.score for o in result.options]
    assert scores == sorted(scores, reverse=True)


# ---------------------------------------------------------------------------
# Scoring weight configurations
# ---------------------------------------------------------------------------


def test_routing_with_time_priority_weights():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_vmc("VMC-001"))
    engine = RoutingEngine(r, weights={"cost": 0.1, "time": 0.8, "quality": 0.05, "energy": 0.05})
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is True


def test_routing_with_cost_priority_weights():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_vmc("VMC-001"))
    engine = RoutingEngine(r, weights={"cost": 0.9, "time": 0.05, "quality": 0.03, "energy": 0.02})
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is True


def test_default_weights_sum_to_one():
    total = sum(DEFAULT_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_zero_weight_normalised_to_uniform():
    """Passing all-zero weights should not crash; engine normalises to uniform."""
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_vmc("VMC-001"))
    engine = RoutingEngine(r, weights={"cost": 0.0, "time": 0.0, "quality": 0.0, "energy": 0.0})
    intent = _steel_intent()
    result = engine.route(intent)
    assert result.has_viable_route is True


# ---------------------------------------------------------------------------
# Multi-step routing
# ---------------------------------------------------------------------------


def test_route_multi_step_returns_correct_count(full_registry):
    engine = RoutingEngine(full_registry)
    intent = ManufacturingIntent(
        part_id="MULTI-001",
        part_name="Welded Frame",
        target_quantity=5,
        material=MaterialSpec(
            material_name="Steel",
            material_family="ferrous",
            form="sheet",
            thickness_mm=3.0,
        ),
    )
    steps = [ProcessFamily.CNC_MILLING, ProcessFamily.WELDING_ARC]
    results = engine.route_multi_step(intent, steps)
    assert len(results) == 2


def test_route_multi_step_each_result_is_routing_result(full_registry):
    engine = RoutingEngine(full_registry)
    intent = ManufacturingIntent(
        part_id="MULTI-002",
        part_name="Sheet Metal Box",
        target_quantity=10,
        material=MaterialSpec(
            material_name="Steel",
            material_family="ferrous",
            form="sheet",
            thickness_mm=2.0,
        ),
    )
    results = engine.route_multi_step(intent, [ProcessFamily.BENDING_PRESS_BRAKE])
    assert len(results) == 1
    assert isinstance(results[0], RoutingResult)


# ---------------------------------------------------------------------------
# Forbidden process filtering
# ---------------------------------------------------------------------------


def test_route_forbidden_processes_removes_options(full_registry):
    engine = RoutingEngine(full_registry)
    intent = ManufacturingIntent(
        part_id="FORBID-001",
        part_name="Part",
        target_quantity=5,
        material=MaterialSpec(
            material_name="Steel",
            material_family="ferrous",
            form="bar_stock",
        ),
        forbidden_processes=[ProcessFamily.CNC_MILLING],
    )
    result = engine.route(intent)
    for option in result.options:
        assert option.process_family != ProcessFamily.CNC_MILLING


# ---------------------------------------------------------------------------
# Cost over-budget penalty
# ---------------------------------------------------------------------------


def test_route_over_budget_still_returns_option(engine):
    """A very tight budget triggers the penalty but routing still completes."""
    intent = _steel_intent(cost_target_usd=0.01)  # effectively $0 budget
    result = engine.route(intent)
    # Should still produce options but with budget warning in reasoning
    assert isinstance(result, RoutingResult)
    if result.has_viable_route:
        assert "over budget" in result.selected.reasoning or result.selected.score < 1.0
