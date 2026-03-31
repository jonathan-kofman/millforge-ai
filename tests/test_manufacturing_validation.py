"""
Tests for manufacturing/validation.py

Covers:
  - validate_intent with valid input
  - validate_intent catches missing required fields / unsupported process
  - validate_intent catches material-process incompatibility
  - validate_work_order with inconsistent step order
  - validate_process_step with missing machine capability
  - validate_process_step energy profile plausibility check
  - validate_process_step batch constraint check
"""

import sys
import os
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from manufacturing.ontology import (
    EnergyProfile,
    ManufacturingIntent,
    MaterialSpec,
    ProcessConstraints,
    ProcessFamily,
    ProcessPlan,
    ProcessStepDefinition,
    QualityRequirement,
)
from manufacturing.registry import (
    MachineCapability,
    ProcessCapability,
    ProcessRegistry,
)
from manufacturing.work_order import WorkOrder, WorkOrderStatus, WorkOrderStep
from manufacturing.validation import (
    validate_intent,
    validate_process_step,
    validate_work_order,
)
from manufacturing.adapters.cnc_milling import CNCMillingAdapter
from manufacturing.adapters.welding import ArcWeldingAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_registry():
    ProcessRegistry.reset()
    yield
    ProcessRegistry.reset()


@pytest.fixture
def registry() -> ProcessRegistry:
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_adapter(ArcWeldingAdapter())
    # Register a capable machine
    r.register_machine(
        MachineCapability(
            machine_id="VMC-001",
            machine_name="Haas VF-2",
            machine_type="VMC",
            capabilities=[
                ProcessCapability(
                    process_family=ProcessFamily.CNC_MILLING,
                    supported_materials=["steel", "aluminum", "titanium", "copper"],
                )
            ],
        )
    )
    return r


@pytest.fixture
def steel_material():
    return MaterialSpec(
        material_name="Steel",
        material_family="ferrous",
        form="bar_stock",
    )


@pytest.fixture
def basic_intent(steel_material) -> ManufacturingIntent:
    return ManufacturingIntent(
        part_id="P-001",
        part_name="Test Bracket",
        target_quantity=10,
        material=steel_material,
        required_processes=[ProcessFamily.CNC_MILLING],
        due_date=datetime.utcnow() + timedelta(days=7),
    )


@pytest.fixture
def basic_step(steel_material) -> ProcessStepDefinition:
    return ProcessStepDefinition(
        step_id="step-001",
        process_family=ProcessFamily.CNC_MILLING,
        description="Face milling",
        material_input=steel_material,
        energy=EnergyProfile(base_power_kw=75.0, peak_power_kw=110.0, idle_power_kw=8.0),
        estimated_cycle_time_minutes=30.0,
        setup_time_minutes=15.0,
    )


@pytest.fixture
def basic_plan(basic_intent, basic_step) -> ProcessPlan:
    return ProcessPlan(
        plan_id="plan-001",
        intent=basic_intent,
        steps=[basic_step],
        total_estimated_time_minutes=45.0,
    )


@pytest.fixture
def basic_work_order(basic_intent, basic_plan) -> WorkOrder:
    return WorkOrder(
        work_order_id="WO-001",
        intent=basic_intent,
        process_plan=basic_plan,
        steps=[
            WorkOrderStep(
                step_number=1,
                process_family=ProcessFamily.CNC_MILLING,
                machine_id="VMC-001",
                estimated_time_minutes=45.0,
            )
        ],
    )


# ---------------------------------------------------------------------------
# validate_intent — valid inputs
# ---------------------------------------------------------------------------


def test_validate_intent_valid_returns_empty(basic_intent, registry):
    errors = validate_intent(basic_intent, registry)
    assert errors == []


def test_validate_intent_valid_no_required_processes(steel_material, registry):
    intent = ManufacturingIntent(
        part_id="P-FREE",
        part_name="Free Part",
        target_quantity=5,
        material=steel_material,
    )
    errors = validate_intent(intent, registry)
    assert errors == []


# ---------------------------------------------------------------------------
# validate_intent — unsupported process
# ---------------------------------------------------------------------------


def test_validate_intent_unregistered_process_error(steel_material, registry):
    """Required process has no adapter → validation error."""
    intent = ManufacturingIntent(
        part_id="P-EDM",
        part_name="EDM Part",
        target_quantity=5,
        material=steel_material,
        required_processes=[ProcessFamily.EDM_WIRE],  # no adapter registered
    )
    errors = validate_intent(intent, registry)
    assert any("EDM_WIRE" in e or "no registered adapter" in e for e in errors)


# ---------------------------------------------------------------------------
# validate_intent — material-process incompatibility
# ---------------------------------------------------------------------------


def test_validate_intent_polymer_with_cnc_error(registry):
    """CNC milling is in _NO_POLYMER; polymer material should generate an error."""
    polymer_intent = ManufacturingIntent(
        part_id="P-POLY",
        part_name="Plastic Part",
        target_quantity=5,
        material=MaterialSpec(
            material_name="Nylon",
            material_family="polymer",
            form="bar_stock",
        ),
        required_processes=[ProcessFamily.CNC_MILLING],
    )
    errors = validate_intent(polymer_intent, registry)
    assert any("polymer" in e.lower() or "incompatible" in e.lower() for e in errors)


def test_validate_intent_injection_molding_needs_polymer(steel_material, registry):
    """INJECTION_MOLDING requires polymer/composite material."""
    intent = ManufacturingIntent(
        part_id="P-INJ",
        part_name="Metal Mold",
        target_quantity=100,
        material=steel_material,
        required_processes=[ProcessFamily.INJECTION_MOLDING],
    )
    errors = validate_intent(intent, registry)
    assert any("injection_molding" in e.lower() or "polymer" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_intent — past due date
# ---------------------------------------------------------------------------


def test_validate_intent_past_due_date_error(steel_material, registry):
    intent = ManufacturingIntent(
        part_id="P-LATE",
        part_name="Late Part",
        target_quantity=5,
        material=steel_material,
        due_date=datetime.utcnow() - timedelta(days=1),  # yesterday
    )
    errors = validate_intent(intent, registry)
    assert any("past" in e.lower() or "due_date" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_intent — negative cost target
# ---------------------------------------------------------------------------


def test_validate_intent_negative_cost_target(steel_material, registry):
    intent = ManufacturingIntent(
        part_id="P-COST",
        part_name="Cheap Part",
        target_quantity=5,
        material=steel_material,
        cost_target_usd=-100.0,
    )
    errors = validate_intent(intent, registry)
    assert any("cost_target_usd" in e.lower() or "positive" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_intent — minimum batch enforcement
# ---------------------------------------------------------------------------


def test_validate_intent_injection_molding_min_batch(registry):
    """INJECTION_MOLDING requires ≥ 50 units."""
    intent = ManufacturingIntent(
        part_id="P-SMALL",
        part_name="Small Batch Injection",
        target_quantity=5,  # below 50
        material=MaterialSpec(
            material_name="Nylon",
            material_family="polymer",
            form="pellet",
        ),
        required_processes=[ProcessFamily.INJECTION_MOLDING],
    )
    errors = validate_intent(intent, registry)
    assert any("50" in e or "minimum" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_intent — no capable machine
# ---------------------------------------------------------------------------


def test_validate_intent_no_capable_machine_for_material(registry):
    """Requesting a material not in any machine's capability list raises error."""
    intent = ManufacturingIntent(
        part_id="P-RARE",
        part_name="Exotic Part",
        target_quantity=5,
        material=MaterialSpec(
            material_name="Inconel",
            material_family="non_ferrous",
            form="bar_stock",
        ),
        required_processes=[ProcessFamily.CNC_MILLING],
    )
    errors = validate_intent(intent, registry)
    # Machine VMC-001 only lists steel/aluminum/titanium/copper — not inconel
    assert any("no available machine" in e.lower() or "inconel" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_work_order
# ---------------------------------------------------------------------------


def test_validate_work_order_valid(basic_work_order, registry):
    errors = validate_work_order(basic_work_order, registry)
    assert errors == []


def test_validate_work_order_no_steps(basic_intent, basic_plan, registry):
    wo = WorkOrder(
        work_order_id="WO-EMPTY",
        intent=basic_intent,
        process_plan=basic_plan,
        steps=[],
    )
    errors = validate_work_order(wo, registry)
    assert any("no steps" in e.lower() for e in errors)


def test_validate_work_order_inconsistent_step_order(basic_intent, basic_plan, registry):
    """Step numbers must be contiguous from 1."""
    wo = WorkOrder(
        work_order_id="WO-GAP",
        intent=basic_intent,
        process_plan=basic_plan,
        steps=[
            WorkOrderStep(
                step_number=1,
                process_family=ProcessFamily.CNC_MILLING,
                estimated_time_minutes=30.0,
            ),
            WorkOrderStep(
                step_number=3,  # gap — should be 2
                process_family=ProcessFamily.WELDING_ARC,
                estimated_time_minutes=20.0,
            ),
        ],
    )
    errors = validate_work_order(wo, registry)
    assert any("step" in e.lower() and "contiguous" in e.lower() for e in errors)


def test_validate_work_order_unregistered_adapter(basic_intent, basic_plan, registry):
    """Step with process that has no adapter → error."""
    wo = WorkOrder(
        work_order_id="WO-NOADP",
        intent=basic_intent,
        process_plan=basic_plan,
        steps=[
            WorkOrderStep(
                step_number=1,
                process_family=ProcessFamily.EDM_WIRE,  # no adapter
                estimated_time_minutes=30.0,
            )
        ],
    )
    errors = validate_work_order(wo, registry)
    assert any("EDM_WIRE" in e or "no registered adapter" in e for e in errors)


def test_validate_work_order_machine_not_capable(basic_intent, basic_plan, registry):
    """Assigned machine doesn't support the process → error."""
    wo = WorkOrder(
        work_order_id="WO-MISMATCH",
        intent=basic_intent,
        process_plan=basic_plan,
        steps=[
            WorkOrderStep(
                step_number=1,
                process_family=ProcessFamily.CNC_MILLING,
                machine_id="VMC-001",
                estimated_time_minutes=30.0,
            ),
            WorkOrderStep(
                step_number=2,
                process_family=ProcessFamily.WELDING_ARC,
                machine_id="VMC-001",  # VMC-001 doesn't do welding
                estimated_time_minutes=20.0,
            ),
        ],
    )
    errors = validate_work_order(wo, registry)
    assert any("does not support" in e.lower() or "WELDING_ARC" in e for e in errors)


def test_validate_work_order_draft_with_active_steps_error(basic_intent, basic_plan, registry):
    """DRAFT work order can't have IN_PROGRESS steps."""
    wo = WorkOrder(
        work_order_id="WO-DRAFT-ACTIVE",
        intent=basic_intent,
        process_plan=basic_plan,
        status=WorkOrderStatus.DRAFT,
        steps=[
            WorkOrderStep(
                step_number=1,
                process_family=ProcessFamily.CNC_MILLING,
                status=WorkOrderStatus.IN_PROGRESS,  # inconsistent with DRAFT
                estimated_time_minutes=30.0,
            )
        ],
    )
    errors = validate_work_order(wo, registry)
    assert any("draft" in e.lower() or "active" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# validate_process_step
# ---------------------------------------------------------------------------


def test_validate_process_step_valid(basic_step, registry):
    errors = validate_process_step(basic_step, registry)
    assert errors == []


def test_validate_process_step_missing_adapter(steel_material, registry):
    step = ProcessStepDefinition(
        step_id="step-edm",
        process_family=ProcessFamily.EDM_SINKER,
        description="EDM sinker op",
        material_input=steel_material,
        energy=EnergyProfile(base_power_kw=10.0, peak_power_kw=20.0),
        estimated_cycle_time_minutes=60.0,
        setup_time_minutes=20.0,
    )
    errors = validate_process_step(step, registry)
    assert any("no adapter" in e.lower() for e in errors)


def test_validate_process_step_invalid_energy_profile(steel_material, registry):
    """peak_power_kw < base_power_kw should be flagged."""
    step = ProcessStepDefinition(
        step_id="step-bad-energy",
        process_family=ProcessFamily.CNC_MILLING,
        description="Bad energy step",
        material_input=steel_material,
        energy=EnergyProfile(
            base_power_kw=100.0,
            peak_power_kw=50.0,  # peak < base → invalid
        ),
        estimated_cycle_time_minutes=30.0,
        setup_time_minutes=15.0,
    )
    errors = validate_process_step(step, registry)
    assert any("peak_power_kw" in e or "peak" in e.lower() for e in errors)


def test_validate_process_step_empty_step_id(steel_material, registry):
    step = ProcessStepDefinition(
        step_id="   ",  # whitespace only
        process_family=ProcessFamily.CNC_MILLING,
        description="Step with blank id",
        material_input=steel_material,
        energy=EnergyProfile(base_power_kw=75.0, peak_power_kw=110.0),
        estimated_cycle_time_minutes=30.0,
        setup_time_minutes=15.0,
    )
    errors = validate_process_step(step, registry)
    assert any("step_id" in e.lower() for e in errors)
