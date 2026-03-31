"""
Manufacturing Process Registry
================================
Singleton registry that holds all registered process adapters and known
machine capabilities. Thread-safe for concurrent access from FastAPI handlers
and background agents.

Key components:
  - ProcessCapability: what dimensions, tolerances, throughput a process can achieve
  - MachineCapability: what a specific physical machine can do
  - ProcessAdapter: abstract interface each process must implement
  - ProcessRegistry: singleton that wires it all together
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from .ontology import (
    EnergyProfile,
    FixtureSpec,
    ManufacturingIntent,
    ProcessFamily,
    QualityRequirement,
    ToolingSpec,
)


# ---------------------------------------------------------------------------
# Capability Models
# ---------------------------------------------------------------------------


class ProcessCapability(BaseModel):
    """
    Describes what a process family can physically achieve.

    Attributes:
        process_family:           Which process this capability describes
        supported_materials:      List of normalized material names (lowercase)
        max_part_dimensions_mm:   (X, Y, Z) work envelope maximum
        min_part_dimensions_mm:   (X, Y, Z) minimum feature / part size
        tolerances:               Achievable tolerances, e.g. {"position_mm": 0.01, "surface_ra_um": 0.8}
        throughput_range:         (min, max) units or mm per hour depending on process
        setup_time_range_minutes: (min, max) typical setup time window
        energy_profile:           Typical energy draw for this process
        supported_batch_range:    (min_batch, max_batch) — None means unlimited max
    """
    process_family: ProcessFamily
    supported_materials: List[str] = Field(default_factory=list)
    max_part_dimensions_mm: Optional[Tuple[float, float, float]] = None
    min_part_dimensions_mm: Optional[Tuple[float, float, float]] = None
    tolerances: Dict[str, float] = Field(default_factory=dict)
    throughput_range: Optional[Tuple[float, float]] = None
    setup_time_range_minutes: Optional[Tuple[float, float]] = None
    energy_profile: Optional[EnergyProfile] = None
    supported_batch_range: Optional[Tuple[int, int]] = None

    def supports_material(self, material: str) -> bool:
        """Case-insensitive check for material support."""
        needle = material.lower().strip()
        return any(m.lower() == needle for m in self.supported_materials)

    def fits_in_envelope(self, dims_mm: Tuple[float, float, float]) -> bool:
        """Return True if all three dimensions fit within the work envelope."""
        if self.max_part_dimensions_mm is None:
            return True
        return all(d <= m for d, m in zip(dims_mm, self.max_part_dimensions_mm))


class MachineCapability(BaseModel):
    """
    Describes a physical machine asset and its capabilities.

    Attributes:
        machine_id:        Unique identifier (e.g. "VMC-001", "WELD-CELL-A")
        machine_name:      Human-readable name
        machine_type:      Category string (e.g. "VMC", "HMC", "MIG_WELDER", "PRESS_BRAKE")
        capabilities:      List of process capabilities this machine has
        is_available:      False when machine is in maintenance or reserved
        current_job_id:    Active job ID if machine is occupied
        location:          Physical location (e.g. "Cell 3", "Bay B")
        max_weight_kg:     Maximum workpiece weight the machine can handle
        custom_attributes: Catch-all for machine-specific metadata
    """
    machine_id: str
    machine_name: str
    machine_type: str
    capabilities: List[ProcessCapability] = Field(default_factory=list)
    is_available: bool = True
    current_job_id: Optional[str] = None
    location: str = ""
    max_weight_kg: Optional[float] = None
    custom_attributes: Dict[str, Any] = Field(default_factory=dict)

    def get_capability(self, family: ProcessFamily) -> Optional[ProcessCapability]:
        """Return the first matching ProcessCapability for the given family, or None."""
        for cap in self.capabilities:
            if cap.process_family == family:
                return cap
        return None

    def supports_process(self, family: ProcessFamily) -> bool:
        return self.get_capability(family) is not None

    def supports_material(self, family: ProcessFamily, material: str) -> bool:
        cap = self.get_capability(family)
        if cap is None:
            return False
        # Empty list = accepts all materials
        if not cap.supported_materials:
            return True
        return cap.supports_material(material)


# ---------------------------------------------------------------------------
# ProcessAdapter Protocol / Abstract Base Class
# ---------------------------------------------------------------------------


class ProcessAdapter(ABC):
    """
    Abstract base class for process-specific manufacturing logic.

    Each concrete adapter encapsulates one ProcessFamily's domain knowledge:
      - Validation rules (material/geometry compatibility checks)
      - Cycle time and cost models
      - Tooling and fixture selection
      - Quality check requirements
      - Consumables consumption
      - Energy profiling

    Adapters are registered with ProcessRegistry and invoked by RoutingEngine.
    They must be stateless — all inputs arrive via method parameters.
    """

    @property
    @abstractmethod
    def process_family(self) -> ProcessFamily:
        """The ProcessFamily this adapter handles."""
        ...

    @abstractmethod
    def validate_intent(self, intent: ManufacturingIntent) -> List[str]:
        """
        Validate a manufacturing intent against this process's constraints.

        Returns a list of human-readable error strings. An empty list means
        the intent is valid for this process.
        """
        ...

    @abstractmethod
    def estimate_cycle_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate the per-unit cycle time in minutes for the given intent
        running on the specified machine.
        """
        ...

    @abstractmethod
    def estimate_cost(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total job cost in USD. Should include labor, tooling wear,
        consumables, and energy. Does NOT include setup cost (handled separately).
        """
        ...

    @abstractmethod
    def generate_setup_sheet(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> Dict[str, Any]:
        """
        Generate a machine-specific setup sheet as a structured dict.
        This is the data that flows to an operator's screen or a robot controller.
        """
        ...

    @abstractmethod
    def get_required_tooling(self, intent: ManufacturingIntent) -> List[ToolingSpec]:
        """Return the list of tooling required to execute this intent."""
        ...

    @abstractmethod
    def get_required_fixtures(self, intent: ManufacturingIntent) -> List[FixtureSpec]:
        """Return the list of fixtures required to hold the workpiece."""
        ...

    @abstractmethod
    def get_quality_checks(self, intent: ManufacturingIntent) -> List[QualityRequirement]:
        """Return required quality checks for this process and intent."""
        ...

    @abstractmethod
    def get_consumables(self, intent: ManufacturingIntent) -> Dict[str, float]:
        """
        Return a mapping of consumable material name → kilograms consumed for
        the full job (all units). E.g. {"filler_wire_er70s6": 0.45, "argon_gas_m3": 2.1}.
        """
        ...

    @abstractmethod
    def get_energy_profile(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> EnergyProfile:
        """Return the expected energy profile for this job on this machine."""
        ...

    # ------------------------------------------------------------------
    # Convenience helper — not abstract
    # ------------------------------------------------------------------

    def estimate_setup_time(
        self, intent: ManufacturingIntent, machine: MachineCapability
    ) -> float:
        """
        Estimate total setup time in minutes. Base implementation returns
        the machine capability's min setup time or a process-family default.
        Concrete subclasses should override with material-changeover logic.
        """
        cap = machine.get_capability(self.process_family)
        if cap and cap.setup_time_range_minutes:
            return cap.setup_time_range_minutes[0]
        return 30.0  # sane global default


# ---------------------------------------------------------------------------
# Process Registry (Singleton)
# ---------------------------------------------------------------------------


class ProcessRegistry:
    """
    Thread-safe singleton registry for process adapters and machine capabilities.

    Usage:
        registry = ProcessRegistry.get_instance()
        registry.register_adapter(CNCMillingAdapter())
        registry.register_machine(MachineCapability(...))

        adapter = registry.get_adapter(ProcessFamily.CNC_MILLING)
        machines = registry.find_capable_machines(ProcessFamily.CNC_MILLING, "aluminum")
    """

    _instance: Optional["ProcessRegistry"] = None
    _singleton_lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._adapters: Dict[ProcessFamily, ProcessAdapter] = {}
        self._machines: Dict[str, MachineCapability] = {}
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "ProcessRegistry":
        """Return the global singleton instance, creating it if necessary."""
        if cls._instance is None:
            with cls._singleton_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Destroy the singleton (useful in tests). Not thread-safe; call before workers start."""
        with cls._singleton_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Adapter management
    # ------------------------------------------------------------------

    def register_adapter(self, adapter: ProcessAdapter) -> None:
        """
        Register a process adapter. Replaces any existing adapter for the
        same ProcessFamily (last-writer wins — useful for test overrides).
        """
        with self._lock:
            self._adapters[adapter.process_family] = adapter

    def get_adapter(self, process_family: ProcessFamily) -> Optional[ProcessAdapter]:
        """Return the registered adapter for a process family, or None."""
        with self._lock:
            return self._adapters.get(process_family)

    def list_supported_processes(self) -> List[ProcessFamily]:
        """Return all process families that have a registered adapter."""
        with self._lock:
            return list(self._adapters.keys())

    # ------------------------------------------------------------------
    # Machine management
    # ------------------------------------------------------------------

    def register_machine(self, machine: MachineCapability) -> None:
        """Register or update a machine. machine_id is the primary key."""
        with self._lock:
            self._machines[machine.machine_id] = machine

    def get_machine(self, machine_id: str) -> Optional[MachineCapability]:
        """Return a machine by ID, or None if not registered."""
        with self._lock:
            return self._machines.get(machine_id)

    def list_machines(self, available_only: bool = True) -> List[MachineCapability]:
        """
        List all registered machines.

        Args:
            available_only: If True (default), only return machines where is_available=True.
        """
        with self._lock:
            machines = list(self._machines.values())
        if available_only:
            return [m for m in machines if m.is_available]
        return machines

    def update_machine_availability(
        self, machine_id: str, is_available: bool, current_job_id: Optional[str] = None
    ) -> bool:
        """
        Update availability status for a machine. Returns False if machine not found.
        Thread-safe.
        """
        with self._lock:
            machine = self._machines.get(machine_id)
            if machine is None:
                return False
            # Replace with updated copy (Pydantic model is immutable by default)
            updated = machine.model_copy(
                update={"is_available": is_available, "current_job_id": current_job_id}
            )
            self._machines[machine_id] = updated
        return True

    def find_capable_machines(
        self, process_family: ProcessFamily, material: str
    ) -> List[MachineCapability]:
        """
        Find all available machines capable of running the given process
        on the specified material.

        Returns machines sorted by machine_id for deterministic ordering.
        """
        with self._lock:
            machines = list(self._machines.values())
        result = []
        for machine in machines:
            if not machine.is_available:
                continue
            if not machine.supports_process(process_family):
                continue
            if not machine.supports_material(process_family, material):
                continue
            result.append(machine)
        return sorted(result, key=lambda m: m.machine_id)

    def find_capable_machines_any_material(
        self, process_family: ProcessFamily
    ) -> List[MachineCapability]:
        """Find all available machines capable of the given process, regardless of material."""
        with self._lock:
            machines = list(self._machines.values())
        return sorted(
            [m for m in machines if m.is_available and m.supports_process(process_family)],
            key=lambda m: m.machine_id,
        )

    def get_stats(self) -> Dict[str, Any]:
        """Return registry health statistics."""
        with self._lock:
            total_machines = len(self._machines)
            available = sum(1 for m in self._machines.values() if m.is_available)
            process_count = len(self._adapters)
        return {
            "registered_adapters": process_count,
            "registered_machines": total_machines,
            "available_machines": available,
            "occupied_machines": total_machines - available,
            "supported_processes": [p.value for p in self._adapters.keys()],
        }
