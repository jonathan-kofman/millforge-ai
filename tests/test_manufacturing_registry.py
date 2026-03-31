"""
Tests for manufacturing/registry.py

Covers:
  - ProcessRegistry singleton behavior (thread safety)
  - Adapter registration and retrieval
  - Machine registration and capability matching
  - find_capable_machines with material filtering
  - list_supported_processes
  - CNCMillingAdapter through the registry
  - MachineCapability.supports_material and get_capability
  - ProcessCapability.supports_material and fits_in_envelope
"""

import sys
import os
import threading

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from manufacturing.ontology import (
    EnergyProfile,
    ManufacturingIntent,
    MaterialSpec,
    ProcessFamily,
)
from manufacturing.registry import (
    MachineCapability,
    ProcessCapability,
    ProcessRegistry,
)
from manufacturing.adapters.cnc_milling import CNCMillingAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cnc_capability(materials=None) -> ProcessCapability:
    return ProcessCapability(
        process_family=ProcessFamily.CNC_MILLING,
        supported_materials=materials or ["steel", "aluminum", "titanium"],
        max_part_dimensions_mm=(600.0, 400.0, 300.0),
        min_part_dimensions_mm=(1.0, 1.0, 1.0),
        tolerances={"position_mm": 0.01, "surface_ra_um": 0.8},
        throughput_range=(2.0, 8.0),
        setup_time_range_minutes=(15.0, 90.0),
        energy_profile=EnergyProfile(base_power_kw=85.0, peak_power_kw=120.0, idle_power_kw=8.0),
    )


def _make_machine(machine_id: str, available: bool = True, materials=None) -> MachineCapability:
    return MachineCapability(
        machine_id=machine_id,
        machine_name=f"VMC {machine_id}",
        machine_type="VMC",
        capabilities=[_make_cnc_capability(materials)],
        is_available=available,
        location="Cell 1",
    )


def _make_steel_intent() -> ManufacturingIntent:
    return ManufacturingIntent(
        part_id="TEST-001",
        part_name="Test Part",
        target_quantity=5,
        material=MaterialSpec(
            material_name="Steel",
            material_family="ferrous",
            form="bar_stock",
        ),
        required_processes=[ProcessFamily.CNC_MILLING],
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def fresh_registry():
    """Destroy singleton before and after each test for isolation."""
    ProcessRegistry.reset()
    yield
    ProcessRegistry.reset()


@pytest.fixture
def registry() -> ProcessRegistry:
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_machine("VMC-001"))
    r.register_machine(_make_machine("VMC-002"))
    return r


# ---------------------------------------------------------------------------
# Singleton behavior
# ---------------------------------------------------------------------------


def test_get_instance_returns_same_object():
    r1 = ProcessRegistry.get_instance()
    r2 = ProcessRegistry.get_instance()
    assert r1 is r2


def test_reset_creates_new_instance():
    r1 = ProcessRegistry.get_instance()
    ProcessRegistry.reset()
    r2 = ProcessRegistry.get_instance()
    assert r1 is not r2


def test_singleton_thread_safety():
    """Multiple threads hitting get_instance() should all get the same object."""
    instances = []
    errors = []

    def grab():
        try:
            instances.append(ProcessRegistry.get_instance())
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=grab) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # All must be the exact same object
    assert all(inst is instances[0] for inst in instances)


# ---------------------------------------------------------------------------
# Adapter registration
# ---------------------------------------------------------------------------


def test_register_adapter():
    r = ProcessRegistry.get_instance()
    adapter = CNCMillingAdapter()
    r.register_adapter(adapter)
    assert r.get_adapter(ProcessFamily.CNC_MILLING) is adapter


def test_get_adapter_unregistered_returns_none():
    r = ProcessRegistry.get_instance()
    assert r.get_adapter(ProcessFamily.WELDING_ARC) is None


def test_register_adapter_replaces_existing():
    r = ProcessRegistry.get_instance()
    adapter1 = CNCMillingAdapter()
    adapter2 = CNCMillingAdapter()
    r.register_adapter(adapter1)
    r.register_adapter(adapter2)
    assert r.get_adapter(ProcessFamily.CNC_MILLING) is adapter2


def test_list_supported_processes(registry):
    supported = registry.list_supported_processes()
    assert ProcessFamily.CNC_MILLING in supported


def test_list_supported_processes_empty_when_no_adapters():
    r = ProcessRegistry.get_instance()
    assert r.list_supported_processes() == []


# ---------------------------------------------------------------------------
# Machine registration
# ---------------------------------------------------------------------------


def test_register_machine():
    r = ProcessRegistry.get_instance()
    machine = _make_machine("VMC-TEST")
    r.register_machine(machine)
    assert r.get_machine("VMC-TEST") is not None


def test_get_machine_unknown_returns_none():
    r = ProcessRegistry.get_instance()
    assert r.get_machine("NONEXISTENT") is None


def test_register_machine_updates_existing():
    r = ProcessRegistry.get_instance()
    m1 = _make_machine("VMC-001", available=True)
    r.register_machine(m1)
    m2 = _make_machine("VMC-001", available=False)
    r.register_machine(m2)
    fetched = r.get_machine("VMC-001")
    assert fetched.is_available is False


def test_list_machines_available_only(registry):
    unavailable = _make_machine("VMC-DOWN", available=False)
    registry.register_machine(unavailable)
    available = registry.list_machines(available_only=True)
    ids = [m.machine_id for m in available]
    assert "VMC-DOWN" not in ids
    assert "VMC-001" in ids


def test_list_machines_all_including_unavailable(registry):
    unavailable = _make_machine("VMC-DOWN", available=False)
    registry.register_machine(unavailable)
    all_machines = registry.list_machines(available_only=False)
    ids = [m.machine_id for m in all_machines]
    assert "VMC-DOWN" in ids


def test_update_machine_availability(registry):
    success = registry.update_machine_availability("VMC-001", is_available=False, current_job_id="JOB-42")
    assert success is True
    machine = registry.get_machine("VMC-001")
    assert machine.is_available is False
    assert machine.current_job_id == "JOB-42"


def test_update_machine_availability_unknown_machine(registry):
    success = registry.update_machine_availability("GHOST-999", is_available=False)
    assert success is False


# ---------------------------------------------------------------------------
# Capability matching
# ---------------------------------------------------------------------------


def test_find_capable_machines_by_material(registry):
    machines = registry.find_capable_machines(ProcessFamily.CNC_MILLING, "steel")
    assert len(machines) == 2
    assert all(m.machine_id in {"VMC-001", "VMC-002"} for m in machines)


def test_find_capable_machines_unsupported_material():
    """A machine with explicit material list excludes unlisted materials."""
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    # Only steel — not ceramic
    m = _make_machine("VMC-STEEL", materials=["steel"])
    r.register_machine(m)
    results = r.find_capable_machines(ProcessFamily.CNC_MILLING, "ceramic")
    assert all(m2.machine_id != "VMC-STEEL" for m2 in results)


def test_find_capable_machines_excludes_unavailable():
    r = ProcessRegistry.get_instance()
    r.register_adapter(CNCMillingAdapter())
    r.register_machine(_make_machine("VMC-OK", available=True))
    r.register_machine(_make_machine("VMC-DOWN", available=False))
    results = r.find_capable_machines(ProcessFamily.CNC_MILLING, "steel")
    ids = [m.machine_id for m in results]
    assert "VMC-OK" in ids
    assert "VMC-DOWN" not in ids


def test_find_capable_machines_returns_sorted(registry):
    machines = registry.find_capable_machines(ProcessFamily.CNC_MILLING, "steel")
    ids = [m.machine_id for m in machines]
    assert ids == sorted(ids)


def test_find_capable_machines_any_material(registry):
    results = registry.find_capable_machines_any_material(ProcessFamily.CNC_MILLING)
    assert len(results) == 2


def test_cnc_adapter_works_through_registry(registry):
    intent = _make_steel_intent()
    adapter = registry.get_adapter(ProcessFamily.CNC_MILLING)
    assert adapter is not None
    errors = adapter.validate_intent(intent)
    assert errors == []


def test_cnc_adapter_cycle_time_through_registry(registry):
    intent = _make_steel_intent()
    machine = registry.get_machine("VMC-001")
    adapter = registry.get_adapter(ProcessFamily.CNC_MILLING)
    cycle_time = adapter.estimate_cycle_time(intent, machine)
    assert cycle_time > 0


# ---------------------------------------------------------------------------
# ProcessCapability helpers
# ---------------------------------------------------------------------------


def test_process_capability_supports_material():
    cap = _make_cnc_capability(materials=["steel", "aluminum"])
    assert cap.supports_material("steel") is True
    assert cap.supports_material("STEEL") is True  # case-insensitive
    assert cap.supports_material("titanium") is False


def test_machine_capability_empty_material_list_accepts_all():
    """
    MachineCapability.supports_material() treats an empty capability material list
    as "accept all" — this is the layer where that semantic is applied.
    """
    machine = MachineCapability(
        machine_id="OPEN-001",
        machine_name="Open Machine",
        machine_type="VMC",
        capabilities=[
            ProcessCapability(
                process_family=ProcessFamily.CNC_MILLING,
                supported_materials=[],  # empty = accept all materials
            )
        ],
    )
    # MachineCapability.supports_material() returns True for any material
    # when the ProcessCapability has an empty supported_materials list
    assert machine.supports_material(ProcessFamily.CNC_MILLING, "unobtainium") is True


def test_process_capability_fits_in_envelope():
    cap = _make_cnc_capability()
    assert cap.fits_in_envelope((100.0, 100.0, 100.0)) is True
    assert cap.fits_in_envelope((700.0, 100.0, 100.0)) is False


def test_process_capability_no_envelope_always_fits():
    cap = ProcessCapability(
        process_family=ProcessFamily.CNC_MILLING,
        max_part_dimensions_mm=None,
    )
    assert cap.fits_in_envelope((9999.0, 9999.0, 9999.0)) is True


# ---------------------------------------------------------------------------
# Registry stats
# ---------------------------------------------------------------------------


def test_get_stats(registry):
    stats = registry.get_stats()
    assert stats["registered_adapters"] == 1
    assert stats["registered_machines"] == 2
    assert stats["available_machines"] == 2
    assert ProcessFamily.CNC_MILLING.value in stats["supported_processes"]
