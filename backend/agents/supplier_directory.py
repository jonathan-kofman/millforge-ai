"""
SupplierDirectory agent — search, filter, and geo-sort US materials suppliers.

No FastAPI imports. Pure Python business logic.
"""

import math
import logging
from typing import Optional

from sqlalchemy.orm import Session

from db_models import Supplier

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Material taxonomy
# ---------------------------------------------------------------------------

MATERIAL_CATEGORIES: dict[str, list[str]] = {
    "metals": [
        "steel", "aluminum", "titanium", "copper", "brass", "bronze",
        "stainless_steel", "carbon_steel", "tool_steel", "cast_iron",
        "nickel", "zinc", "lead", "tin", "chromium", "tungsten",
    ],
    "wood": [
        "oak", "maple", "pine", "plywood", "mdf", "particleboard",
        "walnut", "cherry", "birch", "hardwood", "softwood",
    ],
    "plastics": [
        "abs", "pla", "nylon", "polycarbonate", "acrylic", "hdpe",
        "ldpe", "pet", "pvc", "ptfe", "peek", "delrin", "ultem",
    ],
    "composites": [
        "carbon_fiber", "fiberglass", "kevlar", "graphite",
        "ceramic_matrix", "metal_matrix",
    ],
    "raw_materials": [
        "bar_stock", "sheet_metal", "tube", "pipe", "angle",
        "channel", "extrusion", "wire", "rod", "plate", "coil",
    ],
}

# Reverse map: material → category
_MAT_TO_CAT: dict[str, str] = {}
for _cat, _mats in MATERIAL_CATEGORIES.items():
    for _m in _mats:
        _MAT_TO_CAT[_m] = _cat

ALL_MATERIALS: list[str] = sorted(_MAT_TO_CAT.keys())


def _infer_categories(materials: list[str]) -> list[str]:
    cats = {_MAT_TO_CAT.get(m.lower(), "metals") for m in materials}
    return sorted(cats)


# ---------------------------------------------------------------------------
# Haversine
# ---------------------------------------------------------------------------

def haversine_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in miles between two (lat, lng) pairs."""
    R = 3958.8  # Earth radius in miles
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


# ---------------------------------------------------------------------------
# SupplierDirectory
# ---------------------------------------------------------------------------

class SupplierDirectory:
    """Agent for querying and managing the supplier database."""

    # ------------------------------------------------------------------ #
    # Search / list                                                        #
    # ------------------------------------------------------------------ #

    def search(
        self,
        db: Session,
        *,
        material: Optional[str] = None,
        category: Optional[str] = None,
        state: Optional[str] = None,
        verified_only: bool = False,
        skip: int = 0,
        limit: int = 50,
    ) -> tuple[list[Supplier], int]:
        """Return (suppliers, total_count) matching filters."""
        q = db.query(Supplier)

        if verified_only:
            q = q.filter(Supplier.verified.is_(True))

        if state:
            q = q.filter(Supplier.state.ilike(state))

        # JSON-column text search (SQLite compatible)
        if material:
            q = q.filter(Supplier.materials.contains(material.lower()))

        if category:
            q = q.filter(Supplier.categories.contains(category.lower()))

        total = q.count()
        suppliers = q.order_by(Supplier.name).offset(skip).limit(limit).all()
        return suppliers, total

    # ------------------------------------------------------------------ #
    # Single record                                                        #
    # ------------------------------------------------------------------ #

    def get_by_id(self, db: Session, supplier_id: int) -> Optional[Supplier]:
        return db.query(Supplier).filter(Supplier.id == supplier_id).first()

    # ------------------------------------------------------------------ #
    # Create                                                               #
    # ------------------------------------------------------------------ #

    def create(
        self,
        db: Session,
        *,
        name: str,
        city: str,
        state: str,
        address: Optional[str] = None,
        country: str = "US",
        lat: Optional[float] = None,
        lng: Optional[float] = None,
        materials: list[str] | None = None,
        categories: list[str] | None = None,
        phone: Optional[str] = None,
        website: Optional[str] = None,
        email: Optional[str] = None,
        verified: bool = False,
        data_source: str = "manual",
    ) -> Supplier:
        mats = [m.lower() for m in (materials or [])]
        cats = categories or _infer_categories(mats)
        row = Supplier(
            name=name,
            address=address,
            city=city,
            state=state,
            country=country,
            lat=lat,
            lng=lng,
            materials=mats,
            categories=cats,
            phone=phone,
            website=website,
            email=email,
            verified=verified,
            data_source=data_source,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        logger.info("Created supplier %s (id=%s)", name, row.id)
        return row

    # ------------------------------------------------------------------ #
    # Nearby                                                               #
    # ------------------------------------------------------------------ #

    def nearby(
        self,
        db: Session,
        *,
        lat: float,
        lng: float,
        radius_miles: float = 250.0,
        material: Optional[str] = None,
        limit: int = 20,
    ) -> list[tuple[Supplier, float]]:
        """Return [(supplier, distance_miles)] within radius, sorted by distance."""
        q = db.query(Supplier).filter(
            Supplier.lat.isnot(None),
            Supplier.lng.isnot(None),
        )
        if material:
            q = q.filter(Supplier.materials.contains(material.lower()))

        results = []
        for s in q.all():
            d = haversine_miles(lat, lng, s.lat, s.lng)
            if d <= radius_miles:
                results.append((s, round(d, 1)))

        results.sort(key=lambda x: x[1])
        return results[:limit]

    # ------------------------------------------------------------------ #
    # Stats                                                                #
    # ------------------------------------------------------------------ #

    def get_stats(self, db: Session) -> dict:
        """Return summary stats for landing page display."""
        all_suppliers = db.query(Supplier).all()
        verified = [s for s in all_suppliers if s.verified]
        states = {s.state for s in verified}
        return {
            "total_suppliers": len(all_suppliers),
            "verified_suppliers": len(verified),
            "states_covered": len(states),
            "state_list": sorted(states),
        }

    # ------------------------------------------------------------------ #
    # Materials / categories metadata                                       #
    # ------------------------------------------------------------------ #

    @staticmethod
    def list_materials() -> dict:
        return {
            "categories": MATERIAL_CATEGORIES,
            "all_materials": ALL_MATERIALS,
        }
