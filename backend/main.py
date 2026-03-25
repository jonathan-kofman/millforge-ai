"""
MillForge Backend – FastAPI Application Entry Point
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from database import init_db, SessionLocal
from db_models import Supplier
from agents.quality_vision import MODEL_AVAILABLE as VISION_MODEL_AVAILABLE

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("millforge")


# ---------------------------------------------------------------------------
# Lifespan (startup / shutdown hooks)
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MillForge backend starting up…")
    init_db()   # create tables if they don't exist
    logger.info("Database initialised.")
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
    yield
    logger.info("MillForge backend shutting down.")


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
    version="0.4.0",
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
app.include_router(nl_schedule_router, include_in_schema=False)
app.include_router(rework_router)
app.include_router(learning_router)
app.include_router(twin_router)
app.include_router(suppliers_router)
app.include_router(onboarding_router)


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------

def _energy_status() -> str:
    """Return health label based on whether gridstatus is installed."""
    try:
        import gridstatus  # noqa: F401
        return "real_grid_data"
    except ImportError:
        return "simulated_fallback"


@app.get("/", tags=["Health"])
async def root():
    return {"service": "MillForge API", "status": "ok", "version": "0.4.0"}


@app.get("/health", tags=["Health"])
async def health():
    touchpoints = {
        "scheduling":          "automated",
        "quoting":             "automated",
        "quality_inspection":  "mock",         # heuristic hash — no model file deployed
        "energy_optimization": _energy_status(),  # PJM LMP when gridstatus available, else simulated
        "inventory_management":"automated",
        "production_planning": "real_data",  # US Census ASM throughput benchmarks
        "rework_dispatch":     "automated",
        "material_sourcing":   "directory_active",  # supplier directory with geo-search
    }
    _AUTOMATED_STATUSES = {"automated", "real_grid_data", "real_data", "directory_active"}
    automated = sum(1 for v in touchpoints.values() if v in _AUTOMATED_STATUSES)
    total = len(touchpoints)

    data_sources = {
        "energy_pricing": (
            "PJM real-time LMP via gridstatus"
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
            "NEU-DET YOLOv8n ONNX"
            if VISION_MODEL_AVAILABLE
            else "heuristic mock — NEU-DET training pending"
        ),
        "supplier_directory": "verified US distributors",
    }

    return {
        "status": "ok",
        "version": "0.4.0",
        "lights_out_readiness": touchpoints,
        "vision_model_trained": VISION_MODEL_AVAILABLE,
        "automated_touchpoints": automated,
        "total_touchpoints": total,
        "readiness_percent": round(automated / total * 100),
        "data_sources": data_sources,
    }
