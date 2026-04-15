"""
MillForge Backend – FastAPI Application Entry Point
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

load_dotenv()

from routers import quote, schedule, vision, contact
from routers.auth_router import router as auth_router
from routers.orders import router as orders_router
from routers.inventory import router as inventory_router, _inventory
from routers.planner import router as planner_router
from routers.energy import router as energy_router
from routers.anomaly import router as anomaly_router
from routers.nl_schedule import router as nl_schedule_router
from routers.rework import router as rework_router
from routers.learning import router as learning_router
from routers.twin import router as twin_router
from routers.suppliers import router as suppliers_router
from routers.onboarding import router as onboarding_router
from routers.cad import router as cad_router
from routers.mtconnect import router as mtconnect_router
from routers.exceptions import router as exceptions_router
from routers.ws_machines import router as ws_machines_router, connection_manager as _ws_connection_manager
from routers.shift import router as shift_router
from routers.maintenance import router as maintenance_router
from routers.dashboard import router as dashboard_router
from discovery.routes import router as discovery_router
from routers.jobs import router as jobs_router
from routers.machines import router as machines_router, conflict_router as machines_conflict_router
from routers.analytics import router as analytics_router
from routers.business import router as business_router
from routers.billing import router as billing_router
from routers.market_quotes import router as market_quotes_router
from routers.contracts import router as contracts_router
from routers.manufacturing import router as manufacturing_router, set_registry as _set_mfg_registry
from routers.aria_bridge import router as aria_bridge_router
from routers.demo_chain import router as demo_chain_router
from routers.toolwear import router as toolwear_router
from routers.aria_scan import router as aria_scan_router
from routers.rfqs import router as rfqs_router
# Quality & Compliance modules
from routers.mtr import router as mtr_router
from routers.drawing import router as drawing_router
from routers.logbook import router as logbook_router
from routers.as9100 import router as as9100_router
from routers.inserts import router as inserts_router
from routers.presetter import router as presetter_router
from routers.operator import router as operator_router
from routers.notifications import router as notifications_router
from agents.machine_fleet import MachineFleet
from database import init_db, SessionLocal
from db_models import Supplier
from routers.vision import get_vision_model_name as _get_vision_model_name

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("millforge")

# ---------------------------------------------------------------------------
# Machine fleet (module-level singleton — routers import this)
# ---------------------------------------------------------------------------
machine_fleet: MachineFleet = MachineFleet(
    machine_count=int(os.getenv("MACHINE_COUNT", "3")),
    broadcast_fn=_ws_connection_manager.broadcast,
)


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MillForge backend starting up…")
    init_db()   # create tables if they don't exist
    logger.info("Database initialised.")
    await machine_fleet.start()
    logger.info("MachineFleet started (%d machines).", machine_fleet.machine_count)
    # Load inventory stock from DB (seed if empty)
    db = SessionLocal()
    try:
        _inventory._load_stock_from_db(db)
        logger.info("Inventory stock loaded from DB.")
    except Exception as exc:
        logger.warning("Inventory stock load failed: %s", exc)
    finally:
        db.close()
    # Auto-seed supplier directory if empty
    db = SessionLocal()
    try:
        count = db.query(Supplier).count()
        if count == 0:
            from scripts.seed_suppliers import seed_suppliers
            n = seed_suppliers(db)
            logger.info("Auto-seeded %d suppliers.", n)
        else:
            logger.info("Supplier table already populated (%d rows), skipping seed.", count)
    except Exception as exc:
        logger.warning("Supplier auto-seed failed: %s", exc)
    finally:
        db.close()
    logger.info(
        "Routers active: suppliers=%s energy=%s",
        suppliers_router.prefix,
        energy_router.prefix,
    )
    # Bootstrap manufacturing process registry
    db = SessionLocal()
    try:
        from manufacturing.bridge import bootstrap_registry, register_db_machines
        mfg_registry = bootstrap_registry()
        mfg_n = register_db_machines(mfg_registry, db)
        _set_mfg_registry(mfg_registry)
        logger.info("Manufacturing registry bootstrapped: %d DB machines registered.", mfg_n)
    except Exception as exc:
        logger.warning("Manufacturing registry bootstrap failed: %s", exc)
    finally:
        db.close()
    # Check ARIA schema compatibility — warns if ARIA is emitting a version
    # MillForge has no normalizer for (non-fatal, never blocks startup).
    from services.aria_schema import check_aria_compatibility
    await check_aria_compatibility()
    yield
    await machine_fleet.stop()
    logger.info("MillForge backend shutting down.")


# ---------------------------------------------------------------------------
# Rate limiter (applied to auth endpoints to prevent brute-force)
# ---------------------------------------------------------------------------
limiter = Limiter(key_func=get_remote_address)

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="MillForge API",
    description=(
        "Built by a founder who operates CNC mills every day. "
        "MillForge is the intelligence layer for lights-out American metal mills — "
        "removing human touchpoints from scheduling, quoting, quality triage, energy, and inventory. "
        "Jonathan Kofman machines parts daily at Northeastern's Advanced Manufacturing lab "
        "and built MillForge because he lives the scheduling problem himself."
    ),
    version="0.6.0",
    contact={"name": "Jonathan Kofman — MillForge"},
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
_cors_base = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:80"
).split(",")
_frontend_url = os.getenv("FRONTEND_URL", "").strip()
allowed_origins = [o.strip() for o in _cors_base if o.strip()]
# Always include the production Vercel URL explicitly — do not rely solely on env var
_PROD_FRONTEND = "https://millforge-ai.vercel.app"
if _PROD_FRONTEND not in allowed_origins:
    allowed_origins.append(_PROD_FRONTEND)
if _frontend_url and _frontend_url not in allowed_origins:
    allowed_origins.append(_frontend_url)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(auth_router)
app.include_router(orders_router)
app.include_router(quote.router)
app.include_router(schedule.router)
app.include_router(vision.router)
app.include_router(contact.router)
app.include_router(inventory_router)
app.include_router(planner_router,     include_in_schema=False)
app.include_router(energy_router)
app.include_router(anomaly_router,     include_in_schema=False)
app.include_router(nl_schedule_router)
app.include_router(rework_router)
app.include_router(learning_router)
app.include_router(twin_router)
app.include_router(suppliers_router)
app.include_router(onboarding_router)
app.include_router(cad_router)
app.include_router(mtconnect_router)
app.include_router(exceptions_router)
app.include_router(machines_conflict_router)
app.include_router(ws_machines_router)
app.include_router(shift_router)
app.include_router(maintenance_router)
app.include_router(dashboard_router)
app.include_router(discovery_router)
app.include_router(jobs_router)
app.include_router(machines_router)
app.include_router(analytics_router)
app.include_router(business_router)
app.include_router(billing_router)
app.include_router(market_quotes_router)
app.include_router(contracts_router)
app.include_router(manufacturing_router)
app.include_router(aria_bridge_router)
app.include_router(demo_chain_router)
app.include_router(toolwear_router)
app.include_router(aria_scan_router)
# Quality & Compliance modules
app.include_router(mtr_router)
app.include_router(drawing_router)
app.include_router(logbook_router)
app.include_router(as9100_router)
app.include_router(inserts_router)
app.include_router(presetter_router)
app.include_router(operator_router)
app.include_router(notifications_router)
app.include_router(rfqs_router)


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------

def _energy_status() -> str:
    """Return health label based on whether the EIA API is returning live data."""
    from agents.energy_optimizer import _rates_cache
    return (
        "real_grid_data"
        if _rates_cache.get("data_source") == "EIA_realtime"
        else "simulated_fallback"
    )


@app.get("/", tags=["Health"])
async def root():
    return {"service": "MillForge API", "status": "ok", "version": "0.6.0"}


@app.get("/api/health/pipeline-events", tags=["Health"])
async def pipeline_events(
    boundary: str = None,
    event_type: str = None,
    trace_id: str = None,
    job_id: str = None,
    limit: int = 100,
):
    """Query the pipeline observability event log.

    Returns JSONL events emitted at key boundaries:
    - aria→millforge: job submissions, circuit breaker trips
    - millforge→aria: feedback pushes
    """
    from services.pipeline_events import query_events
    events = query_events(
        boundary=boundary,
        event_type=event_type,
        trace_id=trace_id,
        job_id=job_id,
        limit=min(limit, 1000),
    )
    return {"count": len(events), "events": events}


@app.get("/health", tags=["Health"])
async def health():
    vision_model = _get_vision_model_name()
    quality_status = "mock" if vision_model == "heuristic" else "onnx_inference"

    touchpoints = {
        "scheduling":             "automated",
        "quoting":                "automated",
        "quality_inspection":     quality_status,    # "onnx_inference" when model downloaded, else "mock"
        "anomaly_detection":      "automated",        # critical anomalies auto-held before scheduling
        "energy_optimization":    _energy_status(),   # EIA API v2 when EIA_API_KEY set, else simulated
        "inventory_management":   "automated",
        "production_planning":    "real_data",        # US Census ASM throughput benchmarks
        "rework_dispatch":        "automated",
        "material_sourcing":      "directory_active", # supplier directory with geo-search
        "predictive_maintenance": "automated",        # MTBF/MTTR risk scoring, urgent → exception queue
        "exception_handling":     "automated",        # 5-source aggregator; urgent maintenance auto-surfaced
        "manufacturing_intelligence": "process_registry_active",
        "tool_wear_monitoring":   "automated",        # spectral drift + RUL prediction, tool changes between jobs
    }
    _AUTOMATED_STATUSES = {"automated", "real_grid_data", "real_data", "directory_active", "onnx_inference"}
    automated = sum(1 for v in touchpoints.values() if v in _AUTOMATED_STATUSES)
    total = len(touchpoints)

    data_sources = {
        "energy_pricing": (
            "EIA API v2 (PJM demand-based)"
            if _energy_status() == "real_grid_data"
            else "simulated_mock_curve"
        ),
        "carbon_intensity": (
            "Electricity Maps US-PJM live"
            if os.getenv("ELECTRICITY_MAPS_API_KEY")
            else "estimated_us_grid_average"
        ),
        "eia_api": (
            "real key"
            if os.getenv("EIA_API_KEY")
            else "DEMO_KEY (100 req/day)"
        ),
        "vision_model": (
            f"YOLOv8n ONNX ({vision_model})"
            if vision_model != "heuristic"
            else "heuristic mock — NEU-DET training pending"
        ),
        "supplier_directory": "verified US distributors",
        "anomaly_detection": "rule-based + Claude refinement",
    }

    # Pipeline connectivity probes (non-blocking — best effort)
    aria_url = os.getenv("MILLFORGE_API_URL") or os.getenv("ARIA_API_BASE", "")
    pipeline_status = {
        "aria_bridge_configured": bool(aria_url),
        "millforge_api_url": aria_url or "not configured",
        "circuit_state": "unknown",
        "recent_event_count": 0,
    }
    try:
        from services.pipeline_events import query_events
        recent_events = query_events(limit=50)
        pipeline_status["recent_event_count"] = len(recent_events)
        # Derive circuit state from most recent boundary event
        for ev in recent_events:
            if ev.get("boundary") == "aria→millforge":
                et = ev.get("event_type", "")
                if et == "circuit_open":
                    pipeline_status["circuit_state"] = "open"
                elif et in ("job_received", "submission_error"):
                    pipeline_status["circuit_state"] = (
                        "degraded" if et == "submission_error" else "closed"
                    )
                break
    except Exception:
        pass

    return {
        "status": "ok",
        "version": "0.6.0",
        "lights_out_readiness": touchpoints,
        "vision_model": vision_model,
        "automated_touchpoints": automated,
        "total_touchpoints": total,
        "readiness_percent": round(automated / total * 100),
        "data_sources": data_sources,
        "pipeline": pipeline_status,
    }
