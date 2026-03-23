# MillForge

**AI-powered software-defined metal mill.** Compresses metal part lead times from 60–90 days to 3–7 days through intelligent production scheduling, quality vision, and energy optimization.

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
│   ├── routers/             # quote, schedule, vision, contact
│   ├── models/schemas.py    # Pydantic request/response models
│   ├── agents/
│   │   ├── scheduler.py     # EDD scheduler (core POC)
│   │   ├── quality_vision.py
│   │   └── energy_optimizer.py
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── App.jsx
│       └── components/      # QuoteForm, ScheduleViewer, VisionDemo, ContactForm
├── tests/
│   └── test_scheduler.py
├── docs/                    # architecture, agents, api_spec, roadmap
├── docker-compose.yml
├── Makefile
└── .env.example
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/quote` | Instant price + lead time estimate |
| POST | `/api/schedule` | Optimize production schedule |
| GET | `/api/schedule/demo` | Demo schedule with mock data |
| POST | `/api/vision/inspect` | Quality inspection (mock CV) |
| POST | `/api/contact` | Pilot interest form |
| GET | `/health` | Health check |

Full spec: [`docs/api_spec.md`](docs/api_spec.md)

## Architecture

See [`docs/architecture.md`](docs/architecture.md) for system diagrams and data flow.

## Development Roadmap

See [`docs/development_plan.md`](docs/development_plan.md) for the phased plan from POC to production.
