"""
/api/suppliers endpoints — US materials supplier directory.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
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
