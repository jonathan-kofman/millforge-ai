"""
Tests for manufacturing adapter implementations:
  - manufacturing/adapters/cnc_milling.py  (CNCMillingAdapter)
  - manufacturing/adapters/welding.py       (ArcWeldingAdapter, LaserWeldingAdapter, EBWeldingAdapter)
  - manufacturing/adapters/bending.py       (PressBrakeAdapter)

Covers:
  - estimate_cycle_time with known inputs
  - estimate_cost returns positive value
  - get_consumables returns expected keys
  - generate_setup_sheet keys and structure
  - WeldingAdapter travel-speed throughput model
  - PressBrakeAdapter tonnage calculation
  - PressBrakeAdapter springback factors
  - validate_intent for various material families
"""

import sys
import os
import math

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from manufacturing.ontology import (
    EnergyProfile,
    ManufacturingIntent,
    MaterialSpec,
    ProcessFamily,
)
from manufacturing.registry import MachineCapability, ProcessCapability
from manufacturing.adapters.cnc_milling import (
    CNCMillingAdapter,
    THROUGHPUT,
    TOOL_LIFE_HOURS,
    COOLANT_LITERS_PER_HOUR,
)
from manufacturing.adapters.welding import (
    ArcWeldingAdapter,
    EBWeldingAdapter,
    LaserWeldingAdapter,
    TRAVEL_SPEED_MM_MIN,
    get_welding_adapter,
)
from manufacturing.adapters.bending import (
    PressBrakeAdapter,
    SPRINGBACK_DEG,
    UTS_MPA,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _dummy_machine(machine_id: str = "VMC-TEST", machine_type: str = "VMC") -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"Machine {machine_id}",
        machine_type=machine_type,
        capabilities=[
            ProcessCapability(
                process_family=ProcessFamily.CNC_MILLING,
                supported_materials=["steel", "aluminum", "titanium", "copper"],
                setup_time_range_minutes=(15.0, 90.0),
                energy_profile=EnergyProfile(base_power_kw=85.0, peak_power_kw=120.0, idle_power_kw=8.0),
            )
        ],
        location="Cell 1",
    )


def _weld_machine() -> MachineCapability:
    return MachineCapability(
        machine_id="WLD-001",
        machine_name="Weld Cell A",
        machine_type="MIG_WELDER",
        capabilities=[
            ProcessCapability(
                process_family=ProcessFamily.WELDING_ARC,
                supported_materials=["steel", "aluminum", "stainless_steel", "titanium"],
            )
        ],
    )


def _press_brake_machine() -> MachineCapability:
    return MachineCapability(
        machine_id="PB-001",
        machine_name="Amada HFT 100",
        machine_type="PRESS_BRAKE",
        capabilities=[
            ProcessCapability(
                process_family=ProcessFamily.BENDING_PRESS_BRAKE,
                supported_materials=["steel", "aluminum", "stainless_steel"],
            )
        ],
    )


def _make_intent(material_name: str, material_family: str = "ferrous", quantity: int = 10,
                 form: str = "bar_stock", thickness_mm: float = None,
                 width_mm: float = None, length_mm: float = None,
                 **metadata) -> ManufacturingIntent:
    mat = MaterialSpec(
        material_name=material_name,
        material_family=material_family,
        form=form,
        thickness_mm=thickness_mm,
        width_mm=width_mm,
        length_mm=length_mm,
    )
    return ManufacturingIntent(
        part_id="TEST-PART",
        part_name="Test Part",
        target_quantity=quantity,
        material=mat,
        custom_metadata=metadata,
    )


# ---------------------------------------------------------------------------
# CNCMillingAdapter — cycle time
# ---------------------------------------------------------------------------


class TestCNCMillingCycleTime:
    """CNCMillingAdapter.estimate_cycle_time uses THROUGHPUT constants."""

    @pytest.fixture
    def adapter(self):
        return CNCMillingAdapter()

    @pytest.fixture
    def machine(self):
        return _dummy_machine()

    def test_steel_cycle_time_matches_formula(self, adapter, machine):
        intent = _make_intent("Steel", quantity=4)
        # throughput["steel"] = 4.0 units/hour, complexity=1.0
        expected_minutes = (4 / 4.0) * 1.0 * 60.0
        result = adapter.estimate_cycle_time(intent, machine)
        assert abs(result - expected_minutes) < 1.0  # within 1 minute

    def test_aluminum_faster_than_steel(self, adapter, machine):
        steel_intent = _make_intent("Steel", quantity=10)
        alu_intent = _make_intent("Aluminum", material_family="non_ferrous", quantity=10)
        steel_time = adapter.estimate_cycle_time(steel_intent, machine)
        alu_time = adapter.estimate_cycle_time(alu_intent, machine)
        # Aluminum throughput (6.0) > steel throughput (4.0), so less time
        assert alu_time < steel_time

    def test_titanium_slower_than_steel(self, adapter, machine):
        steel_intent = _make_intent("Steel", quantity=10)
        ti_intent = _make_intent("Titanium", quantity=10)
        steel_time = adapter.estimate_cycle_time(steel_intent, machine)
        ti_time = adapter.estimate_cycle_time(ti_intent, machine)
        # Titanium throughput (2.5) < steel throughput (4.0)
        assert ti_time > steel_time

    def test_higher_quantity_gives_longer_time(self, adapter, machine):
        t10 = adapter.estimate_cycle_time(_make_intent("Steel", quantity=10), machine)
        t20 = adapter.estimate_cycle_time(_make_intent("Steel", quantity=20), machine)
        assert t20 > t10

    def test_complexity_multiplier(self, adapter, machine):
        base_intent = _make_intent("Steel", quantity=10)
        complex_intent = _make_intent("Steel", quantity=10, complexity=2.0)
        base_time = adapter.estimate_cycle_time(base_intent, machine)
        complex_time = adapter.estimate_cycle_time(complex_intent, machine)
        assert abs(complex_time - base_time * 2.0) < 1.0

    def test_cycle_time_is_positive(self, adapter, machine):
        intent = _make_intent("Steel", quantity=1)
        assert adapter.estimate_cycle_time(intent, machine) > 0


# ---------------------------------------------------------------------------
# CNCMillingAdapter — consumables
# ---------------------------------------------------------------------------


class TestCNCMillingConsumables:

    @pytest.fixture
    def adapter(self):
        return CNCMillingAdapter()

    def test_consumables_include_stock_material(self, adapter):
        intent = _make_intent("Steel", quantity=5)
        cons = adapter.get_consumables(intent)
        assert any("steel" in k or "stock" in k for k in cons)

    def test_consumables_include_coolant_for_steel(self, adapter):
        intent = _make_intent("Steel", quantity=5)
        cons = adapter.get_consumables(intent)
        assert "cutting_coolant_kg" in cons
        assert cons["cutting_coolant_kg"] > 0

    def test_consumables_no_coolant_for_copper(self, adapter):
        """Copper is dry-cut — no coolant consumption."""
        intent = _make_intent("Copper", material_family="non_ferrous", quantity=5)
        cons = adapter.get_consumables(intent)
        # COOLANT_LITERS_PER_HOUR["copper"] == 0 → no cutting_coolant_kg key
        assert cons.get("cutting_coolant_kg", 0) == 0

    def test_consumables_include_carbide_end_mill(self, adapter):
        intent = _make_intent("Steel", quantity=5)
        cons = adapter.get_consumables(intent)
        assert "carbide_end_mill_ea" in cons
        assert 0 < cons["carbide_end_mill_ea"] <= 1.0


# ---------------------------------------------------------------------------
# CNCMillingAdapter — setup sheet
# ---------------------------------------------------------------------------


class TestCNCMillingSetupSheet:

    @pytest.fixture
    def adapter(self):
        return CNCMillingAdapter()

    @pytest.fixture
    def machine(self):
        return _dummy_machine()

    def test_setup_sheet_has_required_keys(self, adapter, machine):
        intent = _make_intent("Steel", quantity=5)
        sheet = adapter.generate_setup_sheet(intent, machine)
        for key in ["process", "machine_id", "material", "quantity",
                    "setup_time_minutes", "estimated_cycle_time_minutes",
                    "tooling", "fixtures", "quality_checks", "process_parameters"]:
            assert key in sheet, f"Missing key: {key}"

    def test_setup_sheet_process_parameters_present(self, adapter, machine):
        intent = _make_intent("Steel", quantity=5)
        sheet = adapter.generate_setup_sheet(intent, machine)
        params = sheet["process_parameters"]
        assert "spindle_speed_rpm" in params
        assert "feed_rate_mm_min" in params
        assert "depth_of_cut_mm" in params
        assert "coolant_type" in params

    def test_setup_sheet_spindle_speed_positive(self, adapter, machine):
        intent = _make_intent("Steel", quantity=5)
        sheet = adapter.generate_setup_sheet(intent, machine)
        assert sheet["process_parameters"]["spindle_speed_rpm"] > 0

    def test_setup_sheet_correct_machine_id(self, adapter, machine):
        intent = _make_intent("Steel", quantity=5)
        sheet = adapter.generate_setup_sheet(intent, machine)
        assert sheet["machine_id"] == machine.machine_id


# ---------------------------------------------------------------------------
# CNCMillingAdapter — validation
# ---------------------------------------------------------------------------


class TestCNCMillingValidation:

    @pytest.fixture
    def adapter(self):
        return CNCMillingAdapter()

    def test_valid_steel_intent_no_errors(self, adapter):
        intent = _make_intent("Steel", material_family="ferrous", quantity=10)
        assert adapter.validate_intent(intent) == []

    def test_ceramic_material_rejected(self, adapter):
        intent = _make_intent("Ceramic", material_family="ceramic", quantity=5)
        errors = adapter.validate_intent(intent)
        assert any("ceramic" in e.lower() or "not suitable" in e.lower() for e in errors)

    def test_powder_form_rejected(self, adapter):
        intent = _make_intent("Steel", material_family="ferrous", quantity=5, form="powder")
        errors = adapter.validate_intent(intent)
        assert any("powder" in e.lower() for e in errors)

    def test_oversized_batch_rejected(self, adapter):
        intent = _make_intent("Steel", quantity=20_000)
        errors = adapter.validate_intent(intent)
        assert len(errors) > 0


# ---------------------------------------------------------------------------
# WeldingAdapter — ArcWeldingAdapter
# ---------------------------------------------------------------------------


class TestArcWeldingAdapter:

    @pytest.fixture
    def adapter(self):
        return ArcWeldingAdapter()

    @pytest.fixture
    def machine(self):
        return _weld_machine()

    def test_process_family(self, adapter):
        assert adapter.process_family == ProcessFamily.WELDING_ARC

    def test_cycle_time_uses_travel_speed(self, adapter, machine):
        """cycle_time = (weld_length / travel_speed) × passes × quantity."""
        weld_length_mm = 500.0
        travel_speed = TRAVEL_SPEED_MM_MIN["arc"]["steel"]
        intent = _make_intent("Steel", quantity=1, thickness_mm=3.0,
                               weld_length_mm=weld_length_mm)
        # 3mm thick → 1 pass, no preheat
        expected_minutes = (weld_length_mm / travel_speed) * 1  # 1 pass, qty=1
        result = adapter.estimate_cycle_time(intent, machine)
        assert abs(result - expected_minutes) < 1.0

    def test_cycle_time_increases_with_quantity(self, adapter, machine):
        t1 = adapter.estimate_cycle_time(_make_intent("Steel", quantity=1, weld_length_mm=500.0), machine)
        t5 = adapter.estimate_cycle_time(_make_intent("Steel", quantity=5, weld_length_mm=500.0), machine)
        assert t5 > t1

    def test_thick_section_adds_preheat(self, adapter, machine):
        thin_intent = _make_intent("Steel", quantity=1, thickness_mm=3.0, weld_length_mm=300.0)
        thick_intent = _make_intent("Steel", quantity=1, thickness_mm=20.0, weld_length_mm=300.0)
        thin_time = adapter.estimate_cycle_time(thin_intent, machine)
        thick_time = adapter.estimate_cycle_time(thick_intent, machine)
        assert thick_time > thin_time  # extra preheat time + more passes

    def test_validate_polymer_rejected(self, adapter):
        intent = _make_intent("Nylon", material_family="polymer", quantity=5)
        errors = adapter.validate_intent(intent)
        assert len(errors) > 0
        assert any("metallic" in e.lower() or "weldable" in e.lower() for e in errors)

    def test_consumables_include_filler_wire(self, adapter):
        intent = _make_intent("Steel", quantity=2, weld_length_mm=500.0)
        cons = adapter.get_consumables(intent)
        assert "filler_wire_kg" in cons
        assert cons["filler_wire_kg"] > 0

    def test_consumables_include_shielding_gas(self, adapter):
        intent = _make_intent("Steel", quantity=2, weld_length_mm=500.0, thickness_mm=3.0)
        cons = adapter.get_consumables(intent)
        assert "shielding_gas_m3" in cons
        assert cons["shielding_gas_m3"] > 0


# ---------------------------------------------------------------------------
# WeldingAdapter — LaserWeldingAdapter
# ---------------------------------------------------------------------------


class TestLaserWeldingAdapter:

    @pytest.fixture
    def adapter(self):
        return LaserWeldingAdapter()

    @pytest.fixture
    def machine(self):
        return MachineCapability(
            machine_id="LASER-001", machine_name="Laser Welder", machine_type="LASER_WELDER",
            capabilities=[ProcessCapability(process_family=ProcessFamily.WELDING_LASER,
                                            supported_materials=["steel", "aluminum"])],
        )

    def test_process_family(self, adapter):
        assert adapter.process_family == ProcessFamily.WELDING_LASER

    def test_laser_faster_than_arc_same_length(self, adapter, machine):
        arc = ArcWeldingAdapter()
        arc_machine = _weld_machine()
        intent = _make_intent("Steel", quantity=1, thickness_mm=3.0, weld_length_mm=500.0)
        laser_time = adapter.estimate_cycle_time(intent, machine)
        arc_time = arc.estimate_cycle_time(intent, arc_machine)
        # Laser travel speed is ~8–10x faster than arc
        assert laser_time < arc_time

    def test_copper_rejected(self, adapter):
        intent = _make_intent("Copper", material_family="non_ferrous", quantity=1)
        errors = adapter.validate_intent(intent)
        assert any("reflective" in e.lower() or "copper" in e.lower() for e in errors)

    def test_laser_no_filler_wire_for_steel(self, adapter):
        intent = _make_intent("Steel", quantity=1, weld_length_mm=300.0)
        cons = adapter.get_consumables(intent)
        # Laser autogenous for steel — no filler wire
        assert cons.get("filler_wire_kg", 0) == 0


# ---------------------------------------------------------------------------
# WeldingAdapter — EBWeldingAdapter
# ---------------------------------------------------------------------------


class TestEBWeldingAdapter:

    @pytest.fixture
    def adapter(self):
        return EBWeldingAdapter()

    @pytest.fixture
    def machine(self):
        return MachineCapability(
            machine_id="EBW-001", machine_name="EB Welder", machine_type="EBW",
            capabilities=[ProcessCapability(process_family=ProcessFamily.WELDING_EBW,
                                            supported_materials=["steel", "titanium", "aluminum"])],
        )

    def test_process_family(self, adapter):
        assert adapter.process_family == ProcessFamily.WELDING_EBW

    def test_no_shielding_gas_in_vacuum(self, adapter):
        intent = _make_intent("Steel", quantity=1, weld_length_mm=300.0, vacuum_chamber=True)
        cons = adapter.get_consumables(intent)
        # EBW operates in vacuum — zero shielding gas
        assert cons.get("shielding_gas_m3", 0) == 0

    def test_ebw_requires_vacuum_chamber(self, adapter):
        intent = _make_intent("Steel", quantity=1, weld_length_mm=300.0)
        # No vacuum_chamber in metadata
        errors = adapter.validate_intent(intent)
        assert any("vacuum" in e.lower() for e in errors)

    def test_ebw_large_batch_rejected(self, adapter):
        intent = _make_intent("Steel", quantity=200, vacuum_chamber=True)
        errors = adapter.validate_intent(intent)
        assert any("batch" in e.lower() or "200" in e for e in errors)


# ---------------------------------------------------------------------------
# WeldingAdapter — factory function
# ---------------------------------------------------------------------------


def test_get_welding_adapter_factory():
    assert isinstance(get_welding_adapter(ProcessFamily.WELDING_ARC), ArcWeldingAdapter)
    assert isinstance(get_welding_adapter(ProcessFamily.WELDING_LASER), LaserWeldingAdapter)
    assert isinstance(get_welding_adapter(ProcessFamily.WELDING_EBW), EBWeldingAdapter)
    assert get_welding_adapter(ProcessFamily.CNC_MILLING) is None


# ---------------------------------------------------------------------------
# PressBrakeAdapter — tonnage calculation
# ---------------------------------------------------------------------------


class TestPressBrakeAdapter:

    @pytest.fixture
    def adapter(self):
        return PressBrakeAdapter()

    @pytest.fixture
    def machine(self):
        return _press_brake_machine()

    def test_tonnage_increases_with_thickness(self, adapter):
        """Thicker material requires more force."""
        t3 = adapter._calculate_tonnage("steel", 3.0, 200.0, adapter._select_v_die(3.0))
        t6 = adapter._calculate_tonnage("steel", 6.0, 200.0, adapter._select_v_die(6.0))
        assert t6 > t3

    def test_tonnage_increases_with_bend_length(self, adapter):
        """Longer bend requires more tonnage."""
        t_short = adapter._calculate_tonnage("steel", 3.0, 100.0, 16.0)
        t_long = adapter._calculate_tonnage("steel", 3.0, 400.0, 16.0)
        assert t_long > t_short

    def test_titanium_higher_tonnage_than_aluminum(self, adapter):
        ti = adapter._calculate_tonnage("titanium", 3.0, 200.0, 16.0)
        al = adapter._calculate_tonnage("aluminum", 3.0, 200.0, 16.0)
        assert ti > al

    def test_tonnage_is_positive(self, adapter):
        for mat in ["steel", "aluminum", "stainless_steel", "titanium"]:
            t = adapter._calculate_tonnage(mat, 3.0, 200.0, 16.0)
            assert t > 0, f"Expected positive tonnage for {mat}"

    def test_v_die_selection(self, adapter):
        assert adapter._select_v_die(1.0) == 8.0
        assert adapter._select_v_die(2.0) == 16.0
        assert adapter._select_v_die(4.0) == 40.0
        assert adapter._select_v_die(8.0) == 60.0

    def test_springback_titanium_highest(self):
        """Titanium has highest springback among common metals."""
        assert SPRINGBACK_DEG["titanium"] > SPRINGBACK_DEG["steel"]
        assert SPRINGBACK_DEG["titanium"] > SPRINGBACK_DEG["aluminum"]

    def test_springback_copper_lowest(self):
        """Copper is very ductile — minimal springback."""
        assert SPRINGBACK_DEG["copper"] <= SPRINGBACK_DEG["steel"]

    def test_cycle_time_proportional_to_bends(self, adapter, machine):
        intent_4 = _make_intent("Steel", quantity=10, form="sheet",
                                 thickness_mm=2.0, bends_per_part=4)
        intent_8 = _make_intent("Steel", quantity=10, form="sheet",
                                 thickness_mm=2.0, bends_per_part=8)
        t4 = adapter.estimate_cycle_time(intent_4, machine)
        t8 = adapter.estimate_cycle_time(intent_8, machine)
        assert t8 > t4

    def test_validate_bar_stock_form_rejected(self, adapter):
        intent = _make_intent("Steel", quantity=10, form="bar_stock", thickness_mm=5.0)
        errors = adapter.validate_intent(intent)
        assert any("bar_stock" in e.lower() or "sheet" in e.lower() for e in errors)

    def test_validate_sheet_form_accepted(self, adapter):
        intent = _make_intent("Steel", quantity=10, form="sheet", thickness_mm=3.0)
        errors = adapter.validate_intent(intent)
        # Should have no form-related error
        assert not any("sheet" in e.lower() and "not suitable" in e.lower() for e in errors)

    def test_setup_sheet_includes_tonnage(self, adapter, machine):
        intent = _make_intent("Steel", quantity=5, form="sheet",
                               thickness_mm=3.0, width_mm=200.0)
        sheet = adapter.generate_setup_sheet(intent, machine)
        params = sheet["process_parameters"]
        assert "required_tonnage_tons" in params
        assert params["required_tonnage_tons"] > 0

    def test_setup_sheet_includes_springback_compensation(self, adapter, machine):
        intent = _make_intent("Steel", quantity=5, form="sheet", thickness_mm=3.0, width_mm=200.0)
        sheet = adapter.generate_setup_sheet(intent, machine)
        params = sheet["process_parameters"]
        assert "springback_compensation_deg" in params
        assert params["springback_compensation_deg"] > 0

    def test_consumables_returns_sheet_material(self, adapter):
        intent = _make_intent("Steel", quantity=10, form="sheet",
                               thickness_mm=3.0, width_mm=200.0, length_mm=300.0)
        cons = adapter.get_consumables(intent)
        assert len(cons) > 0
        # should have a key that contains "steel"
        assert any("steel" in k.lower() for k in cons)
