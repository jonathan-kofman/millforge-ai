"""
Pydantic request/response schemas for the MillForge API.
"""

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum


class MaterialType(str, Enum):
    STEEL = "steel"
    ALUMINUM = "aluminum"
    TITANIUM = "titanium"
    COPPER = "copper"


# ---------------------------------------------------------------------------
# /api/quote
# ---------------------------------------------------------------------------

class QuoteRequest(BaseModel):
    material: MaterialType = Field(..., description="Material type to be processed")
    dimensions: str = Field(..., description="Part dimensions (LxWxH mm)")
    quantity: int = Field(..., gt=0, le=100_000, description="Number of units")
    due_date: Optional[datetime] = Field(None, description="Requested delivery date (ISO 8601). Defaults to 30 days from now.")
    priority: int = Field(5, ge=1, le=10, description="Order priority: 1=urgent, 10=low")

    model_config = {
        "json_schema_extra": {
            "example": {
                "material": "steel",
                "dimensions": "200x100x10mm",
                "quantity": 500,
                "priority": 3
            }
        }
    }


class QuoteResponse(BaseModel):
    quote_id: str
    material: str
    dimensions: str
    quantity: int
    estimated_lead_time_hours: float
    estimated_lead_time_days: float
    unit_price_usd: float
    total_price_usd: float
    currency: str = "USD"
    valid_until: datetime
    notes: str


# ---------------------------------------------------------------------------
# /api/schedule
# ---------------------------------------------------------------------------

class OrderInput(BaseModel):
    order_id: str = Field(..., description="Unique order identifier")
    material: MaterialType
    quantity: int = Field(..., gt=0)
    dimensions: str
    due_date: datetime
    priority: int = Field(5, ge=1, le=10)
    complexity: float = Field(1.0, ge=0.1, le=5.0, description="Processing complexity multiplier")

    model_config = {
        "json_schema_extra": {
            "example": {
                "order_id": "ORD-001",
                "material": "steel",
                "quantity": 500,
                "dimensions": "200x100x10mm",
                "due_date": "2025-06-01T08:00:00Z",
                "priority": 2
            }
        }
    }


class ScheduleRequest(BaseModel):
    orders: List[OrderInput] = Field(..., min_length=1, description="List of orders to schedule")
    start_time: Optional[datetime] = Field(None, description="Production start time. Defaults to now.")

    model_config = {
        "json_schema_extra": {
            "example": {
                "orders": [
                    {
                        "order_id": "ORD-001",
                        "material": "steel",
                        "quantity": 500,
                        "dimensions": "200x100x10mm",
                        "due_date": "2025-06-01T08:00:00Z",
                        "priority": 2
                    }
                ]
            }
        }
    }


class ScheduledOrderOutput(BaseModel):
    order_id: str
    machine_id: int
    material: str
    quantity: int
    setup_start: datetime
    processing_start: datetime
    completion_time: datetime
    setup_minutes: int
    processing_minutes: float
    on_time: bool
    lateness_hours: float
    due_date: datetime


class ScheduleSummary(BaseModel):
    total_orders: int
    on_time_count: int
    on_time_rate_percent: float
    makespan_hours: float
    utilization_percent: float


class ScheduleResponse(BaseModel):
    generated_at: datetime
    summary: ScheduleSummary
    algorithm: str = "edd"
    schedule: List[ScheduledOrderOutput]


# ---------------------------------------------------------------------------
# /api/schedule/benchmark
# ---------------------------------------------------------------------------

class BenchmarkEntry(BaseModel):
    algorithm: str
    on_time_rate_percent: float
    makespan_hours: float
    utilization_percent: float
    on_time_count: int
    total_orders: int
    solve_ms: float


class BenchmarkResponse(BaseModel):
    edd: BenchmarkEntry
    sa: BenchmarkEntry
    on_time_improvement_pp: float   # percentage-point improvement SA vs EDD
    winner: str                     # "edd" or "sa"


# ---------------------------------------------------------------------------
# /api/vision/inspect
# ---------------------------------------------------------------------------

class VisionInspectRequest(BaseModel):
    image_url: str = Field(..., description="URL or path of the part image to inspect")
    material: Optional[str] = Field(None, description="Material type for threshold calibration")
    order_id: Optional[str] = Field(None, description="Associated order ID for traceability")

    model_config = {
        "json_schema_extra": {
            "example": {
                "image_url": "https://example.com/part-image.jpg",
                "material": "steel",
                "order_id": "ORD-001"
            }
        }
    }


class VisionInspectResponse(BaseModel):
    image_url: str
    passed: bool
    confidence: float
    defects_detected: List[str]
    recommendation: str
    inspector_version: str
    order_id: Optional[str] = None


# ---------------------------------------------------------------------------
# /api/contact
# ---------------------------------------------------------------------------

class ContactRequest(BaseModel):
    name: str = Field(..., min_length=2)
    email: str = Field(..., description="Contact email address")
    company: Optional[str] = None
    message: str = Field(..., min_length=10)
    pilot_interest: bool = Field(False, description="Interested in pilot program")


class ContactResponse(BaseModel):
    success: bool
    message: str


# ---------------------------------------------------------------------------
# /api/auth
# ---------------------------------------------------------------------------

class RegisterRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=8, description="Password (min 8 chars)")
    name: str = Field(..., min_length=2)
    company: Optional[str] = None


class RegisterResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    name: str
    company: Optional[str] = None


# ---------------------------------------------------------------------------
# /api/orders
# ---------------------------------------------------------------------------

class OrderCreateRequest(BaseModel):
    material: MaterialType
    dimensions: str
    quantity: int = Field(..., gt=0)
    priority: int = Field(5, ge=1, le=10)
    complexity: float = Field(1.0, ge=0.1, le=5.0)
    due_date: Optional[datetime] = None   # defaults to +14 days
    notes: Optional[str] = None


class OrderUpdateRequest(BaseModel):
    priority: Optional[int] = Field(None, ge=1, le=10)
    due_date: Optional[datetime] = None
    status: Optional[str] = Field(None, description="pending|scheduled|in_progress|completed|cancelled")
    notes: Optional[str] = None


class OrderResponse(BaseModel):
    id: int
    order_id: str
    material: str
    dimensions: str
    quantity: int
    priority: int
    complexity: float
    due_date: datetime
    status: str
    notes: Optional[str] = None
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OrderListResponse(BaseModel):
    total: int
    orders: List[OrderResponse]


class OrderScheduleResponse(BaseModel):
    """Response from POST /api/orders/schedule — runs the scheduler on the user's pending orders."""
    schedule_run_id: int
    orders_scheduled: int
    algorithm: str
    generated_at: datetime
    summary: ScheduleSummary
    schedule: List[ScheduledOrderOutput]


# ---------------------------------------------------------------------------
# Generic error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None
