"""
Manufacturing Adapters Package
================================
Concrete ProcessAdapter implementations for each supported ProcessFamily.

Available adapters:
  - CNCMillingAdapter          → ProcessFamily.CNC_MILLING
  - ArcWeldingAdapter          → ProcessFamily.WELDING_ARC
  - LaserWeldingAdapter        → ProcessFamily.WELDING_LASER
  - EBWeldingAdapter           → ProcessFamily.WELDING_EBW
  - PressBrakeAdapter          → ProcessFamily.BENDING_PRESS_BRAKE
  - LaserCuttingAdapter        → ProcessFamily.CUTTING_LASER
  - PlasmaCuttingAdapter       → ProcessFamily.CUTTING_PLASMA
  - WaterjetCuttingAdapter     → ProcessFamily.CUTTING_WATERJET
  - StampingAdapter            → ProcessFamily.STAMPING
  - WireEDMAdapter             → ProcessFamily.EDM_WIRE
  - SinkerEDMAdapter           → ProcessFamily.EDM_SINKER
  - InjectionMoldingAdapter    → ProcessFamily.INJECTION_MOLDING
  - CMMInspectionAdapter       → ProcessFamily.INSPECTION_CMM
  - VisionInspectionAdapter    → ProcessFamily.INSPECTION_VISION
  - XRayInspectionAdapter      → ProcessFamily.INSPECTION_XRAY

Utility:
  - get_welding_adapter(family) → correct welding adapter by ProcessFamily

Usage:
    from manufacturing.adapters import (
        CNCMillingAdapter,
        ArcWeldingAdapter,
        PressBrakeAdapter,
        LaserCuttingAdapter,
        StampingAdapter,
        WireEDMAdapter,
        InjectionMoldingAdapter,
        CMMInspectionAdapter,
    )
    from manufacturing.registry import ProcessRegistry

    registry = ProcessRegistry.get_instance()
    registry.register_adapter(CNCMillingAdapter())
    registry.register_adapter(LaserCuttingAdapter())
"""

from .base_adapter import (
    BASE_SETUP_MINUTES,
    KG_PER_UNIT,
    MACHINE_POWER_KW,
    SETUP_MATRIX,
    THROUGHPUT,
    BaseAdapter,
)
from .bending import PressBrakeAdapter
from .cnc_milling import CNCMillingAdapter
from .cutting import LaserCuttingAdapter, PlasmaCuttingAdapter, WaterjetCuttingAdapter
from .edm import SinkerEDMAdapter, WireEDMAdapter
from .inspection import CMMInspectionAdapter, VisionInspectionAdapter, XRayInspectionAdapter
from .molding import InjectionMoldingAdapter
from .stamping import StampingAdapter
from .welding import (
    ArcWeldingAdapter,
    EBWeldingAdapter,
    LaserWeldingAdapter,
    get_welding_adapter,
)

__all__ = [
    # Base
    "BaseAdapter",
    "BASE_SETUP_MINUTES",
    "SETUP_MATRIX",
    "THROUGHPUT",
    "MACHINE_POWER_KW",
    "KG_PER_UNIT",
    # CNC
    "CNCMillingAdapter",
    # Welding
    "ArcWeldingAdapter",
    "LaserWeldingAdapter",
    "EBWeldingAdapter",
    "get_welding_adapter",
    # Forming
    "PressBrakeAdapter",
    "StampingAdapter",
    # Cutting
    "LaserCuttingAdapter",
    "PlasmaCuttingAdapter",
    "WaterjetCuttingAdapter",
    # EDM
    "WireEDMAdapter",
    "SinkerEDMAdapter",
    # Molding
    "InjectionMoldingAdapter",
    # Inspection
    "CMMInspectionAdapter",
    "VisionInspectionAdapter",
    "XRayInspectionAdapter",
]
