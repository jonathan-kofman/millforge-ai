"""
Tests for manufacturing/ontology.py

Covers:
  - ProcessFamily enum coverage
  - ProcessCategory.for_process() mapping
  - MaterialSpec construction and validation
  - ManufacturingIntent construction, validation, and serialization
  - ProcessPlan construction, auto-time calculation
  - ProcessStepDefinition properties
  - EnergyProfile.average_power_kw
  - ProcessConstraints validation
"""

import sys
import os
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from manufacturing.ontology import (
    EnergyProfile,
    FixtureSpec,
    ManufacturingIntent,
    MaterialSpec,
    ProcessCategory,
    ProcessConstraints,
    ProcessFamily,
    ProcessPlan,
    ProcessStepDefinition,
    QualityRequirement,
    ToolingSpec,
)


# ---------------------------------------------------------------------------
# Helpers / shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def steel_material():
    return MaterialSpec(
        material_name="Steel",
        alloy_designation="A36",
        material_family="ferrous",
        form="bar_stock",
        thickness_mm=10.0,
        width_mm=50.0,
        length_mm=200.0,
        density_kg_m3=7850.0,
        yield_strength_mpa=250.0,
    )


@pytest.fixture
def aluminum_material():
    return MaterialSpec(
        material_name="Aluminum 6061-T6",
        alloy_designation="Al6061-T6",
        material_family="non_ferrous",
        form="plate",
        thickness_mm=5.0,
        width_mm=100.0,
        length_mm=300.0,
        density_kg_m3=2700.0,
    )


@pytest.fixture
def basic_energy():
    return EnergyProfile(base_power_kw=75.0, peak_power_kw=110.0, idle_power_kw=8.0)


@pytest.fixture
def basic_intent(steel_material):
    return ManufacturingIntent(
        part_id="PART-001",
        part_name="Test Bracket",
        description="Simple steel bracket",
        target_quantity=10,
        material=steel_material,
        required_processes=[ProcessFamily.CNC_MILLING],
        priority=3,
    )


@pytest.fixture
def basic_step(steel_material, basic_energy):
    return ProcessStepDefinition(
        step_id="step-001",
        process_family=ProcessFamily.CNC_MILLING,
        description="Face milling operation",
        material_input=steel_material,
        energy=basic_energy,
        estimated_cycle_time_minutes=30.0,
        setup_time_minutes=15.0,
    )


# ---------------------------------------------------------------------------
# ProcessFamily enum tests
# ---------------------------------------------------------------------------


def test_process_family_has_cnc_families():
    assert ProcessFamily.CNC_MILLING == "CNC_MILLING"
    assert ProcessFamily.CNC_TURNING == "CNC_TURNING"
    assert ProcessFamily.CNC_DRILLING == "CNC_DRILLING"


def test_process_family_has_welding_families():
    assert ProcessFamily.WELDING_ARC == "WELDING_ARC"
    assert ProcessFamily.WELDING_LASER == "WELDING_LASER"
    assert ProcessFamily.WELDING_EBW == "WELDING_EBW"
    assert ProcessFamily.WELDING_FRICTION_STIR == "WELDING_FRICTION_STIR"


def test_process_family_has_forming_families():
    assert ProcessFamily.BENDING_PRESS_BRAKE == "BENDING_PRESS_BRAKE"
    assert ProcessFamily.BENDING_ROLL == "BENDING_ROLL"
    assert ProcessFamily.STAMPING == "STAMPING"


def test_process_family_has_additive_families():
    assert ProcessFamily.ADDITIVE_FDM == "ADDITIVE_FDM"
    assert ProcessFamily.ADDITIVE_SLS == "ADDITIVE_SLS"
    assert ProcessFamily.ADDITIVE_DMLS == "ADDITIVE_DMLS"
    assert ProcessFamily.ADDITIVE_WIRE_ARC == "ADDITIVE_WIRE_ARC"


def test_process_family_coverage_count():
    """Ensure the enum has at least 25 distinct process families."""
    all_families = list(ProcessFamily)
    assert len(all_families) >= 25


# ---------------------------------------------------------------------------
# ProcessCategory tests
# ---------------------------------------------------------------------------


def test_category_for_cnc_is_subtractive():
    assert ProcessCategory.for_process(ProcessFamily.CNC_MILLING) == ProcessCategory.SUBTRACTIVE
    assert ProcessCategory.for_process(ProcessFamily.CNC_TURNING) == ProcessCategory.SUBTRACTIVE
    assert ProcessCategory.for_process(ProcessFamily.EDM_WIRE) == ProcessCategory.SUBTRACTIVE


def test_category_for_welding_is_joining():
    assert ProcessCategory.for_process(ProcessFamily.WELDING_ARC) == ProcessCategory.JOINING
    assert ProcessCategory.for_process(ProcessFamily.WELDING_LASER) == ProcessCategory.JOINING
    assert ProcessCategory.for_process(ProcessFamily.WELDING_EBW) == ProcessCategory.JOINING


def test_category_for_forming_is_forming():
    assert ProcessCategory.for_process(ProcessFamily.BENDING_PRESS_BRAKE) == ProcessCategory.FORMING
    assert ProcessCategory.for_process(ProcessFamily.STAMPING) == ProcessCategory.FORMING


def test_category_for_additive_is_additive():
    assert ProcessCategory.for_process(ProcessFamily.ADDITIVE_FDM) == ProcessCategory.ADDITIVE
    assert ProcessCategory.for_process(ProcessFamily.ADDITIVE_DMLS) == ProcessCategory.ADDITIVE


def test_category_for_inspection():
    assert ProcessCategory.for_process(ProcessFamily.INSPECTION_CMM) == ProcessCategory.INSPECTION
    assert ProcessCategory.for_process(ProcessFamily.INSPECTION_XRAY) == ProcessCategory.INSPECTION


def test_category_for_assembly():
    assert ProcessCategory.for_process(ProcessFamily.ASSEMBLY) == ProcessCategory.ASSEMBLY


def test_category_for_heat_treatment():
    assert ProcessCategory.for_process(ProcessFamily.HEAT_TREATMENT) == ProcessCategory.THERMAL


# ---------------------------------------------------------------------------
# MaterialSpec tests
# ---------------------------------------------------------------------------


def test_material_spec_minimal_construction():
    m = MaterialSpec(material_name="Steel")
    assert m.material_name == "Steel"
    assert m.material_family == "ferrous"
    assert m.form == "bar_stock"


def test_material_spec_normalized_name(steel_material):
    assert steel_material.normalized_name == "steel"


def test_material_spec_normalized_name_trims_whitespace():
    m = MaterialSpec(material_name="  Aluminum  ")
    assert m.normalized_name == "aluminum"


def test_material_spec_optional_fields_default_none():
    m = MaterialSpec(material_name="Copper")
    assert m.thickness_mm is None
    assert m.density_kg_m3 is None
    assert m.yield_strength_mpa is None
    assert m.hardness is None


def test_material_spec_custom_properties():
    m = MaterialSpec(
        material_name="Composite",
        material_family="composite",
        custom_properties={"fiber_orientation": "0/90", "prepreg": True},
    )
    assert m.custom_properties["fiber_orientation"] == "0/90"


# ---------------------------------------------------------------------------
# EnergyProfile tests
# ---------------------------------------------------------------------------


def test_energy_profile_average_power_constant():
    ep = EnergyProfile(base_power_kw=100.0, peak_power_kw=150.0, idle_power_kw=10.0, duty_cycle=1.0)
    assert ep.average_power_kw == 100.0


def test_energy_profile_average_power_with_duty_cycle():
    ep = EnergyProfile(base_power_kw=100.0, peak_power_kw=150.0, idle_power_kw=10.0, duty_cycle=0.5)
    expected = 100.0 * 0.5 + 10.0 * 0.5
    assert abs(ep.average_power_kw - expected) < 1e-6


def test_energy_profile_duty_cycle_bounds():
    with pytest.raises(ValidationError):
        EnergyProfile(base_power_kw=50.0, peak_power_kw=80.0, duty_cycle=1.5)

    with pytest.raises(ValidationError):
        EnergyProfile(base_power_kw=50.0, peak_power_kw=80.0, duty_cycle=-0.1)


# ---------------------------------------------------------------------------
# ProcessConstraints tests
# ---------------------------------------------------------------------------


def test_process_constraints_defaults():
    pc = ProcessConstraints()
    assert pc.min_batch_size == 1
    assert pc.max_batch_size is None
    assert pc.vibration_sensitive is False


def test_process_constraints_valid_batch_range():
    pc = ProcessConstraints(min_batch_size=10, max_batch_size=100)
    assert pc.min_batch_size == 10
    assert pc.max_batch_size == 100


def test_process_constraints_invalid_batch_range():
    with pytest.raises(ValidationError):
        ProcessConstraints(min_batch_size=50, max_batch_size=10)


# ---------------------------------------------------------------------------
# ManufacturingIntent tests
# ---------------------------------------------------------------------------


def test_intent_minimal_construction(steel_material):
    intent = ManufacturingIntent(
        part_id="P-1",
        part_name="Widget",
        target_quantity=5,
        material=steel_material,
    )
    assert intent.part_id == "P-1"
    assert intent.priority == 5  # default
    assert intent.required_processes is None


def test_intent_priority_bounds(steel_material):
    with pytest.raises(ValidationError):
        ManufacturingIntent(
            part_id="P-1", part_name="X", target_quantity=1,
            material=steel_material, priority=0,
        )
    with pytest.raises(ValidationError):
        ManufacturingIntent(
            part_id="P-1", part_name="X", target_quantity=1,
            material=steel_material, priority=11,
        )


def test_intent_quantity_must_be_positive(steel_material):
    with pytest.raises(ValidationError):
        ManufacturingIntent(
            part_id="P-1", part_name="X", target_quantity=0,
            material=steel_material,
        )


def test_intent_required_forbidden_overlap_raises(steel_material):
    with pytest.raises(ValidationError):
        ManufacturingIntent(
            part_id="P-1",
            part_name="X",
            target_quantity=1,
            material=steel_material,
            required_processes=[ProcessFamily.CNC_MILLING],
            forbidden_processes=[ProcessFamily.CNC_MILLING],
        )


def test_intent_required_forbidden_no_overlap_ok(steel_material):
    intent = ManufacturingIntent(
        part_id="P-1",
        part_name="X",
        target_quantity=1,
        material=steel_material,
        required_processes=[ProcessFamily.CNC_MILLING],
        forbidden_processes=[ProcessFamily.WELDING_ARC],
    )
    assert ProcessFamily.CNC_MILLING in intent.required_processes


def test_intent_serializes_to_dict(basic_intent):
    d = basic_intent.model_dump()
    assert d["part_id"] == "PART-001"
    assert d["target_quantity"] == 10
    assert "material" in d


def test_intent_with_quality_requirements(steel_material):
    qr = QualityRequirement(
        inspection_method="CMM",
        tolerance_class="ISO_2768_f",
        surface_finish_ra=0.8,
    )
    intent = ManufacturingIntent(
        part_id="P-2",
        part_name="Precision Part",
        target_quantity=1,
        material=steel_material,
        quality_requirements=[qr],
    )
    assert len(intent.quality_requirements) == 1
    assert intent.quality_requirements[0].surface_finish_ra == 0.8


# ---------------------------------------------------------------------------
# ProcessStepDefinition tests
# ---------------------------------------------------------------------------


def test_step_total_time_minutes(basic_step):
    assert basic_step.total_time_minutes == 45.0  # 30 + 15


def test_step_category_derived_correctly(basic_step):
    assert basic_step.category == ProcessCategory.SUBTRACTIVE


def test_step_requires_nonnegative_times(steel_material, basic_energy):
    with pytest.raises(ValidationError):
        ProcessStepDefinition(
            step_id="s1",
            process_family=ProcessFamily.CNC_MILLING,
            description="bad step",
            material_input=steel_material,
            energy=basic_energy,
            estimated_cycle_time_minutes=-1.0,
            setup_time_minutes=0.0,
        )


# ---------------------------------------------------------------------------
# ProcessPlan tests
# ---------------------------------------------------------------------------


def test_process_plan_auto_time_calculation(basic_intent, basic_step, steel_material, basic_energy):
    step2 = ProcessStepDefinition(
        step_id="step-002",
        process_family=ProcessFamily.WELDING_ARC,
        description="Weld assembly",
        material_input=steel_material,
        energy=basic_energy,
        estimated_cycle_time_minutes=20.0,
        setup_time_minutes=10.0,
    )
    plan = ProcessPlan(
        plan_id="plan-001",
        intent=basic_intent,
        steps=[basic_step, step2],
        total_estimated_time_minutes=0.0,  # should auto-compute
    )
    # 45 + 30 = 75 minutes
    assert plan.total_estimated_time_minutes == 75.0


def test_process_plan_step_count(basic_intent, basic_step):
    plan = ProcessPlan(
        plan_id="plan-002",
        intent=basic_intent,
        steps=[basic_step],
        total_estimated_time_minutes=45.0,
    )
    assert plan.step_count == 1


def test_process_plan_get_step(basic_intent, basic_step):
    plan = ProcessPlan(
        plan_id="plan-003",
        intent=basic_intent,
        steps=[basic_step],
        total_estimated_time_minutes=45.0,
    )
    found = plan.get_step("step-001")
    assert found is not None
    assert found.step_id == "step-001"


def test_process_plan_get_step_missing(basic_intent, basic_step):
    plan = ProcessPlan(
        plan_id="plan-004",
        intent=basic_intent,
        steps=[basic_step],
        total_estimated_time_minutes=45.0,
    )
    assert plan.get_step("nonexistent") is None


def test_process_plan_with_multiple_steps(basic_intent, steel_material, basic_energy):
    steps = []
    for i in range(3):
        steps.append(
            ProcessStepDefinition(
                step_id=f"step-{i:03d}",
                process_family=ProcessFamily.CNC_MILLING,
                description=f"Step {i}",
                material_input=steel_material,
                energy=basic_energy,
                estimated_cycle_time_minutes=10.0,
                setup_time_minutes=5.0,
            )
        )
    plan = ProcessPlan(
        plan_id="plan-multi",
        intent=basic_intent,
        steps=steps,
        total_estimated_time_minutes=0.0,
    )
    assert plan.step_count == 3
    assert plan.total_estimated_time_minutes == 45.0  # 3 × (10+5)
