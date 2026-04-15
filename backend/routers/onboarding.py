"""
/api/onboarding — Shop configuration wizard + activation milestone tracking.

Two layers:
  - Wizard endpoints (existing): collect shop profile in 1-3 steps
  - Milestone endpoints (new): track 5-step activation checklist + shop templates
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from db_models import (
    User, ShopConfig, WorkCenter, Operator, Job, ScheduleRun, OrderRecord,
    QCResult, ShopFloorEvent,
)
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
        shifts_per_day=cfg.shifts_per_day,
        hours_per_shift=cfg.hours_per_shift,
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
    if req.shifts_per_day is not None:
        cfg.shifts_per_day = req.shifts_per_day
    if req.hours_per_shift is not None:
        cfg.hours_per_shift = req.hours_per_shift
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


# =========================================================================== #
# Activation milestones + shop templates (feature #32)                          #
# =========================================================================== #

# 5 milestones the new shop owner needs to hit before they're "activated".
# Each milestone is a function(db, user) -> bool computed on demand. Order
# matters — the dashboard renders them sequentially.
MILESTONE_DEFS: list[dict[str, Any]] = [
    {
        "key": "machines_added",
        "label": "Add at least one machine / work center",
        "hint": "Define the equipment in your shop so the scheduler knows your real capacity.",
        "cta": "/dashboard/work-centers/new",
    },
    {
        "key": "first_job",
        "label": "Create or import your first job",
        "hint": "Add an order from a CAD upload, ARIA bridge, or manual entry.",
        "cta": "/dashboard/jobs/new",
    },
    {
        "key": "first_schedule",
        "label": "Run your first schedule",
        "hint": "Hit the schedule button — see the SA optimizer pick the best sequence.",
        "cta": "/dashboard/schedule",
    },
    {
        "key": "operator_login",
        "label": "Add an operator and log them in",
        "hint": "Create at least one operator with a PIN so the tablet interface works.",
        "cta": "/dashboard/operators/new",
    },
    {
        "key": "first_insight",
        "label": "Generate your first quality / DFM insight",
        "hint": "Run a QC inspection or DFM analysis to start collecting feedback.",
        "cta": "/dashboard/quality",
    },
]


# Pre-canned shop templates the operator can apply instead of clicking
# through the wizard. Each template seeds machine_count + materials +
# scheduling_method + shifts, and the apply-template endpoint creates a
# matching ShopConfig + initial WorkCenter rows.
SHOP_TEMPLATES: dict[str, dict[str, Any]] = {
    "cnc_job_shop": {
        "label": "CNC Job Shop",
        "description": "Mid-volume precision parts. CNC mills + lathes, mostly metals, ~5-15 machines.",
        "shop_config": {
            "machine_count": 8,
            "materials": ["steel", "aluminum", "stainless_steel", "titanium"],
            "scheduling_method": "sa",
            "shifts_per_day": 2,
            "hours_per_shift": 8,
            "weekly_order_volume": 60,
            "baseline_otd": 0.78,
        },
        "work_centers": [
            {"name": "VMC-01", "category": "cnc_mill",  "hourly_rate": 95.0},
            {"name": "VMC-02", "category": "cnc_mill",  "hourly_rate": 95.0},
            {"name": "HMC-01", "category": "cnc_mill",  "hourly_rate": 110.0},
            {"name": "Lathe-01", "category": "cnc_lathe", "hourly_rate": 85.0},
            {"name": "Lathe-02", "category": "cnc_lathe", "hourly_rate": 85.0},
            {"name": "Inspection", "category": "inspection_station", "hourly_rate": 60.0},
        ],
    },
    "mixed": {
        "label": "Mixed Manufacturing",
        "description": "CNC + sheet metal + welding + finishing. Generalist shop, ~10-25 machines.",
        "shop_config": {
            "machine_count": 14,
            "materials": ["steel", "aluminum", "stainless_steel", "carbon_steel"],
            "scheduling_method": "sa",
            "shifts_per_day": 2,
            "hours_per_shift": 9,
            "weekly_order_volume": 90,
            "baseline_otd": 0.72,
        },
        "work_centers": [
            {"name": "VMC-01", "category": "cnc_mill",       "hourly_rate": 95.0},
            {"name": "VMC-02", "category": "cnc_mill",       "hourly_rate": 95.0},
            {"name": "Lathe-01", "category": "cnc_lathe",    "hourly_rate": 85.0},
            {"name": "Laser-01", "category": "laser_cutter", "hourly_rate": 120.0},
            {"name": "Brake-01", "category": "press_brake",  "hourly_rate": 80.0},
            {"name": "TIG-01",   "category": "tig_welder",   "hourly_rate": 75.0},
            {"name": "Powder-01","category": "powder_coat_booth", "hourly_rate": 65.0},
            {"name": "Inspection", "category": "inspection_station", "hourly_rate": 60.0},
        ],
    },
    "fab_shop": {
        "label": "Sheet Metal / Fab Shop",
        "description": "Laser, brake, weld, finish. Sheet-metal-first workflow, ~6-15 machines.",
        "shop_config": {
            "machine_count": 9,
            "materials": ["carbon_steel", "stainless_steel", "aluminum"],
            "scheduling_method": "sa",
            "shifts_per_day": 2,
            "hours_per_shift": 9,
            "weekly_order_volume": 75,
            "baseline_otd": 0.74,
        },
        "work_centers": [
            {"name": "Laser-01", "category": "laser_cutter", "hourly_rate": 120.0},
            {"name": "Laser-02", "category": "laser_cutter", "hourly_rate": 120.0},
            {"name": "Brake-01", "category": "press_brake",  "hourly_rate": 80.0},
            {"name": "Brake-02", "category": "press_brake",  "hourly_rate": 80.0},
            {"name": "TIG-01",   "category": "tig_welder",   "hourly_rate": 75.0},
            {"name": "MIG-01",   "category": "mig_welder",   "hourly_rate": 70.0},
            {"name": "Powder-01","category": "powder_coat_booth", "hourly_rate": 65.0},
            {"name": "Inspection", "category": "inspection_station", "hourly_rate": 60.0},
        ],
    },
    "print_farm": {
        "label": "3D Print Farm",
        "description": "FDM/SLA/SLS printers in parallel. Low-mix, lights-out friendly.",
        "shop_config": {
            "machine_count": 20,
            "materials": ["pla", "abs", "petg", "nylon"],
            "scheduling_method": "sa",
            "shifts_per_day": 3,
            "hours_per_shift": 8,
            "weekly_order_volume": 200,
            "baseline_otd": 0.85,
        },
        "work_centers": [
            {"name": f"FDM-{i:02d}", "category": "additive_fdm", "hourly_rate": 18.0}
            for i in range(1, 13)
        ] + [
            {"name": "SLA-01", "category": "additive_sla", "hourly_rate": 28.0},
            {"name": "SLS-01", "category": "additive_sls", "hourly_rate": 45.0},
            {"name": "Post",   "category": "inspection_station", "hourly_rate": 35.0},
        ],
    },
}


class ApplyTemplateRequest(BaseModel):
    template_key: str = Field(..., description="One of: cnc_job_shop | mixed | fab_shop | print_farm")
    overwrite_existing: bool = Field(False, description="If true, replaces existing ShopConfig + WorkCenters; otherwise 409 if any exist")


def _milestone_states(db: Session, user: User) -> dict[str, bool]:
    """Compute current pass/fail for each of the 5 activation milestones."""
    user_id = user.id
    return {
        "machines_added": db.query(WorkCenter).filter(WorkCenter.user_id == user_id).count() > 0,
        "first_job": (
            db.query(Job).filter(Job.created_by_id == user_id).count() > 0
            or db.query(OrderRecord).filter(OrderRecord.created_by_id == user_id).count() > 0
        ),
        "first_schedule": db.query(ScheduleRun).filter(ScheduleRun.created_by_id == user_id).count() > 0,
        "operator_login": db.query(Operator).filter(Operator.user_id == user_id).count() > 0,
        "first_insight": (
            db.query(QCResult).join(Job, QCResult.job_id == Job.id)
            .filter(Job.created_by_id == user_id).count() > 0
        ),
    }


@router.get("/milestones", summary="5-step activation checklist with current pass/fail state")
async def get_milestones(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Returns the 5 activation milestones with current state. The frontend
    renders these as a sticky checklist for new shops; once all 5 are
    complete the checklist auto-dismisses.
    """
    states = _milestone_states(db, user)
    items = []
    for m in MILESTONE_DEFS:
        items.append({
            **m,
            "completed": states.get(m["key"], False),
        })
    completed_count = sum(1 for i in items if i["completed"])
    return {
        "user_id": user.id,
        "completed": completed_count,
        "total": len(items),
        "percent": round(completed_count / len(items) * 100, 1),
        "all_done": completed_count == len(items),
        "milestones": items,
        "generated_at": datetime.now(timezone.utc),
    }


@router.get("/templates", summary="List available shop templates")
async def list_templates():
    """
    Returns the catalog of pre-canned shop templates. The frontend shows
    these as 'Quick Start' tiles on first login so the operator can skip
    the wizard if their shop matches a template.
    """
    return {
        "templates": [
            {
                "key": k,
                "label": t["label"],
                "description": t["description"],
                "shop_config_preview": t["shop_config"],
                "work_center_count": len(t["work_centers"]),
            }
            for k, t in SHOP_TEMPLATES.items()
        ],
    }


@router.post("/apply-template", summary="Apply a shop template — seeds ShopConfig + WorkCenters")
async def apply_template(
    req: ApplyTemplateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Apply a pre-canned shop template for the authenticated user. Creates a
    ShopConfig (if missing) populated from the template + initial WorkCenter
    rows for each machine. Idempotent only when overwrite_existing=true,
    otherwise refuses if a ShopConfig already exists for the user.
    """
    template = SHOP_TEMPLATES.get(req.template_key)
    if template is None:
        raise HTTPException(status_code=400, detail=f"unknown template_key '{req.template_key}'")

    existing_cfg = db.query(ShopConfig).filter(ShopConfig.user_id == user.id).first()
    existing_wcs = db.query(WorkCenter).filter(WorkCenter.user_id == user.id).count()

    if (existing_cfg or existing_wcs) and not req.overwrite_existing:
        raise HTTPException(
            status_code=409,
            detail="Shop already has config or work centers. Pass overwrite_existing=true to replace.",
        )

    if req.overwrite_existing and existing_wcs:
        db.query(WorkCenter).filter(WorkCenter.user_id == user.id).delete()

    sc = template["shop_config"]
    if existing_cfg:
        cfg = existing_cfg
    else:
        cfg = ShopConfig(user_id=user.id)
        db.add(cfg)
    cfg.machine_count = sc["machine_count"]
    cfg.materials_json = json.dumps(sc["materials"])
    cfg.scheduling_method = sc.get("scheduling_method", "sa")
    cfg.shifts_per_day = sc.get("shifts_per_day", 2)
    cfg.hours_per_shift = sc.get("hours_per_shift", 8)
    cfg.weekly_order_volume = sc.get("weekly_order_volume")
    cfg.baseline_otd = sc.get("baseline_otd")
    cfg.wizard_step = 3  # template apply == fully configured

    created_wcs: list[int] = []
    for wc in template["work_centers"]:
        row = WorkCenter(
            user_id=user.id,
            name=wc["name"],
            category=wc["category"],
            status="available",
            hourly_rate=wc.get("hourly_rate"),
            setup_time_default_min=wc.get("setup_time_default_min", 30),
        )
        db.add(row)
        db.flush()
        created_wcs.append(row.id)

    db.commit()

    # Fire a product analytics event so the founder dashboard sees activations
    try:
        from routers.analytics import record_event
        record_event(
            db,
            user_id=user.id,
            event_category="onboarding",
            event_type="template_applied",
            payload={
                "template_key": req.template_key,
                "work_centers_created": len(created_wcs),
                "machine_count": cfg.machine_count,
            },
        )
    except Exception:
        pass

    return {
        "template_key": req.template_key,
        "shop_config_id": cfg.id,
        "work_centers_created": len(created_wcs),
        "work_center_ids": created_wcs,
        "wizard_step": cfg.wizard_step,
    }
