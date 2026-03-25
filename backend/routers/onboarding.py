"""
/api/onboarding — Shop configuration wizard endpoints.

Allows authenticated users to save their shop profile in up to 3 steps.
The wizard drives the frontend onboarding flow shown to new users with no orders.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from db_models import User, ShopConfig
from auth.dependencies import get_current_user
from models.schemas import (
    ShopConfigRequest, ShopConfigResponse, OnboardingStatusResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/onboarding", tags=["Onboarding"])


def _to_response(cfg: ShopConfig) -> ShopConfigResponse:
    return ShopConfigResponse(
        id=cfg.id,
        user_id=cfg.user_id,
        shop_name=cfg.shop_name,
        machine_count=cfg.machine_count,
        materials=cfg.materials,
        setup_times=cfg.setup_times,
        baseline_otd=cfg.baseline_otd,
        scheduling_method=cfg.scheduling_method,
        weekly_order_volume=cfg.weekly_order_volume,
        wizard_step=cfg.wizard_step,
        is_complete=cfg.is_complete,
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


@router.get("/status", response_model=OnboardingStatusResponse, summary="Onboarding completion status")
async def get_onboarding_status(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> OnboardingStatusResponse:
    """Return whether the authenticated user has completed the onboarding wizard."""
    cfg = db.query(ShopConfig).filter(ShopConfig.user_id == user.id).first()
    if cfg is None:
        return OnboardingStatusResponse(configured=False, is_complete=False, wizard_step=0, config=None)
    return OnboardingStatusResponse(
        configured=True,
        is_complete=cfg.is_complete,
        wizard_step=cfg.wizard_step,
        config=_to_response(cfg),
    )


@router.put(
    "/shop-config",
    response_model=ShopConfigResponse,
    status_code=status.HTTP_200_OK,
    summary="Save or update shop configuration",
)
async def upsert_shop_config(
    req: ShopConfigRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ShopConfigResponse:
    """
    Create or update the shop configuration for the authenticated user.
    Idempotent — safe to call multiple times as the wizard advances steps.
    """
    cfg = db.query(ShopConfig).filter(ShopConfig.user_id == user.id).first()
    if cfg is None:
        cfg = ShopConfig(user_id=user.id)
        db.add(cfg)

    if req.shop_name is not None:
        cfg.shop_name = req.shop_name
    if req.machine_count is not None:
        cfg.machine_count = req.machine_count
    if req.materials is not None:
        cfg.materials_json = json.dumps(req.materials)
    if req.setup_times is not None:
        cfg.setup_times_json = json.dumps(req.setup_times)
    if req.baseline_otd is not None:
        cfg.baseline_otd = req.baseline_otd
    if req.scheduling_method is not None:
        cfg.scheduling_method = req.scheduling_method
    if req.weekly_order_volume is not None:
        cfg.weekly_order_volume = req.weekly_order_volume
    # wizard_step advances but never regresses
    if req.wizard_step > (cfg.wizard_step or 0):
        cfg.wizard_step = req.wizard_step

    db.commit()
    db.refresh(cfg)
    logger.info(f"ShopConfig upserted: user={user.email} step={cfg.wizard_step}")
    return _to_response(cfg)


@router.get("/shop-config", response_model=ShopConfigResponse, summary="Fetch shop configuration")
async def get_shop_config(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ShopConfigResponse:
    """Return the authenticated user's shop configuration, or 404 if not yet configured."""
    cfg = db.query(ShopConfig).filter(ShopConfig.user_id == user.id).first()
    if cfg is None:
        raise HTTPException(status_code=404, detail="Shop config not found — complete the onboarding wizard")
    return _to_response(cfg)
