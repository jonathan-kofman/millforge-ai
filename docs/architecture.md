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

## Database Layer

MillForge uses **SQLAlchemy 2.0** with **SQLite** for development (PostgreSQL-ready).

### ORM Models (`backend/db_models.py`)

| Model | Key fields |
|-------|-----------|
| `User` | `id`, `email` (unique), `hashed_password` (Argon2id), `name`, `created_at` |
| `OrderRecord` | `order_id` (UUID-based), `material`, `dimensions`, `quantity`, `priority`, `complexity`, `due_date`, `status`, `created_by_id` FK |
| `ScheduleRun` | `algorithm`, `order_ids_json`, `summary_json`, `on_time_rate`, `makespan_hours`, `created_by_id` FK |
| `InspectionRecord` | `order_record_id` FK (nullable), `image_url`, `passed`, `confidence`, `defects_json`, `recommendation` |

### Session Management

`database.py` exposes `engine`, `SessionLocal`, and `Base`. Routers use `get_db()` as a FastAPI dependency. Tests patch `db_module.engine` and `db_module.SessionLocal` with a `StaticPool` in-memory engine to avoid cross-connection isolation issues.

## Auth Flow

```
Client              /api/auth/register or /login
  │                         │
  │  POST {email, password}  │
  ├────────────────────────► │
  │                          │  Argon2id hash verify
  │                          │  python-jose sign JWT
  │  {access_token: <jwt>}   │
  │◄────────────────────────  │

  │  GET /api/orders          │
  │  Authorization: Bearer <jwt>
  ├────────────────────────► │
  │                          │  get_current_user() dependency
  │                          │  decodes JWT → user_id
  │                          │  scopes DB query to created_by_id
  │  [{orders...}]           │
  │◄────────────────────────  │
```

Passwords are hashed with **Argon2id** (`argon2-cffi`). JWTs are signed with HS256. Token expiry defaults to 7 days (configurable via `JWT_EXPIRE_DAYS` env var).

## Key Design Decisions

1. **Agents are plain Python classes** — no framework lock-in. They can be called from CLI, tests, Celery tasks, or HTTP routes without modification.
2. **Scheduler is deterministic given the same input** — enables reproducible tests.
3. **SA warm-starts from EDD** — SA never produces a worse schedule than EDD; it can only improve.
4. **Mock data in `get_mock_orders()`** — the demo `/api/schedule/demo` endpoint uses this, so the frontend works without any user input.
5. **StaticPool for test isolation** — SQLite in-memory opens a fresh DB per connection; StaticPool reuses one connection so multi-request tests share state correctly.
6. **User-scoped queries** — all order/schedule/inspection endpoints filter by `created_by_id`, preventing cross-user data leakage.
