"""
/api/inventory endpoints — material stock management and purchase order generation.
"""

import logging
from fastapi import APIRouter, HTTPException

from models.schemas import (
    InventoryConsumeRequest,
    MaterialConsumptionResponse,
    InventoryStatusResponse,
    PurchaseOrderResponse,
    ReorderResponse,
)
from agents.inventory_agent import InventoryAgent

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/inventory", tags=["Inventory"])

_inventory = InventoryAgent()


@router.post(
    "/consume",
    response_model=MaterialConsumptionResponse,
    summary="Consume material stock from a scheduled production run",
)
async def consume_stock(req: InventoryConsumeRequest) -> MaterialConsumptionResponse:
    """
    Deduct material consumption from inventory based on a set of production orders.

    Consumption is calculated as: units × kg/unit for each material.
    """
    logger.info("Inventory consume: schedule_id=%s orders=%d", req.schedule_id, len(req.orders))
    try:
        result = _inventory.consume_from_schedule(req.orders, req.schedule_id)
    except Exception as e:
        logger.error("Inventory consume error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Inventory agent error")

    return MaterialConsumptionResponse(
        schedule_id=result.schedule_id,
        consumption_kg=result.consumption_kg,
        total_orders=result.total_orders,
        computed_at=result.computed_at,
    )


@router.get(
    "/status",
    response_model=InventoryStatusResponse,
    summary="Get current inventory levels",
)
async def get_inventory_status() -> InventoryStatusResponse:
    """Return current stock levels for all materials with reorder point flags."""
    status = _inventory.get_status()
    return InventoryStatusResponse(
        stock_kg=status.stock_kg,
        reorder_points=status.reorder_points,
        items_below_reorder=status.items_below_reorder,
        snapshot_at=status.snapshot_at,
    )


@router.post(
    "/reorder",
    response_model=ReorderResponse,
    summary="Check reorder points and generate purchase orders",
)
async def trigger_reorder() -> ReorderResponse:
    """
    Inspect all stock levels.  For each material at or below its reorder point,
    generate a purchase order and update the stock ledger.

    Returns the list of purchase orders generated (may be empty if all stock
    is above reorder points).
    """
    logger.info("Reorder check triggered")
    try:
        pos = _inventory.check_reorder_points()
    except Exception as e:
        logger.error("Reorder check error: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Inventory reorder error")

    return ReorderResponse(
        purchase_orders=[
            PurchaseOrderResponse(
                po_id=po.po_id,
                material=po.material,
                quantity_kg=po.quantity_kg,
                reason=po.reason,
                current_stock_kg=po.current_stock_kg,
                reorder_point_kg=po.reorder_point_kg,
                generated_at=po.generated_at,
            )
            for po in pos
        ],
        total_pos_generated=len(pos),
    )
