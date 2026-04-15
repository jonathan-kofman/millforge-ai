"""
/api/suppliers endpoints — US materials supplier directory.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user
from database import get_db
from db_models import User
from models.schemas import (
    SupplierCreate,
    SupplierListResponse,
    SupplierMaterialsResponse,
    SupplierNearbyResponse,
    SupplierResponse,
    SupplierSearchResult,
    SupplierStatsResponse,
)
from agents.supplier_directory import SupplierDirectory

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/suppliers", tags=["Suppliers"])

_directory = SupplierDirectory()


@router.get(
    "",
    response_model=SupplierListResponse,
    summary="List and search suppliers",
)
async def list_suppliers(
    name: Optional[str] = Query(None, description="Filter by supplier name (partial match)"),
    material: Optional[str] = Query(None, description="Filter by material (e.g. steel, aluminum)"),
    category: Optional[str] = Query(None, description="Filter by category (metals, plastics, composites, wood, raw_materials)"),
    state: Optional[str] = Query(None, description="Filter by US state abbreviation (e.g. OH, PA)"),
    verified_only: bool = Query(False, description="Only return verified suppliers"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> SupplierListResponse:
    suppliers, total = _directory.search(
        db,
        name=name,
        material=material,
        category=category,
        state=state,
        verified_only=verified_only,
        skip=skip,
        limit=limit,
    )
    return SupplierListResponse(
        total=total,
        suppliers=[SupplierResponse.model_validate(s) for s in suppliers],
    )


@router.get(
    "/stats",
    response_model=SupplierStatsResponse,
    summary="Supplier directory stats (verified count, states covered)",
)
async def supplier_stats(db: Session = Depends(get_db)) -> SupplierStatsResponse:
    stats = _directory.get_stats(db)
    return SupplierStatsResponse(**stats)


@router.get(
    "/materials",
    response_model=SupplierMaterialsResponse,
    summary="List all supported material categories and materials",
)
async def list_materials() -> SupplierMaterialsResponse:
    data = SupplierDirectory.list_materials()
    return SupplierMaterialsResponse(**data)


@router.get(
    "/nearby",
    response_model=SupplierNearbyResponse,
    summary="Find suppliers within radius of a coordinate",
)
async def nearby_suppliers(
    lat: float = Query(..., ge=-90.0, le=90.0, description="Latitude of your facility"),
    lng: float = Query(..., ge=-180.0, le=180.0, description="Longitude of your facility"),
    radius_miles: float = Query(250.0, gt=0, le=2000, description="Search radius in miles"),
    material: Optional[str] = Query(None, description="Filter by material"),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> SupplierNearbyResponse:
    results = _directory.nearby(
        db, lat=lat, lng=lng, radius_miles=radius_miles, material=material, limit=limit
    )
    return SupplierNearbyResponse(
        lat=lat,
        lng=lng,
        radius_miles=radius_miles,
        results=[
            SupplierSearchResult(**SupplierResponse.model_validate(s).model_dump(), distance_miles=d)
            for s, d in results
        ],
        total=len(results),
    )


@router.get(
    "/recommend",
    summary="Recommend suppliers for a work-center capability the shop lacks",
)
async def recommend_suppliers(
    capability: str = Query(..., description="Work center category needed (e.g. 'anodizing_line', 'powder_coat_booth', 'heat_treat_oven', 'plating')"),
    lat: Optional[float] = Query(None, ge=-90.0, le=90.0, description="Shop latitude — when provided, results are distance-ranked"),
    lng: Optional[float] = Query(None, ge=-180.0, le=180.0, description="Shop longitude — when provided, results are distance-ranked"),
    radius_miles: float = Query(500.0, gt=0, le=3000, description="Max search radius in miles"),
    material: Optional[str] = Query(None, description="Optional material filter (steel, aluminum, etc.)"),
    limit: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
) -> dict:
    """
    Auto-suggest subcontractors for ops the shop can't run in-house.

    Maps `capability` (a work-center category from the operations array)
    to material categories + keyword scores against the supplier directory,
    and returns the top-N matches with a confidence score.

    Use this when an Operation has `is_subcontracted=True` or when the
    scheduler detects that a required `work_center_category` has no
    matching active WorkCenter in the user's shop.
    """
    results = _directory.recommend_for_capability(
        db,
        capability=capability,
        lat=lat,
        lng=lng,
        radius_miles=radius_miles,
        material=material,
        limit=limit,
    )
    return {
        "capability": capability,
        "lat": lat,
        "lng": lng,
        "radius_miles": radius_miles,
        "material": material,
        "result_count": len(results),
        "recommendations": [
            {
                **SupplierResponse.model_validate(s).model_dump(),
                "distance_miles": dist,
                "confidence": conf,
            }
            for s, dist, conf in results
        ],
    }


@router.get(
    "/{supplier_id}",
    response_model=SupplierResponse,
    summary="Get a single supplier by ID",
)
async def get_supplier(supplier_id: int, db: Session = Depends(get_db)) -> SupplierResponse:
    supplier = _directory.get_by_id(db, supplier_id)
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    return SupplierResponse.model_validate(supplier)


@router.post(
    "/seed",
    summary="Manually trigger supplier seed (idempotent — requires auth)",
)
async def seed_endpoint(
    db: Session = Depends(get_db),
    _user: User = Depends(get_current_user),
):
    from db_models import Supplier as SupplierModel
    from scripts.seed_suppliers import seed_suppliers
    count = db.query(SupplierModel).count()
    if count > 0:
        return {"status": "already_seeded", "count": count}
    n = seed_suppliers(db)
    return {"status": "seeded", "count": n}


@router.post(
    "",
    response_model=SupplierResponse,
    status_code=201,
    summary="Submit a new supplier",
)
async def create_supplier(
    req: SupplierCreate,
    db: Session = Depends(get_db),
) -> SupplierResponse:
    logger.info("Supplier submission: %s (%s, %s)", req.name, req.city, req.state)
    supplier = _directory.create(
        db,
        name=req.name,
        city=req.city,
        state=req.state,
        address=req.address,
        country=req.country,
        lat=req.lat,
        lng=req.lng,
        materials=req.materials,
        categories=req.categories or None,
        phone=req.phone,
        website=req.website,
        email=req.email,
        verified=req.verified,
        data_source=req.data_source,
    )
    return SupplierResponse.model_validate(supplier)
