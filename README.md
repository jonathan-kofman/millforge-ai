# MillForge

[![CI](https://github.com/jonathan-kofman/millforge-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/jonathan-kofman/millforge-ai/actions/workflows/ci.yml)

**An intelligence layer for job shops.** MillForge takes a shop's real constraints — its machines, staff, suppliers, and deals — as inputs and optimises within them. The measurable output is on-time delivery rate and machine utilisation, not promises about lead times or new infrastructure.

A shop that runs FIFO today and delivers 55% of orders on time can reach 85–95% on-time with the same equipment and same staff, just by sequencing work smarter.

**GitHub**: https://github.com/jonathan-kofman/millforge-ai

## The Core Demo

`GET /api/schedule/benchmark` runs three strategies on the same order set:

| Strategy | What it is |
|----------|-----------|
| `fifo` | Naive baseline — process jobs in arrival order, no optimisation |
| `edd` | MillForge EDD — greedy earliest-due-date with setup-time awareness |
| `sa` | MillForge SA — simulated annealing, minimises weighted tardiness |

The `on_time_improvement_pp` field in the response is the number that matters: how many percentage points MillForge adds over the naive baseline on the shop's own order data.

## Quick Start

### Option A – Docker Compose (recommended)

```bash
cp .env.example .env
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000
- Swagger docs: http://localhost:8000/docs

### Option B – Local Development

**Backend**
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend** (separate terminal)
```bash
cd frontend
npm install
npm run dev
```

### Run Tests
```bash
# From project root
cd backend && python -m pytest ../tests/ -v
```

Or with Make:
```bash
make install    # install all deps
make test       # run tests
make dev-backend
make dev-frontend
```

## Project Structure

```
millforge-ai/
├── backend/
│   ├── main.py              # FastAPI app entry point
│   ├── database.py          # SQLAlchemy engine + SessionLocal
│   ├── db_models.py         # ORM models: User, OrderRecord, ScheduleRun, InspectionRecord
│   ├── routers/             # quote, schedule, orders, vision, contact, auth, rework
│   ├── models/schemas.py    # Pydantic request/response models
│   ├── auth/                # JWT utils + dependency injection
│   └── agents/
│       ├── scheduler.py         # EDD scheduler (core)
│       ├── sa_scheduler.py      # Simulated Annealing optimizer
│       ├── quality_vision.py    # Mock CV inspection
│       ├── energy_optimizer.py  # Energy cost estimation
│       ├── inventory_agent.py   # Stock tracking and reorder
│       └── production_planner.py # Weekly plan via Claude
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/      # QuoteForm, ScheduleViewer, VisionDemo, ContactForm, OrdersView
├── tests/                   # 278 tests across all modules
├── docs/                    # architecture, agents, api_spec, roadmap, CHANGELOG
├── docker-compose.yml
├── Makefile
└── .env.example
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/schedule/benchmark` | No | **Core demo** — FIFO vs EDD vs SA on-time comparison |
| POST | `/api/quote` | No | Instant quote within real shop capacity constraints |
| POST | `/api/schedule` | No | Optimise production schedule within shop constraints |
| GET | `/api/schedule/demo` | No | Demo schedule on built-in mock order set |
| POST | `/api/schedule/rework` | No | Schedule rework orders from failed quality inspections |
| POST | `/api/vision/inspect` | No | Quality inspection (mock CV) |
| POST | `/api/contact` | No | Pilot interest form |
| POST | `/api/auth/register` | No | Register user account |
| POST | `/api/auth/login` | No | Login → JWT token |
| GET | `/api/orders` | JWT | List user's orders |
| POST | `/api/orders` | JWT | Create order |
| GET | `/api/orders/{id}` | JWT | Get order by ID |
| PATCH | `/api/orders/{id}` | JWT | Update order |
| DELETE | `/api/orders/{id}` | JWT | Delete order |
| POST | `/api/orders/schedule` | JWT | Schedule pending orders |
| GET | `/health` | No | Health check |

Full spec: [`docs/api_spec.md`](docs/api_spec.md)

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for system diagrams and data flow.

## Development Roadmap

See [`docs/development_plan.md`](docs/development_plan.md) for the phased plan from POC to production.
