# MillForge Agent Memory

## Session Log

| Date | Task | Outcome | Lessons |
|------|------|---------|---------|
| 2026-03-23 | Initial POC scaffolding | Full stack built: FastAPI backend, React frontend, EDD scheduler, mock CV, energy optimizer, Docker, Makefile, docs. 15 tests pass. | EDD greedy is suboptimal; `datetime.utcnow()` deprecated in Python 3.12+ |
| 2026-03-23 | SA Scheduler + benchmark endpoint | SAScheduler (12k iterations, warm-start EDD). `?algorithm=` param. Benchmark endpoint. Fixed utcnow(). 27 tests. | SA deterministic with fixed seed. Warm-start EDD means SA never regresses. Keep `optimize()` interface stable. |
| 2026-03-23 | Persistence + JWT Auth + Orders CRUD | SQLAlchemy + SQLite (4 ORM models: User, OrderRecord, ScheduleRun, InspectionRecord). JWT via python-jose + Argon2id hashing. `/api/auth/register`, `/api/auth/login`. Full CRUD `/api/orders`. 51 tests. Frontend: AuthModal, OrdersView, auth state in App.jsx. | **passlib[bcrypt] incompatible with Python 3.13/bcrypt 4.x** — use `argon2-cffi` instead. **SQLite in-memory per-connection = fresh DB** — must use `StaticPool` in tests. Module-level patching (`db_module.engine = test_engine`) works because Python resolves globals at call time. |
| 2026-03-23 | Orders→Schedule integration + Vision persistence | `POST /api/orders/schedule` — fetches user's pending orders, runs SA/EDD, saves ScheduleRun to DB, marks orders "scheduled". Vision router now persists InspectionRecord after each call. Pydantic `Field(example=...)` deprecation warnings fixed. Frontend: "Schedule N Pending" button + schedule result panel with summary metrics and Gantt table. 63 tests. | **FastAPI route ordering**: `POST /api/orders/schedule` must be after the collection-level POST but won't conflict with `/{order_id}` routes since those use different HTTP methods. `_record_to_domain()` helper converts ORM OrderRecord → domain Order; `material` is already a string in the DB (no `.value` needed). |
| 2026-03-23 | Schedule history + SVG Gantt chart | `GET /api/orders/schedule-history` (paginated, auth-scoped, newest-first). Pure-SVG GanttChart: machine rows × time axis, bars colored by material, dashed-red late borders, setup dim segments. ScheduleHistoryPanel: collapsible accordion auto-refreshing on new runs. Detail table moved behind `<details>` toggle. 121 tests (8 new). | `GET /schedule-history` must be declared BEFORE `GET /{order_id}` in the router to avoid FastAPI matching "schedule-history" as an order_id path param. Pure SVG Gantt needs zero extra npm deps — use viewBox with an internal coordinate system, `toX()` mapping timestamps to x-positions. |

## Current Backlog (Prioritized)

1. [High] CI/CD pipeline (GitHub Actions: test → lint → build → push)
2. [Medium] Integrate real YOLO/ONNX CV model for quality inspection (replace mock)
3. [Medium] Add real-time energy price API (EIA / Electricity Maps)
4. [Low] Prometheus `/metrics` endpoint + health check enhancements
5. [Low] Kubernetes manifests / Helm chart
6. [Low] Rate limiting (slowapi or custom middleware)
7. [Low] Alembic migration files for DB version control

**COMPLETED this session:**
- ✅ `GET /api/orders/schedule-history` — paginated list of past ScheduleRuns (auth-scoped)
- ✅ Pure-SVG GanttChart component (machine rows, material colors, late indicators, time axis)
- ✅ ScheduleHistoryPanel collapsible accordion in OrdersView
- ✅ Detail table hidden behind `<details>` toggle in schedule result card
- ✅ 8 new tests (121 total, 0 failures)

## Known Issues / Technical Debt

- `python-jose` internally uses `datetime.utcnow()` (warning only, not our code — unfixable without forking)
- `SA.estimate_lead_time()` runs full SA per call — expensive for quote endpoint; switch quote to use EDD for speed
- No rate limiting on any endpoint
- JWT stored in `localStorage` — acceptable for POC, use `httpOnly` cookie for production
- Vision inspection uses mock agent — no real YOLO/ONNX model yet
- No schedule history endpoint (ScheduleRun rows are saved but not exposed via API)

## Architecture Notes

- **DB layer**: `database.py` (engine, SessionLocal, get_db, init_db) → `db_models.py` (ORM) → `models/schemas.py` (Pydantic)
- **Auth flow**: `POST /api/auth/register|login` → returns JWT → client sends `Authorization: Bearer <token>` → `get_current_user` dependency validates and returns `User` ORM object
- **Test isolation**: `StaticPool` + module-level `db_module.engine` patching in `conftest.py`. Each test gets a fresh in-memory DB but all connections within the test share it.
- **Password hashing**: `argon2-cffi` (NOT passlib/bcrypt — incompatible with Python 3.13)
- **Orders**: user-scoped (filtered by `created_by_id`). Users cannot see/modify/delete each other's orders.
- All Pydantic models in `backend/models/schemas.py`
- Existing public endpoints (`/api/quote`, `/api/schedule`, `/api/vision/inspect`, `/api/contact`) require NO auth — backwards compatible

## Next Session Goals

- [ ] CI/CD: GitHub Actions workflow (pytest → ruff lint → docker build)
- [ ] Quote endpoint: switch to EDD for lead time estimation (SA is too slow per-call)
- [ ] Real YOLO/ONNX vision model or a simple CNN baseline to replace mock inspector
- [ ] Gantt chart tooltip on hover (order_id + times) — needs SVG `<title>` or overlay div
