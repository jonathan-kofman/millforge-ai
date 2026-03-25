"""
CAD upload router — POST /api/orders/from-cad

Accepts an STL file, extracts order parameters, and returns a draft
order payload ready for the scheduling pipeline.

This is the ARIA-OS integration bridge: ARIA CAD output → STL upload →
auto-populated MillForge draft order.
"""

from fastapi import APIRouter, File, UploadFile, HTTPException
from models.schemas import CadParseResponse
from agents.cad_parser import extract_from_stl

router = APIRouter(prefix="/api/orders", tags=["cad"])


@router.post("/from-cad", response_model=CadParseResponse, summary="Parse STL and extract order parameters")
async def upload_stl(file: UploadFile = File(..., description="STL file (binary or ASCII)")):
    """
    Upload an STL file and receive extracted order parameters:
    dimensions, complexity score, estimated volume, and triangle count.

    The returned payload maps directly to `OrderCreateRequest` fields —
    pass it to `POST /api/orders` to create a draft order.
    """
    if not file.filename or not file.filename.lower().endswith(".stl"):
        raise HTTPException(status_code=400, detail="Only .stl files are accepted")

    file_bytes = await file.read()
    if len(file_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        result = extract_from_stl(file_bytes)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Failed to parse STL: {exc}")

    return CadParseResponse(**result)
