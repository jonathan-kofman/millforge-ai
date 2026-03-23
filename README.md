# MillForge

**AI-powered software-defined metal mill.** Compresses metal part lead times from 60–90 days to 3–7 days through intelligent production scheduling, quality vision, and energy optimization.

**GitHub**: https://github.com/jonathan-kofman/millforge-ai

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
make test       # run tests (113 tests)
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
│   ├── routers/             # quote, schedule, orders, vision, contact, auth
│   ├── models/schemas.py    # Pydantic request/response models
│   ├── auth/                # JWT utils + dependency injection
│   └── agents/
│       ├── scheduler.py     # EDD scheduler (core POC)
│       ├── sa_scheduler.py  # Simulated Annealing optimizer
│       ├── quality_vision.py
│       └── energy_optimizer.py
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/      # QuoteForm, ScheduleViewer, VisionDemo, ContactForm, OrdersView
├── tests/                   # 113 tests across all modules
├── docs/                    # architecture, agents, api_spec, roadmap, CHANGELOG
├── docker-compose.yml
├── Makefile
└── .env.example
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/quote` | No | Instant price + lead time estimate |
| POST | `/api/schedule` | No | Optimize production schedule |
| GET | `/api/schedule/demo` | No | Demo schedule with mock data |
| GET | `/api/schedule/benchmark` | No | EDD vs SA comparison |
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
