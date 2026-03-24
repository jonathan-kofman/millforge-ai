# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Product Vision

MillForge is an **intelligence layer** that sits on top of whatever constraints a job shop already has — their machines, their suppliers, their staff, their deals. It does not control lead times, replace physical infrastructure, or promise supply chain transformation.

**The value proposition**: a job shop that was 60% on-time becomes 90%+ on-time with the same machines, same suppliers, same staff — just smarter sequencing.

**Inputs**: the shop's real constraints (machine throughput, setup times, material changeovers, order priorities, due dates).
**Outputs**: on-time delivery rate and machine utilisation.

**The core demo is `/api/schedule/benchmark`**: it shows a three-way comparison of FIFO (naive baseline any shop can relate to) vs MillForge EDD vs MillForge SA on the same order set. The `on_time_improvement_pp` field is the number that wins the room.

**Locked benchmark numbers (deterministic, 28-order dataset):**
- FIFO: 60.7% on-time (±2pp, [58.7%, 62.7%])
- EDD: 96.4% on-time (±2pp, [94.4%, 98.4%])
- SA: 100.0% on-time (±1pp, [99.0%, 100.0%])
- Improvement over FIFO: +39.3pp
- Results are fully deterministic — identical every run

When writing copy, docs, or code comments, always frame MillForge around *efficiency within existing constraints*, never around *replacing* those constraints or compressing lead times as a standalone claim.

## Commands

```bash
# Backend (from /backend)
uvicorn main:app --reload --port 8000       # dev server with hot reload
python -m pytest ../tests/ -v               # run all tests
python -m pytest ../tests/test_scheduler.py::test_name -v  # run single test

# Frontend (from /frontend)
npm run dev     # Vite dev server on :5173
npm run build   # production build

# Full stack
make install        # install all deps
make dev-backend    # backend only
make dev-frontend   # frontend only
make test           # run pytest
docker compose up --build   # full stack via Docker
```

## Architecture

**Three-layer structure: React SPA → FastAPI → Agent modules.**

```
frontend/src/         React + Vite + Tailwind CSS
backend/main.py       FastAPI entry point; registers routers, configures CORS
backend/routers/      Thin HTTP handlers (quote, schedule, vision, contact)
backend/models/       Pydantic v2 schemas — single source of truth for API contracts
backend/agents/       Business logic — no FastAPI dependency, pure Python classes
tests/                pytest; must add sys.path to backend/ (already done in conftest)
```

**Key design rules:**
- Routers are thin — all logic lives in agents
- Agents are instantiated once at module level in each router (not per-request)
- `get_mock_orders()` in `scheduler.py` is the canonical demo dataset — used by `/api/schedule/demo`
- Vite proxies `/api` to `localhost:8000` during dev, so no CORS config needed in the browser

## Core Scheduler Logic (`backend/agents/scheduler.py`)

The `Scheduler` class is the heart of the POC. Key internals:
- **Sorting**: EDD — orders sorted by `(due_date, priority, complexity)`
- **Machine assignment**: greedy earliest-available machine
- **Setup times**: `SETUP_MATRIX` dict keyed on `(from_material, to_material)` tuples; missing pairs fall back to `BASE_SETUP_MINUTES = 30`
- **Throughput**: `THROUGHPUT` dict (units/hour by material) × complexity multiplier
- `estimate_lead_time()` inserts a candidate order into the mock queue and returns completion delta from now — used by the quote endpoint

When extending the scheduler, keep the `Scheduler.optimize(orders, start_time) -> Schedule` signature stable — the router and tests depend on it.

## Pydantic Models

All request/response types are in `backend/models/schemas.py`. `MaterialType` is a `str` enum — always use `.value` when passing to domain objects (e.g., `req.material.value`).

## Adding a New Agent

1. Create `backend/agents/my_agent.py` with a class and no FastAPI imports
2. Export from `backend/agents/__init__.py`
3. Create a router in `backend/routers/my_router.py` and register it in `main.py`
4. Add Pydantic schemas to `models/schemas.py`
5. Add tests to `tests/`

## Quote Endpoint (`backend/routers/quote.py`)

- Uses EDD-only (`Scheduler.estimate_lead_time()`) for lead time — SA was removed (avg ~180 ms delta, negligible difference)
- Volume discount tiers: 0% / 5% (500+) / 10% (1000+) / 20% (10000+)
- Unit prices by material in `UNIT_PRICE` dict

## Rework Endpoint (`backend/routers/rework.py`)

- `POST /api/schedule/rework` — converts failed inspection items to priority-1 rework orders
- Severity → complexity × deadline: `critical=2.5×/24h`, `major=1.8×/48h`, `minor=1.3×/72h`
- Rework order IDs prefixed `RW-{original_id}`
- Uses `SAScheduler` for scheduling rework orders

## E2E Smoke Test (`tests/test_e2e.py`)

Full chain: schedule → inspect → energy → quote → rework (Step 6). Key assertions:
- Rework order IDs start with `RW-{original_id}`
- `machine_id` in rework schedule is a positive integer
- Inspection response echoes the `order_id` submitted
- Complexity boosts: `critical=2.5`, `major=1.8`, `minor=1.3`
- Quote `total_price_usd > 0`

## Frontend Notes

- Tailwind custom components (`btn-primary`, `card`, `input`, `label`) are defined in `src/index.css` under `@layer components`
- Custom `forge-*` color palette is in `tailwind.config.js`
- All API calls go through relative `/api/...` paths — Vite proxies to backend in dev
- Error state pattern: `const [loading, error, result]` with early `setError(null)` on each request
