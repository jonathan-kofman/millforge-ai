"""
ARIABridgeAgent — translates ARIA-OS scan catalog entries into MillForge
quotable, schedulable jobs without human CAD interpretation.

A scanned part from ARIA-OS arrives as a catalog JSON dict containing bounding
box geometry, volume, and a primitives summary. This agent maps that directly
to MillForge's internal Order / QuoteRequest shapes.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Material mapping — ARIA designations → MillForge MaterialType values
# ARIA uses alloy designations; MillForge only has four base materials.
# ---------------------------------------------------------------------------
MATERIAL_MAP: Dict[str, str] = {
    # Aluminum alloys → aluminum
    "6061-T6": "aluminum",
    "7075-T6": "aluminum",
    "2024-T3": "aluminum",
    "5052-H32": "aluminum",
    "aluminum": "aluminum",
    "aluminium": "aluminum",
    "al": "aluminum",
    # Steel alloys → steel
    "1018": "steel",
    "4140": "steel",
    "4340": "steel",
    "316L": "steel",
    "304": "steel",
    "17-4ph": "steel",
    "stainless": "steel",
    "steel": "steel",
    "mild_steel": "steel",
    # Titanium alloys → titanium
    "ti-6al-4v": "titanium",
    "gr5": "titanium",
    "grade5": "titanium",
    "grade2": "titanium",
    "titanium": "titanium",
    "ti": "titanium",
    # Copper alloys → copper
    "c110": "copper",
    "c360": "copper",
    "brass": "copper",
    "bronze": "copper",
    "copper": "copper",
    "cu": "copper",
}

# Material removal rate (mm³/min) — mid-range conservative estimate per material
MATERIAL_MRR: Dict[str, float] = {
    "aluminum": 12_000.0,
    "steel":     3_500.0,
    "titanium":  1_200.0,
    "copper":    6_000.0,
}

# Extra machining time per primitive feature type (minutes per feature)
FEATURE_TIME: Dict[str, float] = {
    "hole":      2.5,
    "pocket":    4.0,
    "slot":      3.0,
    "thread":    1.5,
    "chamfer":   0.5,
    "fillet":    0.5,
    "boss":      3.0,
    "rib":       2.0,
    "groove":    1.5,
    "contour":   5.0,
    "surface":   8.0,
}

# Complexity weight per feature type (relative to a plain block = 1.0)
FEATURE_COMPLEXITY_WEIGHT: Dict[str, float] = {
    "hole":      0.10,
    "pocket":    0.20,
    "slot":      0.15,
    "thread":    0.12,
    "chamfer":   0.03,
    "fillet":    0.03,
    "boss":      0.15,
    "rib":       0.10,
    "groove":    0.08,
    "contour":   0.25,
    "surface":   0.35,
}


class ARIABridgeAgent:
    """
    Stateless translation agent — no DB dependency, no scheduler state.
    Methods operate purely on the catalog entry dict.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def map_material(self, aria_material: str) -> str:
        """
        Return the MillForge MaterialType value for an ARIA material string.
        Raises ValueError if material is not recognised.
        """
        key = aria_material.strip().lower()
        # Try exact lower-case match first
        for k, v in MATERIAL_MAP.items():
            if k.lower() == key:
                return v
        # Try prefix / substring match as fallback
        for k, v in MATERIAL_MAP.items():
            if key.startswith(k.lower()) or k.lower().startswith(key):
                return v
        raise ValueError(
            f"Unknown ARIA material: '{aria_material}'. "
            f"Supported materials: {sorted(set(MATERIAL_MAP.values()))}"
        )

    def estimate_complexity(self, catalog_entry: Dict[str, Any]) -> float:
        """
        Estimate processing complexity (1.0–5.0) from a catalog entry's
        primitives_summary list.

        Algorithm:
        - Start at 1.0 (plain block)
        - Add weighted contribution per primitive feature count
        - Clamp to [1.0, 5.0]
        """
        primitives: List[Dict[str, Any]] = catalog_entry.get("primitives_summary", [])
        if not primitives:
            return 1.0

        complexity = 1.0
        for p in primitives:
            ptype = p.get("type", "").lower()
            count = int(p.get("count", 1))
            weight = FEATURE_COMPLEXITY_WEIGHT.get(ptype, 0.05)
            complexity += weight * count

        return round(min(5.0, max(1.0, complexity)), 2)

    def estimate_machining_minutes(self, catalog_entry: Dict[str, Any]) -> float:
        """
        Estimate total machining time in minutes.

        Method:
        1. Volume removal ≈ 35% of bounding box volume (average stock removal)
        2. Material MRR (mm³/min) gives base machining time
        3. Add feature setup time from primitives_summary
        """
        material_raw = catalog_entry.get("material", "steel")
        try:
            material = self.map_material(material_raw)
        except ValueError:
            material = "steel"

        # Volume removal estimate
        volume_mm3 = float(catalog_entry.get("volume_mm3") or 0.0)
        if volume_mm3 <= 0.0:
            bb = catalog_entry.get("bounding_box", {})
            x = float(bb.get("x", 50))
            y = float(bb.get("y", 50))
            z = float(bb.get("z", 10))
            volume_mm3 = x * y * z

        removal_fraction = 0.35
        removal_volume = volume_mm3 * removal_fraction
        mrr = MATERIAL_MRR.get(material, 3_500.0)
        base_minutes = removal_volume / mrr

        # Feature time
        feature_minutes = 0.0
        for p in catalog_entry.get("primitives_summary", []):
            ptype = p.get("type", "").lower()
            count = int(p.get("count", 1))
            feature_minutes += FEATURE_TIME.get(ptype, 1.0) * count

        total = base_minutes + feature_minutes
        # Floor at 1 minute, ceil at 480 minutes per job
        return round(min(480.0, max(1.0, total)), 1)

    def catalog_to_dimensions(self, catalog_entry: Dict[str, Any]) -> str:
        """Return dimensions string from bounding box or default."""
        bb = catalog_entry.get("bounding_box", {})
        x = bb.get("x") or bb.get("length") or 50
        y = bb.get("y") or bb.get("width") or 50
        z = bb.get("z") or bb.get("height") or 10
        return f"{x}x{y}x{z}mm"

    def catalog_to_quote(
        self,
        catalog_entry: Dict[str, Any],
        quantity: int = 1,
    ) -> Dict[str, Any]:
        """
        Build a QuoteRequest-compatible dict from a catalog entry.
        The caller passes this to the quote endpoint or calls the Scheduler
        directly.
        """
        material_raw = catalog_entry.get("material", "steel")
        try:
            material = self.map_material(material_raw)
        except ValueError as e:
            raise ValueError(str(e))

        complexity = self.estimate_complexity(catalog_entry)
        dimensions = self.catalog_to_dimensions(catalog_entry)
        part_id = catalog_entry.get("part_id") or catalog_entry.get("id") or "SCAN"

        return {
            "material": material,
            "dimensions": dimensions,
            "quantity": quantity,
            "priority": int(catalog_entry.get("priority", 5)),
            "complexity": complexity,
            "source_part_id": part_id,
            "estimated_machining_minutes": self.estimate_machining_minutes(catalog_entry),
        }

    def catalog_to_order(
        self,
        catalog_entry: Dict[str, Any],
        quantity: int = 1,
        due_date: Optional[datetime] = None,
        priority: int = 5,
    ) -> Dict[str, Any]:
        """
        Build an OrderInput-compatible dict from a catalog entry.
        """
        quote_data = self.catalog_to_quote(catalog_entry, quantity)
        if due_date is None:
            due_date = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=14)

        order_id = f"ARIA-{uuid.uuid4().hex[:8].upper()}"
        return {
            "order_id": order_id,
            "material": quote_data["material"],
            "quantity": quantity,
            "dimensions": quote_data["dimensions"],
            "due_date": due_date.isoformat() if isinstance(due_date, datetime) else due_date,
            "priority": priority,
            "complexity": quote_data["complexity"],
            "source_part_id": quote_data["source_part_id"],
        }

    def bulk_catalog_to_orders(
        self,
        catalog_entries: List[Dict[str, Any]],
        default_quantity: int = 1,
        default_due_days: int = 14,
    ) -> List[Dict[str, Any]]:
        """Convert a list of catalog entries to order dicts, skipping errors."""
        orders = []
        for entry in catalog_entries:
            try:
                due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                    days=int(entry.get("due_days", default_due_days))
                )
                qty = int(entry.get("quantity", default_quantity))
                order = self.catalog_to_order(entry, quantity=qty, due_date=due)
                orders.append(order)
            except Exception as e:
                logger.warning("Skipping catalog entry %s: %s", entry.get("part_id", "?"), e)
        return orders

    def part_summary(self, catalog_entry: Dict[str, Any]) -> Dict[str, Any]:
        """Return a human-readable summary dict for display in the UI."""
        material_raw = catalog_entry.get("material", "unknown")
        try:
            material = self.map_material(material_raw)
            material_ok = True
        except ValueError:
            material = material_raw
            material_ok = False

        complexity = self.estimate_complexity(catalog_entry)
        machining_minutes = self.estimate_machining_minutes(catalog_entry)
        dimensions = self.catalog_to_dimensions(catalog_entry)

        primitives = catalog_entry.get("primitives_summary", [])
        feature_count = sum(int(p.get("count", 1)) for p in primitives)

        return {
            "part_id": catalog_entry.get("part_id") or catalog_entry.get("id") or "N/A",
            "material_raw": material_raw,
            "material_mapped": material,
            "material_valid": material_ok,
            "dimensions": dimensions,
            "volume_mm3": catalog_entry.get("volume_mm3"),
            "complexity": complexity,
            "estimated_machining_minutes": machining_minutes,
            "feature_count": feature_count,
            "primitive_types": [p.get("type") for p in primitives],
        }
