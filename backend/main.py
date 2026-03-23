"""
MillForge Backend – FastAPI Application Entry Point
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routers import quote, schedule, vision, contact
from routers.auth_router import router as auth_router
from routers.orders import router as orders_router
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
        "AI-powered production scheduling for software-defined metal mills. "
        "Compresses lead times from months to days."
    ),
    version="0.2.0",
    contact={"name": "MillForge Team"},
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------
allowed_origins = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://localhost:3000,http://localhost:80"
).split(",")

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


# ---------------------------------------------------------------------------
# Root / health
# ---------------------------------------------------------------------------
@app.get("/", tags=["Health"])
async def root():
    return {"service": "MillForge API", "status": "ok", "version": "0.2.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok"}
