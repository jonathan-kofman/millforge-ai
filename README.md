# MillForge

[![CI](https://github.com/jonathan-kofman/millforge-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/jonathan-kofman/millforge-ai/actions/workflows/ci.yml)

Most metal mills have 8 to 30 week lead times not because the machines are slow — but because everything around them is manual and fragmented.

**MillForge AI** replaces the scheduling chaos with software that optimizes, quotes, inspects, and reschedules automatically.

**Live demo**: https://millforge-ai.vercel.app
**API**: https://millforge-ai-production.up.railway.app
**GitHub**: https://github.com/jonathan-kofman/millforge-ai

## Lights-Out Readiness

`GET /health` returns the live scoreboard — how many production touchpoints are fully automated vs pretrained vs mock:

| Touchpoint | Status |
|------------|--------|
| Scheduling | ✅ automated |
| Quoting | ✅ automated |
| Quality Inspection | 🔬 onnx_inference (NEU-DET YOLOv8n, mAP50=0.759 — first-pass triage; CMM validation on roadmap) |
| Anomaly Detection | ✅ automated (critical orders auto-held before scheduling) |
| Rework Dispatch | ✅ automated |
| Inventory Management | ✅ automated |
| Energy Optimization | ✅ automated (EIA API v2, PJM demand-based) |
| Material Sourcing | ✅ directory active (1,137 verified US suppliers, geo-search) |
| Production Planning | 📊 real data (US Census ASM) |
| Predictive Maintenance | ✅ automated (MTBF/MTTR risk scoring → exception queue) |
| Exception Handling | ✅ automated (5-source aggregator) |

**Current readiness: 91%** (10 of 11 touchpoints fully automated)

## The Core Demo

`GET /api/schedule/benchmark` runs three strategies on the same 28-order dataset:

| Strategy | On-time rate | What it is |
|----------|-------------|-----------|
| `fifo` | 60.7% | Naive baseline — arrival order, no optimisation |
| `edd` | 82.1% | MillForge EDD — greedy earliest-due-date with setup-time awareness |
| `sa` | 96.4% | MillForge SA — simulated annealing, minimises weighted tardiness |

**+35.7pp on-time improvement over the naive baseline.** Same machines, same staff, same suppliers.

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
│   ├── main.py              # FastAPI app entry point; 18 routers, lifespan hooks
│   ├── database.py          # SQLAlchemy engine + SessionLocal
│   ├── db_models.py         # ORM models: User, OrderRecord, ScheduleRun, Supplier, JobFeedbackRecord…
│   ├── routers/             # 23 thin HTTP handlers (schedule, quote, vision, energy, suppliers…)
│   ├── models/schemas.py    # Pydantic v2 request/response models — single source of truth
│   ├── auth/                # httpOnly cookie session + JWT utils
│   ├── scripts/             # seed_suppliers.py, train_vision_model.py, export_model.py
│   └── agents/              # 25 pure-Python business-logic modules
│       ├── scheduler.py           # EDD core — machine assignment, setup-time matrix
│       ├── sa_scheduler.py        # Simulated Annealing (seed=123, deterministic)
│       ├── benchmark_data.py      # 28-order deterministic dataset (FIFO/EDD/SA)
│       ├── quality_vision.py      # YOLOv8n ONNX inference (NEU-DET, mAP50=0.759)
│       ├── energy_optimizer.py    # EIA API v2 pricing, carbon intensity, 10-yr NPV
│       ├── inventory_agent.py     # Stock tracking, auto-reorder POs
│       ├── anomaly_detector.py    # Critical anomaly gate — auto-holds before scheduling
│       ├── exception_queue.py     # 5-source urgency aggregator
│       ├── predictive_maintenance.py  # MTBF/MTTR risk scoring
│       ├── supplier_directory.py  # 1,137 US suppliers, haversine geo-search
│       ├── scheduling_twin.py     # ML self-calibration (RandomForest setup-time predictor)
│       ├── dashboard.py           # Live lights-out KPI aggregation
│       ├── cad_parser.py          # STL → order parameters (ARIA-OS bridge)
│       └── …                     # machine_fleet, machine_state_machine, feedback_logger…
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/      # 14 components: BenchmarkDemo, LightsOutWidget, SupplierMap,
│                            #   VisionDemo, EnergyWidget, GanttChart, QuoteForm…
├── tests/                   # 36 pytest files — unit + e2e coverage
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
| POST | `/api/schedule` | No | Optimise production schedule within shop constraints |
| GET | `/api/schedule/demo` | No | Demo schedule on built-in mock order set |
| POST | `/api/quote` | No | Instant quote with volume discounts and carbon footprint |
| POST | `/api/schedule/rework` | No | Auto-dispatch rework orders from failed inspections |
| POST | `/api/vision/inspect` | No | Visual quality triage (YOLOv8n ONNX, NEU-DET, mAP50=0.759 — first-pass triage only) |
| GET | `/api/energy/negative-pricing-windows` | No | Detect off-peak/low-cost grid hours (PJM demand-based; true negative LMP on roadmap) |
| POST | `/api/energy/arbitrage-analysis` | No | Off-peak shift savings estimate |
| POST | `/api/energy/scenario` | No | 10-year NPV for solar/wind/battery/SMR/grid-only |
| GET | `/api/suppliers` | No | Search 1,137 verified US suppliers |
| GET | `/api/suppliers/nearby` | No | Geo-sorted supplier search by lat/lng radius |
| GET | `/api/inventory/reorder-with-suppliers` | No | Reorder POs with nearest supplier suggestions |
| GET | `/api/dashboard/live` | JWT | Composite lights-out score + live KPIs |
| GET | `/api/exceptions` | JWT | 5-source exception queue (maintenance, energy, anomaly, inventory, orders) |
| POST | `/api/anomaly/detect` | No | Run anomaly detection on an order batch |
| POST | `/api/orders/from-cad` | No | STL upload → extracted order parameters |
| GET | `/api/learning/calibration-report` | JWT | Setup/processing time prediction accuracy |
| GET | `/api/twin/accuracy` | JWT | Scheduling twin MAE vs actual job records |
| POST | `/api/contact` | No | Pilot interest form |
| POST | `/api/auth/register` | No | Register user account |
| POST | `/api/auth/login` | No | Login → httpOnly session cookie |
| GET | `/api/orders` | JWT | List user's orders |
| POST | `/api/orders` | JWT | Create order |
| PATCH | `/api/orders/{id}` | JWT | Update order |
| DELETE | `/api/orders/{id}` | JWT | Delete order |

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for system diagrams and data flow.

## Development Roadmap

See [`docs/development_plan.md`](docs/development_plan.md) for the phased plan from POC to production.
