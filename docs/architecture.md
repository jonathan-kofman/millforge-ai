# MillForge System Architecture

## Overview

MillForge is a three-tier web application: a React SPA frontend, a Python/FastAPI backend, and modular AI agent modules. All tiers communicate via REST JSON APIs.

```
┌─────────────────────────────────────────────────────────────────┐
│                        Browser / Client                          │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐  │
│  │  QuoteForm   │ │ScheduleView  │ │VisionDemo│ │ Contact  │  │
│  └──────┬───────┘ └──────┬───────┘ └────┬─────┘ └────┬─────┘  │
│         └────────────────┴──────────────┴────────────┘          │
│                           React SPA (Vite + Tailwind)            │
└───────────────────────────────┬─────────────────────────────────┘
                                 │ HTTP/REST
                                 │
┌───────────────────────────────▼─────────────────────────────────┐
│                    FastAPI Backend (Python 3.12)                  │
│                                                                   │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────┐  ┌────────┐  │
│  │ /api/quote   │  │/api/schedule │  │/api/vision│  │/contact│  │
│  └──────┬───────┘  └──────┬───────┘  └────┬─────┘  └────────┘  │
│         │                  │               │                      │
│  ┌──────▼───────────────────▼───────────────▼─────────────────┐ │
│  │                    Agent Layer                               │ │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │ │
│  │  │  Scheduler   │  │QualityVision │  │EnergyOptimizer │   │ │
│  │  │   (EDD +     │  │  (mock CV,   │  │  (price-aware  │   │ │
│  │  │  setup times)│  │  → real YOLO)│  │   scheduling)  │   │ │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

### Frontend (`frontend/`)
- **React SPA** with Vite for fast HMR and Tailwind CSS for styling.
- Four views: Quote, Schedule Gantt, Vision Demo, Contact.
- Communicates with the backend exclusively via `/api/*` fetch calls.
- Vite dev-server proxies `/api` to `localhost:8000`, eliminating CORS issues during development.

### Backend (`backend/`)
- **FastAPI** handles all HTTP routing, validation (via Pydantic v2), and CORS.
- Each domain area has its own router module in `routers/`.
- Pydantic schemas in `models/schemas.py` enforce contract between API and callers.
- Business logic lives entirely in agent modules — routers are thin.

### Agent Layer (`backend/agents/`)
- **Scheduler**: The core POC component. Implements EDD with sequence-dependent setup times and parallel machine dispatch. Designed to be swapped with an ILP/genetic algorithm or LLM planner.
- **QualityVisionAgent**: Mock inspection engine. Interface is fixed; implementation swappable with an ONNX/YOLO model.
- **EnergyOptimizer**: Heuristic energy-cost estimator using simulated hourly pricing. Will integrate grid APIs.

## Data Flow – Quote Request

```
Browser                Backend               Scheduler Agent
  │                       │                        │
  │  POST /api/quote       │                        │
  │  {material, qty, ...}  │                        │
  ├──────────────────────► │                        │
  │                        │  estimate_lead_time()  │
  │                        ├───────────────────────►│
  │                        │  EDD optimize() on     │
  │                        │  queue + new order     │
  │                        │◄───────────────────────│
  │                        │  lead_time_hours        │
  │  QuoteResponse         │                        │
  │◄──────────────────────  │                        │
```

## Key Design Decisions

1. **Agents are plain Python classes** — no framework lock-in. They can be called from CLI, tests, Celery tasks, or HTTP routes without modification.
2. **Scheduler is deterministic given the same input** — enables reproducible tests.
3. **Mock data in `get_mock_orders()`** — the demo `/api/schedule/demo` endpoint uses this, so the frontend works without any user input.
4. **In-memory only for POC** — no database dependency. Adding Postgres requires only swapping the mock queue with a DB read.
