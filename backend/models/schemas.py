"""
Pydantic request/response schemas for the MillForge API.
"""

from pydantic import BaseModel, EmailStr, Field
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
    shifts_per_day: Optional[int] = Field(None, ge=1, le=3, description="Production shifts per day (1–3). Omit to assume 24h continuous operation.")
    hours_per_shift: Optional[int] = Field(None, ge=4, le=12, description="Hours per shift (4–12). Used with shifts_per_day to convert scheduled hours to calendar days.")

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
    carbon_footprint_kg_co2: Optional[float] = None


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
    battery_soc_percent: Optional[float] = Field(None, ge=0.0, le=100.0, description="Battery state of charge (0–100%). Influences energy scheduling recommendations.")

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
    validation_failures: List[str] = []
    warnings: List[str] = []
    energy_analysis: Optional["EnergyAnalysis"] = None
    held_orders: List[str] = []          # order_ids blocked by critical anomalies
    anomaly_report: Optional["AnomalyDetectResponse"] = None  # auto-scan results


# ---------------------------------------------------------------------------
# /api/schedule/benchmark
# ---------------------------------------------------------------------------

class BenchmarkEntry(BaseModel):
    algorithm: str
    on_time_rate_percent: float
    avg_lateness_hours: float
    makespan_hours: float
    utilization_percent: float
    on_time_count: int
    total_orders: int
    solve_ms: float


class BenchmarkResponse(BaseModel):
    fifo: BenchmarkEntry            # naive baseline: first-in first-out, no optimization
    edd: BenchmarkEntry             # MillForge EDD: greedy earliest-due-date
    sa: BenchmarkEntry              # MillForge SA: simulated annealing optimizer
    on_time_improvement_pp: float   # percentage-point improvement SA vs FIFO (the MillForge delta)
    winner: str                     # "edd" or "sa"
    order_count: int
    machine_count: int
    dataset_description: str
    pressure: float = 0.5


# ---------------------------------------------------------------------------
# /api/schedule/backtest
# ---------------------------------------------------------------------------

class HistoricalOrderInput(BaseModel):
    """One historical order with the shop's actual recorded completion time."""
    order_id: str
    material: MaterialType
    quantity: int = Field(..., gt=0)
    dimensions: str
    due_date: datetime
    priority: int = Field(5, ge=1, le=10)
    complexity: float = Field(1.0, ge=0.1, le=5.0)
    actual_completion: datetime  # what the shop actually recorded


class BacktestActuals(BaseModel):
    """Metrics derived purely from the shop's real historical completion data."""
    on_time_count: int
    on_time_rate_percent: float
    avg_lateness_hours: float


class BacktestOrderDetail(BaseModel):
    """Per-order comparison of actual outcome vs SA projection."""
    order_id: str
    due_date: datetime
    actual_completion: datetime
    actual_on_time: bool
    actual_lateness_hours: float
    sa_on_time: Optional[bool]          # None if order was not scheduled by SA
    sa_lateness_hours: Optional[float]
    rescued: bool                       # True when actual=late AND sa=on_time


class BacktestImpact(BaseModel):
    """Concrete impact metrics — more actionable than percentage-point deltas."""
    # Volume
    orders_rescued: int                     # late in reality → SA delivers on time
    orders_lost: int                        # on-time in reality → SA misses (should be 0)
    # Time saved
    total_lateness_hours_saved: float       # sum of (actual_lateness - sa_lateness) across all orders
    avg_lateness_reduction_hours: float     # per-order average
    # Throughput
    makespan_delta_hours: float             # actual wall-clock batch time − SA makespan (>0 = SA faster)
    # Cost (only present when penalty_per_late_order_usd is supplied)
    estimated_penalty_usd: Optional[float]


class BacktestRequest(BaseModel):
    orders: List[HistoricalOrderInput] = Field(..., min_length=1)
    start_time: Optional[datetime] = Field(
        None,
        description=(
            "Production start time for algorithm projections. "
            "Defaults to the earliest due_date minus median processing time."
        ),
    )
    label: Optional[str] = Field("Historical backtest", description="Human-readable name for this dataset")
    penalty_per_late_order_usd: Optional[float] = Field(
        None,
        ge=0.0,
        description="Optional per-order late penalty in USD. When provided, impact.estimated_penalty_usd shows annual savings.",
    )


class BacktestResponse(BaseModel):
    label: str
    order_count: int
    machine_count: int
    start_time: datetime
    actual: BacktestActuals             # real historical performance
    fifo: BenchmarkEntry                # what naive FIFO would have done
    edd: BenchmarkEntry                 # what MillForge EDD would have done
    sa: BenchmarkEntry                  # what MillForge SA would have done
    sa_vs_actual_pp: float              # SA improvement over actual baseline (pp)
    fifo_vs_actual_pp: float            # FIFO vs actual (model validation)
    impact: BacktestImpact              # concrete impact metrics beyond pp
    orders: List[BacktestOrderDetail]   # per-order actual vs SA comparison


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
    defect_severities: Dict[str, str] = {}  # defect_name → critical|major|minor
    recommendation: str
    inspector_version: str
    model: Optional[str] = None            # "yolov8n-neu-det", "yolov8n-pretrained", or "heuristic"
    model_map50: Optional[float] = None    # published mAP@0.5 accuracy; None for heuristic
    order_id: Optional[str] = None
    inspection_mode: str = "heuristic"     # "onnx" when real model is loaded, else "heuristic"


# ---------------------------------------------------------------------------
# /api/contact
# ---------------------------------------------------------------------------

class ContactRequest(BaseModel):
    name: str = Field(..., min_length=2)
    email: EmailStr = Field(..., description="Contact email address")
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
    email: EmailStr = Field(..., description="User email address")
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
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: int
    email: str
    name: str
    company: Optional[str] = None


class MeResponse(BaseModel):
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
# /api/orders/schedule-history
# ---------------------------------------------------------------------------

class ScheduleHistoryItem(BaseModel):
    id: int
    algorithm: str
    order_ids: List[str]
    summary: Dict[str, Any]
    on_time_rate: float
    makespan_hours: float
    created_at: datetime

    model_config = {"from_attributes": True}


class ScheduleHistoryResponse(BaseModel):
    total: int
    runs: List[ScheduleHistoryItem]


# ---------------------------------------------------------------------------
# /api/orders/from-cad
# ---------------------------------------------------------------------------

class CadParseResponse(BaseModel):
    dimensions: str = Field(..., description="Bounding box dimensions e.g. '45.2x32.1x18.7mm'")
    complexity: int = Field(..., ge=1, le=10, description="Complexity score derived from triangle count")
    estimated_volume_cm3: float = Field(..., description="Bounding box volume proxy in cm³")
    triangle_count: int = Field(..., description="Total triangles in the STL mesh")
    source: str = Field("stl_upload", description="Data source identifier")


# ---------------------------------------------------------------------------
# /api/inventory
# ---------------------------------------------------------------------------

class InventoryConsumeRequest(BaseModel):
    schedule_id: str = Field("manual", description="Identifier for the schedule run")
    orders: List[Dict[str, Any]] = Field(
        ..., description="List of scheduled orders with material and quantity fields"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "schedule_id": "SCHED-001",
                "orders": [
                    {"material": "steel", "quantity": 500},
                    {"material": "aluminum", "quantity": 200},
                ],
            }
        }
    }


class MaterialConsumptionResponse(BaseModel):
    schedule_id: str
    consumption_kg: Dict[str, float]
    total_orders: int
    computed_at: datetime
    validation_failures: List[str] = []


class InventoryStatusResponse(BaseModel):
    stock_kg: Dict[str, float]
    reorder_points: Dict[str, float]
    items_below_reorder: List[str]
    snapshot_at: datetime
    validation_failures: List[str] = []


class PurchaseOrderResponse(BaseModel):
    po_id: str
    material: str
    quantity_kg: float
    reason: str
    current_stock_kg: float
    reorder_point_kg: float
    generated_at: datetime


class ReorderResponse(BaseModel):
    purchase_orders: List[PurchaseOrderResponse]
    total_pos_generated: int
    validation_failures: List[str] = []


# ---------------------------------------------------------------------------
# /api/planner
# ---------------------------------------------------------------------------

class DailyPlanItem(BaseModel):
    day: str
    material: str
    units: int
    machine_hours: float


class WeeklyPlanRequest(BaseModel):
    demand_signal: str = Field(
        ...,
        description="Natural language demand forecast (e.g. 'Rush 500 titanium parts for aerospace')",
    )
    capacity: Dict[str, float] = Field(
        ...,
        description="Available machine hours per material for the week",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "demand_signal": "Rush 500 titanium parts for aerospace, plus routine steel and aluminum",
                "capacity": {"steel": 40.0, "aluminum": 30.0, "titanium": 20.0, "copper": 10.0},
            }
        }
    }


class WeeklyPlanResponse(BaseModel):
    week_start: str
    total_units_planned: int
    daily_plans: List[DailyPlanItem]
    capacity_utilization_percent: float
    bottlenecks: List[str]
    recommendations: List[str]
    validation_failures: List[str] = []
    data_source: str = "internal_benchmarks"


# ---------------------------------------------------------------------------
# /api/energy
# ---------------------------------------------------------------------------

class EnergyEstimateRequest(BaseModel):
    start_time: datetime
    duration_hours: float = Field(..., gt=0)
    material: MaterialType


class EnergyEstimateResponse(BaseModel):
    start_time: datetime
    end_time: datetime
    material: str
    estimated_kwh: float
    estimated_cost_usd: float
    peak_rate: float
    off_peak_rate: float
    recommendation: str
    data_source: str = "simulated_fallback"
    validation_failures: List[str] = []


class EnergyAnalysis(BaseModel):
    total_energy_kwh: float
    current_schedule_cost_usd: float
    optimal_schedule_cost_usd: float
    potential_savings_usd: float
    carbon_footprint_kg_co2: float
    carbon_delta_kg_co2: float
    battery_recommendation: Optional[str] = None
    data_source: str = "simulated_fallback"


class NegativePricingWindow(BaseModel):
    hour: int
    rate_usd_per_mwh: float
    duration_hours: int = 1


class NegativePricingResponse(BaseModel):
    windows: List[NegativePricingWindow]
    total_windows: int
    max_credit_usd_per_mwh: float
    recommendation: str
    data_source: str = "simulated_fallback"


class ArbitrageRequest(BaseModel):
    daily_energy_kwh: float = Field(..., gt=0, description="Daily mill energy consumption in kWh")
    flexible_load_percent: float = Field(0.3, ge=0.0, le=1.0, description="Fraction of load that can be shifted")


class ArbitrageResponse(BaseModel):
    daily_savings_usd: float
    annual_savings_usd: float
    peak_rate_usd_per_kwh: float
    off_peak_rate_usd_per_kwh: float
    optimal_shift_hours: List[int]
    recommendation: str
    data_source: str = "simulated_fallback"


class ScenarioType(str, Enum):
    SOLAR = "solar"
    BATTERY = "battery"
    SOLAR_BATTERY = "solar_battery"
    WIND = "wind"
    SMR = "smr"
    GRID_ONLY = "grid_only"


class ScenarioRequest(BaseModel):
    scenario: ScenarioType = Field(..., description="On-site generation scenario to model")
    annual_energy_kwh: float = Field(..., gt=0, description="Annual mill energy consumption in kWh")
    capex_usd: Optional[float] = Field(None, gt=0, description="Override default capex estimate")

    model_config = {
        "json_schema_extra": {
            "example": {
                "scenario": "solar",
                "annual_energy_kwh": 500000
            }
        }
    }


class ScenarioResponse(BaseModel):
    scenario: str
    capex_usd: float
    lcoe_usd_per_kwh: float
    annual_savings_usd: float
    npv_10yr_usd: float
    payback_years: Optional[float] = None
    recommendation: str
    data_source: str = "lazard_lcoe_v17_2024"


# ---------------------------------------------------------------------------
# /api/schedule/nl
# ---------------------------------------------------------------------------

class NLScheduleRequest(BaseModel):
    instruction: str = Field(
        ...,
        description="Plain-English scheduling override (e.g. 'rush the titanium orders')",
    )
    orders: List[Dict[str, Any]] = Field(
        ..., description="Order list to apply overrides to, then schedule"
    )


class NLAutoScheduleRequest(BaseModel):
    instruction: str = Field(
        ...,
        description=(
            "Plain-English scheduling override applied to your pending orders. "
            "e.g. 'Rush all titanium orders' or 'Defer low-priority steel to end of queue'."
        ),
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "instruction": "Rush all titanium orders — aerospace deadline moved up",
            }
        }
    }

    model_config = {
        "json_schema_extra": {
            "example": {
                "instruction": "Rush all titanium orders — aerospace deadline moved up",
                "orders": [
                    {
                        "order_id": "ORD-001",
                        "material": "titanium",
                        "quantity": 50,
                        "dimensions": "300x200x15mm",
                        "due_date": "2025-06-01T08:00:00Z",
                        "priority": 5,
                        "complexity": 1.5,
                    }
                ],
            }
        }
    }


class PriorityOverrideItem(BaseModel):
    order_id: str
    new_priority: int
    reason: str


class NLScheduleResponse(BaseModel):
    instruction: str
    overrides_applied: List[PriorityOverrideItem]
    override_summary: str
    schedule: "ScheduleResponse"
    validation_failures: List[str] = []


# ---------------------------------------------------------------------------
# /api/anomaly
# ---------------------------------------------------------------------------

class AnomalyDetectRequest(BaseModel):
    orders: List[Dict[str, Any]] = Field(
        ..., description="List of order dicts to analyse for anomalies"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "orders": [
                    {
                        "order_id": "ORD-001",
                        "material": "steel",
                        "quantity": 500,
                        "due_date": "2025-06-01T08:00:00Z",
                        "priority": 2,
                        "complexity": 1.0,
                    }
                ]
            }
        }
    }


class AnomalyItem(BaseModel):
    order_id: str
    anomaly_type: str
    severity: str
    description: str


class AnomalyDetectResponse(BaseModel):
    orders_analysed: int
    anomalies: List[AnomalyItem]
    summary: str
    analysed_at: datetime
    validation_failures: List[str] = []


# ---------------------------------------------------------------------------
# /api/schedule/rework
# ---------------------------------------------------------------------------

class ReworkItem(BaseModel):
    order_id: str = Field(..., description="Original order ID to rework")
    material: MaterialType
    quantity: int = Field(..., gt=0)
    defect_severity: str = Field(..., description="critical|major|minor")
    dimensions: str = Field("100x100x10mm", description="Part dimensions")
    due_date: Optional[datetime] = Field(
        None,
        description="Rework deadline. Defaults: critical=24h, major=48h, minor=72h from now.",
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "order_id": "ORD-001",
                "material": "steel",
                "quantity": 50,
                "defect_severity": "critical",
                "dimensions": "200x100x10mm",
            }
        }
    }


class ReworkRequest(BaseModel):
    items: List[ReworkItem] = Field(..., min_length=1)

    model_config = {
        "json_schema_extra": {
            "example": {
                "items": [
                    {
                        "order_id": "ORD-001",
                        "material": "steel",
                        "quantity": 50,
                        "defect_severity": "critical",
                        "dimensions": "200x100x10mm",
                    }
                ]
            }
        }
    }


class ReworkScheduleResponse(BaseModel):
    rework_orders_count: int
    complexity_boosts: Dict[str, float]  # rework order_id → complexity multiplier
    schedule: ScheduleResponse


# ---------------------------------------------------------------------------
# /api/suppliers
# ---------------------------------------------------------------------------

class SupplierCreate(BaseModel):
    name: str = Field(..., min_length=2)
    city: str = Field(..., min_length=2)
    state: str = Field(..., min_length=2, max_length=50)
    address: Optional[str] = None
    country: str = "US"
    lat: Optional[float] = Field(None, ge=-90.0, le=90.0)
    lng: Optional[float] = Field(None, ge=-180.0, le=180.0)
    materials: List[str] = Field(default_factory=list)
    categories: List[str] = Field(default_factory=list)
    phone: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    verified: bool = False
    data_source: str = "user_submitted"


class SupplierResponse(BaseModel):
    id: int
    name: str
    city: str
    state: str
    address: Optional[str] = None
    country: str
    lat: Optional[float] = None
    lng: Optional[float] = None
    materials: List[str]
    categories: List[str]
    phone: Optional[str] = None
    website: Optional[str] = None
    email: Optional[str] = None
    verified: bool
    data_source: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SupplierSearchResult(SupplierResponse):
    distance_miles: Optional[float] = None


class SupplierListResponse(BaseModel):
    total: int
    suppliers: List[SupplierResponse]


class SupplierNearbyResponse(BaseModel):
    lat: float
    lng: float
    radius_miles: float
    results: List[SupplierSearchResult]
    total: int


class SupplierStatsResponse(BaseModel):
    total_suppliers: int
    verified_suppliers: int
    states_covered: int
    state_list: List[str]


class SupplierMaterialsResponse(BaseModel):
    categories: Dict[str, List[str]]
    all_materials: List[str]


# ---------------------------------------------------------------------------
# /api/orders/import-csv
# ---------------------------------------------------------------------------

class CsvRowPreview(BaseModel):
    row_number: int
    order_id: Optional[str] = None
    material: str
    quantity: int
    due_date: datetime
    dimensions: str
    priority: int
    complexity: float


class CsvRowError(BaseModel):
    row_number: int
    raw_data: Dict[str, str]
    error: str


class CsvImportPreviewResponse(BaseModel):
    preview_token: str
    total_rows: int
    valid_count: int
    error_count: int
    column_mapping: Dict[str, str]
    valid_rows: List[CsvRowPreview]
    error_rows: List[CsvRowError]


class CsvImportConfirmRequest(BaseModel):
    preview_token: str


class CsvImportConfirmResponse(BaseModel):
    imported_count: int
    order_ids: List[str]
    skipped_count: int


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# /api/onboarding
# ---------------------------------------------------------------------------

class ShopConfigRequest(BaseModel):
    shop_name: Optional[str] = None
    machine_count: Optional[int] = Field(None, ge=1, le=500)
    materials: Optional[List[str]] = None
    setup_times: Optional[Dict[str, Any]] = None
    baseline_otd: Optional[float] = Field(None, ge=0.0, le=100.0)
    scheduling_method: Optional[str] = None
    weekly_order_volume: Optional[int] = Field(None, ge=0)
    shifts_per_day: Optional[int] = Field(None, ge=1, le=3)
    hours_per_shift: Optional[int] = Field(None, ge=4, le=12)
    wizard_step: int = Field(0, ge=0, le=3)


class ShopConfigResponse(BaseModel):
    id: int
    user_id: int
    shop_name: Optional[str] = None
    machine_count: Optional[int] = None
    materials: List[str] = []
    setup_times: Dict[str, Any] = {}
    baseline_otd: Optional[float] = None
    scheduling_method: Optional[str] = None
    weekly_order_volume: Optional[int] = None
    shifts_per_day: int = 2
    hours_per_shift: int = 8
    wizard_step: int
    is_complete: bool
    created_at: datetime
    updated_at: datetime


class OnboardingStatusResponse(BaseModel):
    configured: bool
    is_complete: bool
    wizard_step: int
    config: Optional[ShopConfigResponse] = None


# Generic error response
# ---------------------------------------------------------------------------

class ErrorResponse(BaseModel):
    detail: str
    error_code: Optional[str] = None


# ---------------------------------------------------------------------------
# /api/jobs — ARIA CAM import, machine-aware scheduling, QC inspection
# ---------------------------------------------------------------------------

class CAMTool(BaseModel):
    tool_number: int
    description: str
    diameter_mm: Optional[float] = None
    material: Optional[str] = None


class StockDimensions(BaseModel):
    length_mm: float
    width_mm: float
    height_mm: float


class CAMImport(BaseModel):
    """ARIA-OS setup sheet v1.0 — consumed by POST /api/jobs/import-from-cam."""
    schema_version: str = Field("1.0", description="ARIA CAM setup sheet schema version")
    part_id: str = Field(..., description="ARIA part identifier")
    machine_name: str = Field(..., description="Target CNC machine name from ARIA")
    tools: List[CAMTool] = Field(default_factory=list)
    stock_dims: StockDimensions
    cycle_time_min_estimate: float = Field(..., gt=0)
    second_op_required: bool = False
    work_offset_recommendation: str = ""
    fixturing_suggestion: str = ""
    generated_at: str = Field(..., description="ISO timestamp when ARIA generated the setup sheet")
    material: Optional[str] = None
    notes: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "schema_version": "1.0",
                "part_id": "ARIA-P-20240101-001",
                "machine_name": "Haas VF-2",
                "tools": [{"tool_number": 1, "description": "3/8 End Mill", "diameter_mm": 9.5}],
                "stock_dims": {"length_mm": 120.0, "width_mm": 60.0, "height_mm": 25.0},
                "cycle_time_min_estimate": 42.5,
                "second_op_required": False,
                "work_offset_recommendation": "G54",
                "fixturing_suggestion": "Kurt vise, jaw width 60mm",
                "generated_at": "2024-01-01T08:00:00",
                "material": "aluminum"
            }
        }
    }


class JobResponse(BaseModel):
    id: int
    title: str
    stage: str
    source: str
    material: Optional[str] = None
    required_machine_type: Optional[str] = None
    estimated_duration_minutes: Optional[float] = None
    notes: Optional[str] = None
    cam_metadata: Optional[Dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobPatch(BaseModel):
    stage: Optional[str] = None
    notes: Optional[str] = None
    required_machine_type: Optional[str] = None


class JobListResponse(BaseModel):
    total: int
    jobs: List[JobResponse]


class MachineCreate(BaseModel):
    name: str = Field(..., min_length=1)
    machine_type: str = Field(..., min_length=1, description="e.g. 'VMC', 'Lathe', 'EDM'")
    is_available: bool = True
    notes: Optional[str] = None

    model_config = {
        "json_schema_extra": {
            "example": {"name": "Haas VF-2", "machine_type": "VMC", "is_available": True}
        }
    }


class MachineResponse(BaseModel):
    id: int
    name: str
    machine_type: str
    is_available: bool
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class MachineConflictResponse(BaseModel):
    conflict: bool
    message: str
    required_machine_type: str
    available_machines: List[MachineResponse]


class QCResultResponse(BaseModel):
    id: int
    job_id: int
    defects_found: List[str]
    confidence_scores: List[float]
    passed: bool
    image_path: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QCAnalyticsItem(BaseModel):
    dimension: str
    value: str
    total_inspections: int
    passed: int
    failed: int
    pass_rate_percent: float
    top_defects: List[str]


class QCAnalyticsResponse(BaseModel):
    total_inspections: int
    overall_pass_rate_percent: float
    by_machine_type: List[QCAnalyticsItem]
    by_material: List[QCAnalyticsItem]
    generated_at: datetime
