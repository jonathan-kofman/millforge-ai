"""
MillForge Inventory Agent

Tracks raw-material stock levels, calculates consumption from production
schedules, and generates purchase orders when stock hits reorder points.
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Material constants
# ---------------------------------------------------------------------------

# Average kg of raw stock consumed per unit produced, by material
KG_PER_UNIT: Dict[str, float] = {
    "steel":    2.5,
    "aluminum": 0.8,
    "titanium": 1.2,
    "copper":   1.5,
}

# Initial stock levels (kg) — represents warehouse inventory at startup
INITIAL_STOCK: Dict[str, float] = {
    "steel":    5_000.0,
    "aluminum": 3_000.0,
    "titanium": 1_000.0,
    "copper":   2_000.0,
}

# Reorder point: when stock falls at or below this level a PO is generated
REORDER_POINTS: Dict[str, float] = {
    "steel":    1_000.0,
    "aluminum":   600.0,
    "titanium":   200.0,
    "copper":     400.0,
}

# Standard reorder quantity (kg per PO)
REORDER_QTY: Dict[str, float] = {
    "steel":    3_000.0,
    "aluminum": 2_000.0,
    "titanium":   500.0,
    "copper":   1_000.0,
}


# ---------------------------------------------------------------------------
# Domain objects
# ---------------------------------------------------------------------------

@dataclass
class MaterialConsumption:
    """Aggregated material usage extracted from a schedule."""
    schedule_id: str
    consumption_kg: Dict[str, float]
    total_orders: int
    computed_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    validation_failures: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "schedule_id": self.schedule_id,
            "consumption_kg": {k: round(v, 2) for k, v in self.consumption_kg.items()},
            "total_orders": self.total_orders,
            "computed_at": self.computed_at.isoformat(),
        }


@dataclass
class PurchaseOrder:
    """A generated purchase order for a material."""
    po_id: str
    material: str
    quantity_kg: float
    reason: str
    current_stock_kg: float
    reorder_point_kg: float
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    def to_dict(self) -> dict:
        return {
            "po_id": self.po_id,
            "material": self.material,
            "quantity_kg": round(self.quantity_kg, 2),
            "reason": self.reason,
            "current_stock_kg": round(self.current_stock_kg, 2),
            "reorder_point_kg": self.reorder_point_kg,
            "generated_at": self.generated_at.isoformat(),
        }


@dataclass
class InventoryStatus:
    """Current snapshot of all material stock levels."""
    stock_kg: Dict[str, float]
    reorder_points: Dict[str, float]
    items_below_reorder: List[str]
    snapshot_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    validation_failures: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "stock_kg": {k: round(v, 2) for k, v in self.stock_kg.items()},
            "reorder_points": self.reorder_points,
            "items_below_reorder": self.items_below_reorder,
            "snapshot_at": self.snapshot_at.isoformat(),
            "validation_failures": self.validation_failures,
        }


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class InventoryAgent:
    """
    Inventory Agent.

    Maintains an in-memory stock ledger (cache) backed by the DB.
    Consume stock via ``consume_from_schedule()``; check current levels via ``get_status()``;
    generate purchase orders via ``check_reorder_points()``.

    The DB (InventoryStock table) is the source of truth; the in-memory dict is a cache
    that persists for the lifetime of the agent instance or until saved back to DB.

    Validation loop: each method validates its own output and retries up to
    MAX_RETRIES times before returning a result with populated
    ``validation_failures``.
    """

    MAX_RETRIES = 3

    def __init__(
        self,
        initial_stock: Optional[Dict[str, float]] = None,
        db_factory: Optional[Callable] = None,
    ):
        self._stock: Dict[str, float] = dict(initial_stock or INITIAL_STOCK)
        self._po_counter = 0
        self._db_factory = db_factory
        self._lock = threading.Lock()
        logger.info("InventoryAgent initialized: %s", self._stock)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _load_stock_from_db(self, db) -> None:
        """
        Load all InventoryStock rows from the DB into self._stock.
        If DB is empty, seed from INITIAL_STOCK and save back.
        """
        try:
            from db_models import InventoryStock
            rows = db.query(InventoryStock).all()
            if rows:
                self._stock = {row.material: row.quantity_kg for row in rows}
                logger.info("Loaded stock from DB: %s", self._stock)
            else:
                logger.info("DB is empty, seeding from INITIAL_STOCK")
                for material, qty in INITIAL_STOCK.items():
                    self._save_stock_to_db(db, material, qty)
                self._stock = dict(INITIAL_STOCK)
        except Exception as e:
            logger.warning("Failed to load stock from DB: %s. Using in-memory cache.", e)

    def _save_stock_to_db(self, db, material: str, qty: float) -> None:
        """
        Upsert a single material stock level in the DB.
        Called after any mutation to self._stock[material].
        """
        try:
            from db_models import InventoryStock
            row = db.query(InventoryStock).filter_by(material=material).first()
            if row:
                row.quantity_kg = qty
            else:
                row = InventoryStock(material=material, quantity_kg=qty)
                db.add(row)
            db.commit()
            logger.debug("Saved %s stock to DB: %.2f kg", material, qty)
        except Exception as e:
            logger.warning("Failed to save %s stock to DB: %s", material, e)

    def consume_from_schedule(
        self,
        schedule_orders: List[dict],
        schedule_id: str = "unknown",
        db=None,
    ) -> MaterialConsumption:
        """
        Deduct material consumption from stock based on a list of scheduled orders.

        Args:
            schedule_orders: List of dicts with at least {material, quantity}.
            schedule_id: Identifier for the schedule run (for traceability).
            db: Optional SQLAlchemy session to persist stock changes to DB.

        Returns:
            MaterialConsumption with a breakdown of usage per material.
        """
        spec = {"schedule_orders": schedule_orders, "schedule_id": schedule_id}
        failures: List[str] = []
        best: Optional[MaterialConsumption] = None

        for attempt in range(self.MAX_RETRIES):
            with self._lock:
                result = self._do_consume(schedule_orders, schedule_id)
            errors = self._validate_consumption(result, spec)

            if not errors:
                result.validation_failures = []
                # Persist stock changes to DB if session provided
                if db:
                    for material in result.consumption_kg.keys():
                        if material in self._stock:
                            self._save_stock_to_db(db, material, self._stock[material])
                return result

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = result
            logger.warning("Inventory consume validation failed attempt %d: %s", attempt + 1, errors)

        assert best is not None
        best.validation_failures = failures
        return best

    def get_status(self) -> InventoryStatus:
        """Return current stock levels and flag items below reorder points."""
        below = [
            mat
            for mat, qty in self._stock.items()
            if qty <= REORDER_POINTS.get(mat, 0)
        ]
        return InventoryStatus(
            stock_kg=dict(self._stock),
            reorder_points=dict(REORDER_POINTS),
            items_below_reorder=below,
        )

    def check_reorder_points(self, db=None) -> List[PurchaseOrder]:
        """
        Inspect all stock levels and generate POs for anything at or below
        its reorder point.

        Args:
            db: Optional SQLAlchemy session to persist stock changes to DB.

        Returns:
            List of PurchaseOrder objects (may be empty).
        """
        spec: dict = {}
        failures: List[str] = []
        best: Optional[List[PurchaseOrder]] = None

        for attempt in range(self.MAX_RETRIES):
            with self._lock:
                pos = self._do_reorder()
            errors = self._validate_pos(pos, spec)

            if not errors:
                # Persist stock changes to DB if session provided
                if db:
                    for material in self._stock.keys():
                        self._save_stock_to_db(db, material, self._stock[material])
                return pos

            labeled = [f"[attempt {attempt + 1}] {e}" for e in errors]
            failures.extend(labeled)
            best = pos
            logger.warning("PO validation failed attempt %d: %s", attempt + 1, errors)

        return best or []

    # ------------------------------------------------------------------
    # Spec + validation
    # ------------------------------------------------------------------

    def _validate_consumption(
        self, result: MaterialConsumption, spec: dict
    ) -> List[str]:
        errors: List[str] = []
        orders = spec.get("schedule_orders", [])

        if result.total_orders != len(orders):
            errors.append(
                f"total_orders mismatch: expected {len(orders)}, got {result.total_orders}"
            )
        for mat, kg in result.consumption_kg.items():
            if kg < 0:
                errors.append(f"negative consumption for {mat}: {kg} kg")
        return errors

    def _validate_pos(
        self, pos: List[PurchaseOrder], spec: dict
    ) -> List[str]:
        errors: List[str] = []
        for po in pos:
            if po.quantity_kg <= 0:
                errors.append(f"PO {po.po_id} has non-positive quantity: {po.quantity_kg}")
            if po.current_stock_kg < 0:
                errors.append(f"PO {po.po_id} has negative stock level: {po.current_stock_kg}")
        return errors

    # ------------------------------------------------------------------
    # Core implementation
    # ------------------------------------------------------------------

    def _do_consume(
        self,
        schedule_orders: List[dict],
        schedule_id: str,
    ) -> MaterialConsumption:
        consumption: Dict[str, float] = {}
        for order in schedule_orders:
            mat = str(order.get("material", "")).lower()
            qty = int(order.get("quantity", 0))
            kg = qty * KG_PER_UNIT.get(mat, 1.0)
            consumption[mat] = consumption.get(mat, 0.0) + kg
            if mat in self._stock:
                self._stock[mat] = max(0.0, self._stock[mat] - kg)
            else:
                self._stock[mat] = 0.0

        logger.info(
            "Consumed from schedule %s: %s",
            schedule_id,
            {k: round(v, 1) for k, v in consumption.items()},
        )
        return MaterialConsumption(
            schedule_id=schedule_id,
            consumption_kg=consumption,
            total_orders=len(schedule_orders),
        )

    def _do_reorder(self) -> List[PurchaseOrder]:
        pos: List[PurchaseOrder] = []
        for mat, qty in self._stock.items():
            reorder_point = REORDER_POINTS.get(mat, 0.0)
            if qty <= reorder_point:
                self._po_counter += 1
                po_qty = REORDER_QTY.get(mat, 1000.0)
                self._stock[mat] = self._stock[mat] + po_qty
                po = PurchaseOrder(
                    po_id=f"PO-{self._po_counter:05d}",
                    material=mat,
                    quantity_kg=po_qty,
                    reason=(
                        f"Stock {qty:.0f} kg ≤ reorder point {reorder_point:.0f} kg"
                    ),
                    current_stock_kg=qty,
                    reorder_point_kg=reorder_point,
                )
                pos.append(po)
                logger.info("Generated %s: %s %.0f kg", po.po_id, mat, po_qty)
        return pos
