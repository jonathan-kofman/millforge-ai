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
from routers.inventory import router as inventory_router
from routers.planner import router as planner_router
from routers.energy import router as energy_router
from routers.anomaly import router as anomaly_router
from routers.nl_schedule import router as nl_schedule_router
from routers.rework import router as rework_router
from database import init_db

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
    version="0.2.0",
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


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------
@app.get("/", tags=["Health"])
async def root():
    return {"service": "MillForge API", "status": "ok", "version": "0.2.0"}


@app.get("/health", tags=["Health"])
async def health():
    touchpoints = {
        "scheduling":          "automated",
        "quoting":             "automated",
        "quality_inspection":  "pretrained",  # YOLOv8n ONNX placeholder
        "energy_optimization": "real_grid_data",  # PJM LMP + Electricity Maps carbon
        "inventory_management":"automated",
        "production_planning": "real_data",  # US Census ASM throughput benchmarks
        "rework_dispatch":     "automated",
    }
    automated = sum(1 for v in touchpoints.values() if v == "automated")
    total = len(touchpoints)
    return {
        "status": "ok",
        "version": "1.0.0",
        "lights_out_readiness": touchpoints,
        "automated_touchpoints": automated,
        "total_touchpoints": total,
        "readiness_percent": round(automated / total * 100),
    }
