# MillForge

[![CI](https://github.com/jonathan-kofman/millforge-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/jonathan-kofman/millforge-ai/actions/workflows/ci.yml)

Most metal mills have 8 to 30 week lead times not because the machines are slow — but because everything around them is manual and fragmented.

**MillForge AI** replaces the scheduling chaos with software that optimizes, quotes, inspects, and reschedules automatically.

**Live demo**: https://millforge-ai.vercel.app
**API**: https://millforge-ai.up.railway.app
**GitHub**: https://github.com/jonathan-kofman/millforge-ai

## Lights-Out Readiness

`GET /health` returns the live scoreboard — how many production touchpoints are fully automated vs pretrained vs mock:

| Touchpoint | Status |
|------------|--------|
| Scheduling | ✅ automated |
| Quoting | ✅ automated |
| Quality Inspection | ⚡ pretrained (YOLOv8n ONNX) |
| Rework Dispatch | ✅ automated |
| Inventory Management | ✅ automated |
| Energy Optimization | ✅ automated (PJM real-time LMP) |
| Production Planning | 📊 real data (US Census ASM) |

**Current readiness: 71%** (5 of 7 touchpoints fully automated)

## The Core Demo

`GET /api/schedule/benchmark` runs three strategies on the same 28-order dataset:

| Strategy | On-time rate | What it is |
|----------|-------------|-----------|
| `fifo` | 60.7% | Naive baseline — arrival order, no optimisation |
| `edd` | 96.4% | MillForge EDD — greedy earliest-due-date with setup-time awareness |
| `sa` | 100.0% | MillForge SA — simulated annealing, minimises weighted tardiness |

**+39.3pp on-time improvement over the naive baseline.** Same machines, same staff, same suppliers.

Results are fully deterministic — identical every run.

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
│       ├── quality_vision.py    # YOLOv8n ONNX visual quality triage
│       ├── energy_optimizer.py  # Energy cost estimation
│       ├── inventory_agent.py   # Stock tracking and auto-reorder
│       └── rework.py            # Rework dispatch from failed inspections
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/      # QuoteForm, ScheduleViewer, VisionDemo, BenchmarkDemo, LightsOutWidget
├── tests/                   # pytest suite across all modules
├── docs/                    # architecture, agents, api_spec, roadmap, CHANGELOG
├── docker-compose.yml
├── Makefile
└── .env.example
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Lights-out readiness scoreboard |
| GET | `/api/schedule/benchmark` | No | **Core demo** — FIFO vs EDD vs SA on-time comparison |
| POST | `/api/quote` | No | Instant quote within real shop capacity constraints |
| POST | `/api/schedule` | No | Optimise production schedule within shop constraints |
| GET | `/api/schedule/demo` | No | Demo schedule on built-in mock order set |
| POST | `/api/schedule/rework` | No | Auto-dispatch rework orders from failed inspections |
| POST | `/api/vision/inspect` | No | Visual quality triage (YOLOv8n ONNX pretrained) |
| POST | `/api/contact` | No | Pilot interest form |
| POST | `/api/auth/register` | No | Register user account |
| POST | `/api/auth/login` | No | Login → JWT token |
| GET | `/api/orders` | JWT | List user's orders |
| POST | `/api/orders` | JWT | Create order |
| GET | `/api/orders/{id}` | JWT | Get order by ID |
| PATCH | `/api/orders/{id}` | JWT | Update order |
| DELETE | `/api/orders/{id}` | JWT | Delete order |
| POST | `/api/orders/schedule` | JWT | Schedule pending orders |

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for system diagrams and data flow.

## Development Roadmap

See [`docs/development_plan.md`](docs/development_plan.md) for the phased plan from POC to production.
