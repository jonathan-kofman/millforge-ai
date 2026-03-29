"""
MillForge Contracts Router

Exposes ContractGenerator as HTTP endpoints:
  GET  /api/contracts/sla/{tier}
  POST /api/contracts/msa
  POST /api/contracts/order-form
  POST /api/contracts/pilot
"""

from datetime import date
from fastapi import APIRouter, HTTPException

from agents.contract_generator import ContractGenerator
from models.schemas import (
    MSARequest,
    OrderFormRequest,
    PilotRequest,
    ContractResponse,
)

router = APIRouter(prefix="/api/contracts", tags=["Contracts"])
_generator = ContractGenerator()


@router.get("/sla/{tier}", response_model=ContractResponse)
def get_sla_schedule(tier: str):
    """
    Return the SLA schedule Markdown for a given pricing tier.
    Valid tiers: starter, growth, enterprise, custom.
    """
    result = _generator.generate_sla(tier)
    return ContractResponse(
        document_type=result["document_type"],
        content_markdown=result["content_markdown"],
        generated_at=result["generated_at"],
        tier=result["tier"],
    )


@router.post("/msa", response_model=ContractResponse)
def generate_msa(req: MSARequest):
    """
    Generate a Master Service Agreement for a customer.
    Returns the document as Markdown.
    """
    effective_date = None
    if req.effective_date:
        try:
            effective_date = date.fromisoformat(req.effective_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="effective_date must be YYYY-MM-DD")

    result = _generator.generate_msa(
        customer_name=req.customer_name,
        customer_address=req.customer_address,
        effective_date=effective_date,
        governing_state=req.governing_state,
    )
    return ContractResponse(
        document_type=result["document_type"],
        content_markdown=result["content_markdown"],
        generated_at=result["generated_at"],
        customer_name=result["customer_name"],
    )


@router.post("/order-form", response_model=ContractResponse)
def generate_order_form(req: OrderFormRequest):
    """
    Generate a signed order form / pricing schedule.
    """
    start_date = None
    if req.start_date:
        try:
            start_date = date.fromisoformat(req.start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")

    result = _generator.generate_order_form(
        customer_name=req.customer_name,
        tier=req.tier,
        machine_count=req.machine_count,
        billing_cycle=req.billing_cycle,
        start_date=start_date,
        add_ons=req.add_ons,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return ContractResponse(
        document_type=result["document_type"],
        content_markdown=result["content_markdown"],
        generated_at=result["generated_at"],
        customer_name=result["customer_name"],
        tier=result["tier"],
    )


@router.post("/pilot", response_model=ContractResponse)
def generate_pilot_agreement(req: PilotRequest):
    """
    Generate a short-form pilot agreement (30-day default, no charge).
    """
    start_date = None
    if req.start_date:
        try:
            start_date = date.fromisoformat(req.start_date)
        except ValueError:
            raise HTTPException(status_code=400, detail="start_date must be YYYY-MM-DD")

    result = _generator.generate_pilot_agreement(
        customer_name=req.customer_name,
        pilot_days=req.pilot_days,
        tier=req.tier,
        start_date=start_date,
    )
    return ContractResponse(
        document_type=result["document_type"],
        content_markdown=result["content_markdown"],
        generated_at=result["generated_at"],
        customer_name=result["customer_name"],
        tier=result["tier"],
    )
