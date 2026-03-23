# MillForge Project Memory

**Last updated**: 2026-03-23
**Status**: POC — feature-complete for demo, pre-production
**GitHub**: https://github.com/jonathan-kofman/millforge-ai.git

## What It Is

AI-powered production scheduling SaaS for metal mills. Compresses part lead times from 60–90 days to 3–7 days via:
- Intelligent scheduling (EDD + Simulated Annealing)
- Computer vision quality inspection (mock → YOLO planned)
- Energy-aware production windows (mock → grid API planned)

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18, Vite, Tailwind CSS |
| Backend | FastAPI (Python 3.12+), Pydantic v2 |
| Database | SQLAlchemy 2.0 + SQLite (dev), PostgreSQL ready |
| Auth | JWT (python-jose) + Argon2id (argon2-cffi) |
| Scheduler | EDD greedy + Simulated Annealing (custom) |
| Tests | pytest, 113 tests |

## Key Agents

### Scheduler (`backend/agents/scheduler.py`)
- EDD sort: `(due_date, priority, complexity)`
- 3 machines, greedy earliest-available assignment
- `SETUP_MATRIX` for material changeover times (15–90 min)
- `THROUGHPUT` dict: steel=4, aluminum=6, titanium=2.5, copper=5 (units/hr)
- `estimate_lead_time()` used by `/api/quote`

### SAScheduler (`backend/agents/sa_scheduler.py`)
- Warm-starts from EDD, then 12k SA iterations
- Objective: minimize Σ w_i × max(0, C_i − d_i) where w_i = (11 - priority)
- Moves: swap, transfer, cross-swap
- Deterministic with fixed seed; never regresses below EDD solution
- ~200ms for 8–50 orders / 3 machines

### QualityVisionAgent (`backend/agents/quality_vision.py`)
- Mock: random confidence [0.72, 0.99], pass threshold 0.85
- Roadmap: YOLOv8 / ViT fine-tuned on industrial defect datasets
- Persists InspectionRecord to DB on every call

### EnergyOptimizer (`backend/agents/energy_optimizer.py`)
- Mock 24-hour price curve (off-peak 06¢, peak 19¢/kWh)
- Machine power: steel=85kW, titanium=110kW, aluminum=55kW, copper=65kW
- `get_optimal_start_windows()` → top 5 cheapest windows in next 24h
- Roadmap: EIA / Electricity Maps API

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /api/quote | No | Instant pricing + lead time |
| POST | /api/schedule | No | Schedule from order list |
| GET | /api/schedule/demo | No | Mock data schedule |
| GET | /api/schedule/benchmark | No | EDD vs SA comparison |
| POST | /api/vision/inspect | No | Quality inspection |
| POST | /api/contact | No | Contact form |
| POST | /api/auth/register | No | Register user |
| POST | /api/auth/login | No | Login → JWT |
| GET/POST | /api/orders | JWT | List/create orders |
| GET/PATCH/DELETE | /api/orders/{id} | JWT | Get/update/delete order |
| POST | /api/orders/schedule | JWT | Schedule pending orders → DB |

## DB Models (`backend/db_models.py`)

- `User`: id, email (unique), hashed_password, name, created_at
- `OrderRecord`: order_id (UUID-based), material, dimensions, quantity, priority, complexity, due_date, status (pending/scheduled/in_progress/completed/cancelled), notes, created_by_id FK
- `ScheduleRun`: algorithm, order_ids_json, summary_json, on_time_rate, makespan_hours, created_by_id FK
- `InspectionRecord`: order_record_id FK (nullable), order_id_str, image_url, passed, confidence, defects_json, recommendation, inspector_version

## Critical Technical Notes

- **argon2-cffi** not passlib/bcrypt — incompatible with Python 3.13
- **StaticPool** + module-level engine patching for test isolation
- **MaterialType** is `str` enum — use `.value` in routers (already a string in DB)
- **python-jose** emits `datetime.utcnow()` deprecation warnings — not our code, can't fix without fork
- **JWT in localStorage** — acceptable for POC, switch to httpOnly cookie for production
- **SA estimate_lead_time()** — runs full SA per call (used in quote endpoint; should switch to EDD for speed)

## Backlog

1. [High] CI/CD pipeline (GitHub Actions)
2. [Medium] Real YOLO/ONNX CV model
3. [Medium] GET /api/orders/schedule-history
4. [Medium] Frontend Gantt chart (recharts)
5. [Medium] Rate limiting on auth endpoints (slowapi)
6. [Medium] Alembic migrations
7. [Low] Real energy price API
8. [Low] Prometheus /metrics
9. [Low] Kubernetes / Helm
10. [Low] httpOnly cookie for JWT

## Reference CV Repos (cloned to ~/projects/references/)

- **Surface-Defect-Detection** (Charmve) — survey + dataset links for 47 defect datasets
- **sagemaker-defect-detection** (AWS) — full MLOps pipeline: data prep, training, SageMaker endpoint
- **visual-quality-inspection** (Intel oneAPI) — ONNX model optimization, OpenVINO inference
