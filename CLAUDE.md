# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Lights-Out Vision

MillForge is **the software stack for lights-out American metal mills**. China is moving toward dark factories — fully automated metal production where software controls the entire production flow and humans handle exceptions only. The US has almost none of this. MillForge is building the intelligence layer that makes it possible.

**Every feature is evaluated against one question: does this remove a human touchpoint from routine metal production?**

**Hierarchy of human touchpoints to eliminate (in order of priority):**
1. **Scheduling** — ✅ automated. No human decides what runs next.
2. **Quoting** — ✅ automated. No human calculates lead time or price.
3. **Quality triage** — 🔬 onnx_inference (NEU-DET YOLOv8n mAP50=0.759, model deployed). No human does first-pass visual inspection.
4. **Anomaly detection** — ✅ automated. Critical order anomalies (duplicate IDs, impossible deadlines) auto-held before scheduling; no human scans batch.
5. **Rework dispatch** — ✅ automated. No human decides rework priority.
6. **Energy procurement** — ✅ automated (EIA API v2, PJM demand-based pricing). No human decides when to run energy-intensive jobs.
7. **Inventory reorder** — ✅ automated. No human monitors stock levels.
8. **Material sourcing** — ✅ directory active (1,100+ verified US suppliers, geo-search). No human searches for suppliers.
9. **Production planning** — real data (Census ASM throughput). No human translates demand signals into capacity targets.
10. **Exception handling** — this is what humans are for. Everything else is software.

**Module audit against the lights-out lens:**

| Module | Removes Human? | Status | Priority |
|--------|---------------|--------|----------|
| scheduler.py | ✅ Yes — no human schedules jobs | automated | Core |
| quote.py | ✅ Yes — no human prices orders | automated | Core |
| quality_vision.py | Partially — triage only | onnx_inference (NEU-DET YOLOv8n, mAP50=0.759, model present in repo) | High |
| rework.py | ✅ Yes — auto-dispatches failures | automated | Core |
| inventory_agent.py | ✅ Yes — auto-reorders stock | automated | Medium |
| energy_optimizer.py | ✅ Yes — no human decides when to run energy-intensive jobs | automated (EIA API v2, PJM demand-based) | Medium |
| supplier_directory.py | ✅ Yes — no human searches for suppliers | directory_active (1,100+ US suppliers, 4 categories) | Medium |
| production_planner.py | Partially — real Census ASM throughput data | real_data | Defer |
| nl_scheduler.py | Assists human, not replaces | mock | Defer |
| anomaly_detector.py | ✅ Yes — critical anomalies auto-held before scheduling | automated | Core |

**Lights-out readiness target:** `GET /health` returns a `lights_out_readiness` object showing automated vs mock vs not-implemented for each touchpoint. This is the living scoreboard.

## Claude Agents (`.claude/agents/`)

Specialized subagents for common MillForge tasks. Invoke via the Agent tool or `/agent-name` in Claude Code.

| Agent | When to use |
|-------|-------------|
| `millforge-pm` | Start of any session; deciding what to build next; YC readiness check |
| `lights-out-auditor` | Before building any feature — does it remove a human touchpoint? |
| `feature-prioritizer` | Rank backlog items against lights-out lens + discovery signal |
| `pricing-analyst` | Analyze WTP signals from discovery; recommend pricing tiers |
| `yc-prep` | Draft/stress-test YC application answers; adversarial Q&A prep |
| `customer-discovery-coach` | Prep for interviews; debrief after conversations |
| `demo-validator` | Before any partner meeting — verify benchmark numbers are locked |
| `scheduler-debugger` | Debug late orders, underutilized machines, bad EDD sequences |
| `energy-optimizer-analyzer` | Validate energy cost estimates and grid pricing logic |
| `quality-vision-tester` | Test vision inspection results and defect classification |
| `backend-reviewer` | Review before merging changes to backend/agents/, backend/routers/ |
| `frontend-reviewer` | Review before merging changes to frontend/src/ |
| `deployment-checker` | Diagnose Railway/Vercel deploy failures, CORS issues, env var gaps |
| `business-advisor` | Pricing conversations, ROI analysis, competitive positioning, feature business cases |
| `market-quoter` | Spot price debugging, supplier cost modeling, energy window analysis |
| `contract-generator` | Generate/review MSA, SLA, order forms, pilot agreements for new customers |

## Product Vision

MillForge is the intelligence layer for lights-out American metal mills — starting with AI production scheduling that replaces manual coordination, and expanding to automated quoting, real-time execution monitoring, computer vision quality inspection, and energy optimization.

**The benchmark demo is `/api/schedule/benchmark`**: three-way comparison of FIFO (naive baseline) vs MillForge EDD vs MillForge SA on the same order set. The `on_time_improvement_pp` field is the number that wins the room.

**Locked benchmark numbers (deterministic, 28-order dataset):**
- FIFO: 60.7% on-time (17/28)
- EDD: 82.1% on-time (23/28)
- SA: 96.4% on-time (27/28) — seed=123
- Improvement over FIFO: +35.7pp (SA)
- Results are fully deterministic — identical every run (same reference_time passed to both order generation and optimizer)

When writing copy, docs, or code comments, frame MillForge around *removing human touchpoints from routine production*, not scheduling assistance or lead time compression.

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

# Ollama (local LLM for discovery agent)
ollama serve                # start Ollama if not running as a service
ollama list                 # show available models
ollama pull llama3.2        # pull the model used by the discovery agent
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
- **Shift calendar**: `QuoteRequest.shifts_per_day` (1–3) and `hours_per_shift` (4–12) are optional. When both provided, raw scheduled hours are scaled by `24 / (shifts_per_day * hours_per_shift)` to convert continuous-machine hours to real calendar days. Omitting either field preserves original behavior (assumes 24h operation).

## Anomaly Gate (`backend/agents/anomaly_detector.py`, `backend/routers/schedule.py`)

Every `POST /api/schedule` call automatically runs the anomaly detector before scheduling. This removes the "human scans the batch" touchpoint.

**Auto-hold logic:**
- `AnomalyDetector.detect(orders)` runs on the raw order list before any scheduling occurs
- Orders with `critical`-severity anomalies (`impossible_deadline`, `duplicate_id`) are **held** — excluded from the schedule
- Held order IDs returned in `ScheduleResponse.held_orders: List[str]`
- Full anomaly report returned in `ScheduleResponse.anomaly_report: AnomalyDetectResponse`
- `warning`-severity anomalies (quantity spike, clustering) are surfaced but **do not block** scheduling
- BATCH-level anomalies (material clustering) are never held (no single order to hold)
- Anomaly detection failure is non-fatal — schedule runs without anomaly data if detection errors

**Health endpoint:** `anomaly_detection: "automated"` — counts toward `readiness_percent`

## Rework Endpoint (`backend/routers/rework.py`)

- `POST /api/schedule/rework` — converts failed inspection items to priority-1 rework orders
- Severity → complexity × deadline: `critical=2.5×/24h`, `major=1.8×/48h`, `minor=1.3×/72h`
- Rework order IDs prefixed `RW-{original_id}`
- Uses `SAScheduler` for scheduling rework orders

## Energy Intelligence (`backend/agents/energy_optimizer.py`, `backend/routers/energy.py`)

Energy is the other half of the lights-out problem — no human decides when to run energy-intensive jobs.

**Endpoints:**
- `GET /api/energy/negative-pricing-windows` — detect hours where grid electricity is free or negative (grid pays you to run)
- `POST /api/energy/arbitrage-analysis` — compute daily/annual savings from shifting flexible load to off-peak hours
- `POST /api/energy/scenario` — 10-year NPV analysis for on-site generation: `solar`, `battery`, `solar_battery`, `wind`, `smr`, `grid_only`

**Energy analysis on every schedule response:**
- `ScheduleRequest.battery_soc_percent: Optional[float]` — pass battery state-of-charge (0–100%) to get a battery recommendation in the response
- `ScheduleResponse.energy_analysis` — `EnergyAnalysis` schema with `total_energy_kwh`, `current_schedule_cost_usd`, `optimal_schedule_cost_usd`, `potential_savings_usd`, `carbon_footprint_kg_co2`, `carbon_delta_kg_co2`, and optional `battery_recommendation`

**Carbon footprint on every quote response:**
- `QuoteResponse.carbon_footprint_kg_co2` — estimated CO2 for the order using `THROUGHPUT` (from `agents.scheduler`) × `MACHINE_POWER_KW` × `_get_carbon_intensity()`

**Key implementation details:**
- `_get_carbon_intensity()` is a **module-level function** (not an instance method of `EnergyOptimizer`) — import directly: `from agents.energy_optimizer import _get_carbon_intensity`
- `THROUGHPUT` dict lives in `agents.scheduler`, NOT `agents.energy_optimizer`
- `MACHINE_POWER_KW` dict maps material → kW draw (steel=85, aluminum=55, titanium=110, copper=65, default=70)
- `US_GRID_CARBON_INTENSITY = 0.386` kg CO2/kWh — EPA 2023 average, used as fallback
- `ELECTRICITY_MAPS_API_KEY` env var enables live carbon intensity from Electricity Maps API
- PJM demand data fetched via **EIA API v2** (`EIA_API_KEY` env var); demand (MW) is scaled to a pricing curve ($/kWh); falls back to `MOCK_HOURLY_RATES` when key not set or network fails. Note: demand-based curve is always positive — true negative LMP windows require a direct LMP feed (future roadmap)
- LCOE constants from Lazard v17 (2024): solar=0.045, battery=0.060, solar_battery=0.050, wind=0.035, SMR=0.065 $/kWh
- NPV discount rate: SMR=6%, all others=8%
- `ScenarioResponse.payback_years` is `Optional[float] = None` — `grid_only` scenario returns `None`
- Arbitrage router derives `peak_rate` / `off_peak_rate` from `_get_hourly_rates()` directly (agent dict returns delta, not absolute rates)

## E2E Smoke Test (`tests/test_e2e.py`)

Full chain: schedule → inspect → energy → quote → rework (Step 6). Key assertions:
- Rework order IDs start with `RW-{original_id}`
- `machine_id` in rework schedule is a positive integer
- Inspection response echoes the `order_id` submitted
- Complexity boosts: `critical=2.5`, `major=1.8`, `minor=1.3`
- Quote `total_price_usd > 0`

## Auth & Session (`backend/routers/auth_router.py`, `backend/auth/`)

- Session stored in **httpOnly cookie** (`millforge_session`) — not localStorage. XSS-safe.
- Cookie settings: `SameSite=none; Secure=true` in prod (Railway env), `SameSite=lax; Secure=false` in dev (Vite proxies same-origin).
- Prod detection: `_COOKIE_SECURE = bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("COOKIE_SECURE"))`
- Token extraction order in `auth/dependencies.py`: cookie first, then `Authorization: Bearer` header (backward-compatible for API clients and tests).
- `GET /api/auth/me` — returns current user from cookie; called on every page load to restore session.
- `POST /api/auth/logout` — deletes the cookie server-side.
- All authenticated frontend fetches use `credentials: "include"` — no `Authorization` headers in the browser.

## Onboarding & Shop Config (`backend/routers/onboarding.py`, `backend/db_models.py ShopConfig`)

- `ShopConfig` stores per-user shop settings: `shop_name`, `machine_count`, `materials`, `shifts_per_day` (default 2), `hours_per_shift` (default 8), `baseline_otd`, `scheduling_method`, `weekly_order_volume`.
- `shifts_per_day` and `hours_per_shift` feed into quote lead-time scaling (see Quote Endpoint above).
- `_apply_column_migrations()` in `database.py` runs `ALTER TABLE ADD COLUMN` at startup to safely add new columns to existing databases. Uses try/except to skip columns that already exist (SQLite and Postgres compatible).
- Onboarding wizard Step 1 collects: shop name, machine count, shifts per day, hours per shift.

## Frontend Notes

- Tailwind custom components (`btn-primary`, `card`, `input`, `label`) are defined in `src/index.css` under `@layer components`
- Custom `forge-*` color palette is in `tailwind.config.js`
- All API calls go through relative `/api/...` paths — Vite proxies to backend in dev
- Error state pattern: `const [loading, error, result]` with early `setError(null)` on each request
- All authenticated components use `credentials: "include"` on fetch — no token props, no localStorage.

## Real Data Sources

Every module falls back gracefully when real data is unavailable (CI-safe). The `data_source` field in each response tells callers which path was taken.

| Module | Real Data | Source | Fallback | Cache TTL |
|--------|-----------|--------|----------|-----------|
| `energy_optimizer.py` | PJM demand-based pricing | EIA API v2 → `_fetch_real_time_price()` scales PJM demand (MW) to $/kWh curve; `EIA_API_KEY` env var required | `MOCK_HOURLY_RATES` (24-hour simulated curve) | 1 hour |
| `energy_optimizer.py` | Carbon intensity | Electricity Maps API `zone=US-MIDA-PJM` via `_get_carbon_intensity()` when `ELECTRICITY_MAPS_API_KEY` set | `US_GRID_CARBON_INTENSITY = 0.386` kg CO2/kWh (EPA 2023 average) | 1 hour |
| `production_planner.py` | US Census ASM throughput | EIA API NAICS 332721 — Precision Turned Products; `EIA_API_KEY` env var set to real key (defaults to DEMO_KEY with 100 req/day limit) | `THROUGHPUT` constants (internal benchmarks) | 24 hours |
| `quality_vision.py` | NEU-DET fine-tuned YOLOv8n (mAP50=0.759) | `backend/models/neu_det_yolov8n.onnx` (train via `backend/scripts/train_vision_model.py` using Kaggle API with `KAGGLE_USERNAME`/`KAGGLE_KEY`) | Generic YOLOv8n ONNX → heuristic hash | N/A (file-based) |

## Vision Model Training (`backend/scripts/train_vision_model.py`)

Full pipeline: Kaggle download → Pascal VOC → YOLO conversion → YOLOv8n fine-tune → ONNX export.

**Prerequisites:** `pip install -r backend/requirements-optional.txt` (ultralytics, kaggle<2.0). Set `KAGGLE_USERNAME` and `KAGGLE_KEY` in `.env`.

**Pipeline steps (run `python scripts/train_vision_model.py` from `backend/`):**
1. `check_prerequisites()` — verifies ultralytics installed; auto-downloads NEU-DET from Kaggle if `data/NEU-DET/` missing
2. `download_dataset()` — writes Kaggle creds to `~/.kaggle/kaggle.json`, calls `kaggle.api.dataset_download_files("kaustubhdikshit/neu-surface-defect-database")`
3. `prepare_dataset()` — converts Pascal VOC XML annotations to YOLO label format under `data/neu_det_yolo/`; skips if already converted
4. `xml_to_yolo(xml_path, img_w, img_h)` — parses `<bndbox>` → normalized `cx cy w h`; maps to `CLASS_INDEX`
5. `train()` — `YOLO("yolov8n.pt").train(epochs=50, imgsz=640)`; finds most-recently-modified `neu_det_train*/weights/best.pt`
6. `export_onnx(weights_path)` — exports to ONNX at `backend/models/neu_det_yolov8n.onnx`; backend auto-switches to `onnx_inference` on restart

**Classes (6):** `crazing`, `inclusion`, `patches`, `pitted_surface`, `rolled-in_scale`, `scratches`

**Dataset layout expected:**
```
data/NEU-DET/train/images/<class>/*.jpg
data/NEU-DET/train/annotations/<class>/*.xml
data/NEU-DET/validation/images/<class>/*.jpg
data/NEU-DET/validation/annotations/<class>/*.xml
```

**Output:** `backend/models/neu_det_yolov8n.onnx` (replaces heuristic mock; mAP50=0.759 achieved on NEU-DET)

**Manual fallback:** Download from `https://www.kaggle.com/datasets/kaustubhdikshit/neu-surface-defect-database` and unzip so `data/NEU-DET/train/images/` exists.

**Adding new real data sources:**
1. Write a `_fetch_X()` function that returns `None` on any failure
2. Wrap with a module-level cache dict + TTL check in `_get_X()`
3. Return `(data, data_source_string)` from the getter
4. Pass `data_source` through to the response schema
5. Add tests: one that monkeypatches fetch to `None` (checks fallback), one that returns fake data (checks real path), one that calls getter twice (checks cache hit count)

## Scheduling Twin Architecture (ML self-calibration layer)

Four agents form a closed feedback loop for continuous improvement. Adapted from microgravity-manufacturing-stack patterns.

### Machine State Machine (`backend/agents/machine_state_machine.py`)

Protocol-based IO isolation: `MachineIO` Protocol → real hardware OR `MockMachineIO`.

States: `IDLE → SETUP (setup_time_min) → READY → RUNNING (processing_time_min) → COOLDOWN → IDLE`

Any exception during `step()` → `FAULT`. Operator calls `reset_fault()` to return to IDLE.

`MachineStateMachine(machine_id, io, db=None)` — pass a DB session to persist every transition to `MachineStateLog`.

Key API:
- `assign_job(job_id, setup_time_minutes, processing_time_minutes)` — only valid in IDLE
- `step() → MachineState` — call periodically; exception-safe
- `reset_fault()` — operator clears FAULT

DB model: `MachineStateLog` (`machine_id`, `job_id`, `from_state`, `to_state`, `occurred_at`)

### Setup Time Predictor (`backend/agents/setup_time_predictor.py`)

`RandomForestRegressor` (n_estimators=200) surrogate for changeover time prediction.

Features: `from_material (int), to_material (int), machine_id (int), hour_of_day (int), day_of_week (int)`

- `train_test_split(test_size=0.3, random_state=42)`
- Requires `MIN_TRAINING_RECORDS = 20` feedback records before switching from `SETUP_MATRIX` fallback
- Model saved to `backend/models/setup_time_predictor.pkl` via `joblib`
- Loaded automatically at startup if file exists
- `SetupTimePredictor._trained` is the gate — checked by `SchedulingTwin`

Endpoint: `GET /api/learning/setup-time-accuracy`

### Feedback Logger (`backend/agents/feedback_logger.py`)

Canonical ID: `ORD-{order_id}_M{material}_MC{machine_id}_{YYYYMMDDTHHMMSS}`

`data_provenance` values (trust ranking): `operator_logged > mtconnect_auto > estimated`

`FeedbackLogger.log(db, order_id, material, machine_id, predicted_*, actual_*, provenance)` — persists to `JobFeedbackRecord`.

`FeedbackLogger.calibration_report(db, limit=50)` — last 50 jobs, predicted vs actual, grouped by provenance.

Endpoint: `GET /api/learning/calibration-report`

DB model: `JobFeedbackRecord` (`canonical_id` unique, `order_id`, `material`, `machine_id`, `predicted_setup_minutes`, `actual_setup_minutes`, `predicted_processing_minutes`, `actual_processing_minutes`, `data_provenance`, `logged_at`)

### Scheduling Twin (`backend/agents/scheduling_twin.py`)

Narrow predict API that starts with physics defaults and upgrades to ML automatically.

- `predict_setup_time(from_material, to_material, machine_id, ...)` → uses `SetupTimePredictor` if trained, else `SETUP_MATRIX`
- `predict_completion(material, quantity, complexity, setup_time_minutes, start_time)` → uses `THROUGHPUT` constants
- `predict_on_time_probability(...)` → heuristic: ≥120 min slack → 95%, 0 min → 50%, negative → clamp 10%
- `accuracy_report(db)` → MAE for setup and processing vs `JobFeedbackRecord` actuals

`SetupTimePredictor` is a lazy module-level singleton — loaded once on first `SchedulingTwin` call.

Endpoint: `GET /api/twin/accuracy`

### Routing

- `GET /api/learning/setup-time-accuracy` → `routers/learning.py`
- `GET /api/learning/calibration-report` → `routers/learning.py`
- `GET /api/twin/accuracy` → `routers/twin.py`

Both routers registered in `main.py` after `rework_router`.

## Supplier Directory Architecture

US materials supplier database with geo-search — the data foundation for automated sourcing.

### Data Model (`backend/db_models.py` — `Supplier`)

Fields: `name, address, city, state, country, lat, lng, materials (JSON list), categories (JSON list), phone, website, email, verified (bool), data_source (str), created_at, updated_at`

`data_source` values: `pmpa | msci | manual | user_submitted`

### Agent (`backend/agents/supplier_directory.py`)

`MATERIAL_CATEGORIES` dict: `metals | wood | plastics | composites | raw_materials` → list of material strings.

`haversine_miles(lat1, lng1, lat2, lng2)` — great-circle distance in miles (Earth radius 3958.8 mi).

`SupplierDirectory` methods:
- `search(db, *, material, category, state, verified_only, skip, limit)` → `(list[Supplier], total_count)`
- `get_by_id(db, supplier_id)` → `Optional[Supplier]`
- `create(db, *, name, city, state, ...)` → `Supplier`
- `nearby(db, *, lat, lng, radius_miles, material, limit)` → `[(Supplier, distance_miles)]` sorted by distance
- `get_stats(db)` → `{total_suppliers, verified_suppliers, states_covered, state_list}`
- `list_materials()` → `{categories, all_materials}` (static)

### Endpoints (`backend/routers/suppliers.py`)

- `GET /api/suppliers` — list/search with `?material=steel&state=OH&category=metals&verified_only=true&skip=0&limit=50`
- `GET /api/suppliers/stats` — verified count + states covered (used by landing page)
- `GET /api/suppliers/materials` — full material taxonomy
- `GET /api/suppliers/nearby?lat=41.5&lng=-81.7&radius_miles=250&material=steel` — geo-sorted results
- `GET /api/suppliers/{id}` — single supplier
- `POST /api/suppliers` — user submission (verified=false, data_source="user_submitted")

### Inventory Integration (`backend/routers/inventory.py`)

`GET /api/inventory/reorder-with-suppliers?lat=...&lng=...&radius_miles=500` — reorder POs with nearest verified supplier suggestions attached. Pass lat/lng for geo-ranked results; omit for alphabetical.

### Seed Data (`backend/scripts/seed_suppliers.py`)

1,137 entries across four categories (metals 508, plastics 308, composites 160, wood 161).

Two-layer structure:
- `_STATIC_SUPPLIERS` — 101 hand-curated flagship / specialty locations (Olympic Steel, Ryerson, TW Metals, Curbell Plastics, Toray, Hexcel, Baillie Lumber, etc.)
- `_generate_suppliers()` — 1,036 entries generated by spreading 6 metal + 5 plastics + 5 wood + 4 composites chains across 150 major US cities. Deterministic (no randomness); coordinates jittered slightly per entry so co-located branches don't stack on the same pixel.

Run: `python scripts/seed_suppliers.py [--clear]`

### Frontend

- `SupplierMap.jsx` — Leaflet.js map (CDN, no API key) with `leaflet.markercluster` for performance. At country zoom, markers cluster into colored bubbles (color = dominant category); individual circle markers appear at zoom ≥ 10. Cluster icon color reflects dominant category in the group. Fetches up to 2000 suppliers in one request. Material filter input. CDN links in `index.html`.
- Sourcing section in `App.jsx` — between energy widget and tab nav. Two-column: left copy + right map. Fetches `/api/suppliers/stats` for dynamic counts.
- Supplier submission form in `ContactForm.jsx` — "Submit a supplier →" toggle in Get in Touch tab.

### Health endpoint

`material_sourcing: "directory_active"` — added as 8th touchpoint in `/health`.

## CAD Upload / ARIA-OS Integration (`backend/agents/cad_parser.py`, `backend/routers/cad.py`)

`POST /api/orders/from-cad` — accepts an STL file upload and returns extracted order parameters. This is the bridge that connects ARIA CAD output directly to the MillForge scheduling pipeline: no human translates geometry into job parameters.

**Agent (`backend/agents/cad_parser.py`):**
- `extract_from_stl(file_bytes: bytes) -> dict` — parses binary or ASCII STL via `numpy-stl`
- Bounding box dimensions from `m.vectors.reshape(-1, 3).min/max(axis=0)` → `"{x}x{y}x{z}mm"`
- `complexity = min(10, max(1, triangle_count // 1000))` — 1 complexity point per 1000 triangles, clamped to [1, 10]
- `estimated_volume_cm3 = (x * y * z) / 1000` — bounding box volume proxy in cm³

**Router (`backend/routers/cad.py`):**
- `POST /api/orders/from-cad` — `UploadFile` (`.stl` only); returns `CadParseResponse`
- 400 if non-STL extension or empty file; 422 if STL is malformed
- Response fields map directly to `OrderCreateRequest` — caller can pass result straight to `POST /api/orders`

**Schema:** `CadParseResponse` in `backend/models/schemas.py` — `dimensions`, `complexity`, `estimated_volume_cm3`, `triangle_count`, `source="stl_upload"`

**Dependency:** `numpy-stl>=3.0.0` in `backend/requirements.txt`

**Tests:** `tests/test_cad_parser.py` — dimensions/volume accuracy, complexity scaling (including clamp at 10), HTTP validation (wrong extension, empty file, valid STL)

**ARIA-OS integration note:** When ARIA generates a toolpath, it exports the stock STL to this endpoint. The response pre-fills a draft order; the operator confirms or schedules immediately. This removes the "engineer reads CAD and fills in a form" touchpoint.

## ARIA Bridge Endpoints (`backend/routers/aria_bridge.py`)

The full ARIA → MillForge handoff lives in `aria_bridge.py`. Three Pydantic schemas and 6 endpoints:

**Schemas:**
- `ARIAJobSubmission` — full CAM submission (geometry_hash required, simulation_results required). `structsight_context` optional field for StructSight engineering handoff.
- `ARIABundleSubmission` — lightweight pre-CAM bundle from an ARIA run folder. Requires only `run_id`, `goal`, `part_name`. `material`, `step_path`, `stl_path`, `geometry_hash` are all optional. `structsight_context` optional.
- `_FeedbackRequest` — post-completion QC feedback from MillForge back to ARIA.

**Endpoints:**
| Method | Path | Stage | Notes |
|--------|------|-------|-------|
| POST | `/api/jobs/from-aria` | `queued` | Full CAM submission — requires CAM toolpath + simulation |
| POST | `/api/aria/bundle` | `pending_cam` | Pre-CAM run bundle — register geometry + DFM before CAM runs |
| GET | `/api/bridge/status/{aria_job_id}` | — | Poll job progress by ARIA job ID |
| POST | `/api/bridge/feedback` | — | Push actual cycle time + QC results back to ARIA |
| GET | `/api/bridge/feedback/{aria_job_id}` | — | Retrieve stored feedback record |
| GET | `/api/bridge/progress/{aria_job_id}` | — | SSE stream of stage transitions |

**Auth:** Set `ARIA_BRIDGE_KEY` env var to require `X-API-Key` header. Leave unset in dev.

**Bundle flow (typical):**
1. ARIA completes geometry + DFM → `POST /api/aria/bundle` with `run_manifest.json` fields
2. MillForge creates Job in `pending_cam`, returns `millforge_job_id`
3. ARIA completes CAM → `POST /api/jobs/from-aria` with `extra.aria_run_id` to link
4. MillForge upgrades job to `queued`

**StructSight bridge:** Both `ARIAJobSubmission` and `ARIABundleSubmission` accept `structsight_context: dict` — a StructSight JSON response (`discipline`, `assumptions`, `verification_required`, `risk_flags`, `size_class`) stored in `cam_metadata.structsight_context` for shop-floor and scheduling context.

**Idempotency:** Both `from-aria` (keyed on `aria_job_id`) and `bundle` (keyed on `run_id`) are idempotent — re-submitting returns the existing job with `duplicate: true`.

## ARIA Schema Version Registry (`backend/services/aria_schema.py`)

MillForge auto-adapts to ARIA schema changes through a normalizer registry — no hardcoded version whitelist in the router.

**How it works:**
- `POST /api/jobs/import-from-cam` accepts raw JSON, calls `normalize(raw)` before Pydantic validation
- `normalize()` dispatches to the registered normalizer for `raw["schema_version"]`
- If no normalizer exists for that version → 400 with actionable message
- Each normalizer maps ARIA's fields to MillForge's internal `CAMImport` canonical shape

**Adding support for a new ARIA schema version (the only required step):**
```python
# backend/services/aria_schema.py

def _normalize_v2(raw: dict) -> dict:
    out = dict(raw)
    _rename(out, "target_machine", "machine_name")       # example rename
    _rename(out, "cycle_time_minutes", "cycle_time_min_estimate")
    out["schema_version"] = "1.0"  # normalise to internal canonical version
    return out

NORMALIZERS: dict[str, Callable[[dict], dict]] = {
    "1.0": _normalize_v1,
    "2.0": _normalize_v2,   # add this line
}
```
Deploy MillForge with the new normalizer **before** deploying the ARIA version that emits it.

**Startup compatibility probe:**
- `check_aria_compatibility()` runs in the FastAPI lifespan
- If `ARIA_API_BASE` env var is set, it calls `GET {ARIA_API_BASE}/schema-version`
- If ARIA reports a version MillForge has no normalizer for → `WARNING` log, never crashes
- If `ARIA_API_BASE` is unset → skipped silently

**Key rule:** `services/aria_schema.py` is the only place version knowledge lives. The router (`routers/jobs.py`) and the Pydantic model (`CAMImport`) are version-agnostic.

**Contract file:** `contracts/cam_setup_schema_v1.json` — JSON Schema draft-07 for the v1.0 canonical shape. Update alongside `CAMImport` when the internal canonical shape changes. The test `test_cam_import_validates_against_json_schema` validates against it.

## Manufacturing Abstraction Layer (`backend/manufacturing/`)

Process-agnostic manufacturing intelligence layer that enables MillForge to support multiple fabrication processes beyond CNC milling — welding, cutting, bending, stamping, EDM, molding, inspection, and robotics.

### Architecture

```
backend/manufacturing/
  __init__.py           — package root; exports all public classes
  ontology.py           — core type system: ProcessFamily (32 variants), MaterialSpec, ManufacturingIntent, ProcessPlan
  registry.py           — thread-safe singleton ProcessRegistry + ProcessAdapter protocol + MachineCapability
  routing.py            — RoutingEngine: 4-factor weighted scoring (cost/time/quality/energy), multi-step routing
  work_order.py         — WorkOrder + WorkOrderStep with 12-state FSM
  validation.py         — cross-cutting validators for intent, work order, process steps
  simulation.py         — CycleTimeEstimator, CostEstimator, FeasibilityChecker
  bridge.py             — bridges new layer to existing scheduler/energy agents (backward-compatible)
  adapters/
    base_adapter.py     — BaseAdapter ABC; re-exports SETUP_MATRIX, THROUGHPUT for backward compat
    cnc_milling.py      — CNCMillingAdapter: wraps legacy scheduler constants in adapter pattern
    welding.py          — ArcWeldingAdapter, LaserWeldingAdapter, EBWeldingAdapter (travel-speed throughput)
    bending.py          — PressBrakeAdapter: tonnage formula, springback compensation, bend deduction
    cutting.py          — LaserCuttingAdapter, PlasmaCuttingAdapter, WaterjetCuttingAdapter
    stamping.py         — StampingAdapter: high-volume die-based, SPM throughput
    edm.py              — WireEDMAdapter, SinkerEDMAdapter: MRR-based throughput, dielectric consumption
    molding.py          — InjectionMoldingAdapter: polymer/MIM, high batch minimums
    inspection.py       — CMMInspectionAdapter, VisionInspectionAdapter, XRayInspectionAdapter (post-process)
```

### Key Concepts

**ProcessFamily** — 32 enum variants covering all major manufacturing processes. Grouped into **ProcessCategory** (SUBTRACTIVE, ADDITIVE, JOINING, FORMING, CASTING_MOLDING, INSPECTION, MATERIAL_HANDLING, THERMAL, FINISHING, ASSEMBLY).

**ManufacturingIntent** — describes *what* needs to be made: part ID, material spec, quantity, quality requirements, due date, cost target. Process-agnostic — the routing engine decides *how*.

**ProcessAdapter** — abstract protocol that each process family implements:
- `validate_intent(intent) → List[str]` — validation errors
- `estimate_cycle_time(intent, machine) → float` — minutes
- `estimate_cost(intent, machine) → float` — USD
- `generate_setup_sheet(intent, machine) → Dict` — process-specific setup instructions
- `get_consumables(intent) → Dict[str, float]` — material_name → kg consumed
- `get_energy_profile(intent, machine) → EnergyProfile`

**ProcessRegistry** — thread-safe singleton holding all registered adapters and machines. Supports `find_capable_machines(process_family, material)` for routing.

**RoutingEngine** — `route(intent) → RoutingResult` — finds all capable process/machine combinations, scores them on 4 weighted factors (cost 0.3, time 0.3, quality 0.25, energy 0.15), returns ranked options.

**Bridge module** (`bridge.py`) — backward-compatible functions:
- `order_to_intent(order)` / `intent_to_order(intent)` — convert between legacy Order and ManufacturingIntent
- `setup_matrix_from_registry(registry, from_mat, to_mat)` — adapter-first, falls back to SETUP_MATRIX
- `throughput_from_registry(registry, material)` — adapter-first, falls back to THROUGHPUT dict
- `bootstrap_registry()` — registers all 16 built-in adapters, returns singleton
- `register_db_machines(registry, db)` — reads Machine table → MachineCapability objects

### REST API (`backend/routers/manufacturing.py`)

**Prefix:** `/api/manufacturing`

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/manufacturing/health` | GET | Registry stats: adapter count, machine count, supported processes |
| `/api/manufacturing/processes` | GET | List all registered process families with adapter capabilities |
| `/api/manufacturing/machines` | GET | List all registered machines with capabilities |
| `/api/manufacturing/route` | POST | Route a ManufacturingIntent — returns scored options |
| `/api/manufacturing/feasibility` | POST | Feasibility check for an intent |
| `/api/manufacturing/validate` | POST | Validate an intent, return errors |
| `/api/manufacturing/work-order` | POST | Create a WorkOrder from intent + selected route |
| `/api/manufacturing/work-orders` | GET | List work orders (placeholder) |
| `/api/manufacturing/estimate` | POST | Cycle time + cost estimate for intent + process |

### Startup Integration

In `main.py` lifespan, after inventory/supplier init:
1. `bootstrap_registry()` registers all 16 adapters
2. `register_db_machines(registry, db)` syncs Machine table to registry
3. Registry passed to manufacturing router via `set_registry()`

### Adding a New Process Adapter

1. Create `backend/manufacturing/adapters/my_process.py` with a class extending `BaseAdapter`
2. Set `process_family` property to the target `ProcessFamily` enum value
3. Implement `validate_intent()`, `estimate_cycle_time()`, `estimate_cost()`, `generate_setup_sheet()`, `get_consumables()`, `get_energy_profile()`
4. Register in `bridge.py:bootstrap_registry()` — one line: `MyAdapter()`
5. Add tests to `tests/test_manufacturing_*.py`

The adapter will be automatically available to the routing engine and REST API.

### ARIA Schema v2 (Multi-Process)

`services/aria_schema.py` now supports v2.0 with multi-process fields:
- `process_type` (string) — e.g. "cnc_milling", "welding_arc", "bending_press_brake"
- `process_parameters` (dict) — generic process-specific params
- `consumables` (list) — filler wire, shielding gas, etc.
- `quality_standards` (list) — e.g. ["AWS D1.1", "ASME IX"]
- `energy_profile` (dict) — base_power_kw, peak_power_kw

v1 payloads still work unchanged. v2 normalizer defaults missing `process_type` to "cnc_milling".

Contract file: `contracts/cam_setup_schema_v2.json`

### Tests

173 tests across 6 test files covering ontology, registry, routing, adapters (CNC + welding + bending), validation, and simulation. All pass in <0.3s.

```bash
python -m pytest tests/test_manufacturing_*.py -v  # run manufacturing tests
```

### Key Rules

1. **Never break the bridge** — `bridge.py` fallback paths must always work even if adapters are not registered
2. **Adapter isolation** — each adapter is self-contained; no cross-adapter imports
3. **Registry is lazy** — adapters registered at startup, but the registry works with zero adapters (empty results, no crashes)
4. **Thread-safe** — ProcessRegistry uses threading.Lock for all mutations

## Customer Discovery Module (`backend/discovery/`, `frontend/src/pages/Discovery.jsx`)

Internal tool for logging, extracting, and synthesizing customer interview data. Not a lights-out touchpoint — built for YC prep and product validation.

### Architecture

```
backend/discovery/
  __init__.py       — package init
  models.py         — SQLAlchemy models: Interview, Insight, DiscoveryPattern
  agent.py          — Ollama LLM agent (llama3.2 default) for extraction + synthesis
  prompts.py        — all system prompts isolated here for easy iteration
  routes.py         — FastAPI router, prefix /api/discovery, 7 endpoints
```

### DB Models

- `Interview` — contact_name, shop_name, shop_size (1-5|6-20|21-100|100+), role, date, raw_transcript; has_many Insights (cascade delete)
- `Insight` — interview_id (FK), category (pain_point|current_tool|wtp_signal|workflow|quote), content, severity (1-3), quote
- `DiscoveryPattern` — label, insight_ids (JSON), frequency (0.0-1.0), evidence_quotes (JSON), feature_tag (scheduling|quoting|supplier|defect_detection|energy|onboarding|other)

### Endpoints

- `POST /api/discovery/interviews` — persist interview + run Ollama insight extraction
- `GET /api/discovery/interviews` — list with insight counts
- `GET /api/discovery/interviews/{id}` — full detail with insights
- `DELETE /api/discovery/interviews/{id}` — cascade delete
- `POST /api/discovery/synthesize` — clear old patterns, run cross-interview synthesis via Ollama
- `GET /api/discovery/patterns` — ordered by frequency desc
- `GET /api/discovery/next-questions` — generate 5 targeted questions via Ollama

All endpoints require JWT auth (httpOnly cookie). Frontend tab visible only when logged in.

### Ollama LLM Agent (`backend/discovery/agent.py`)

- Uses Ollama HTTP API directly (no SDK dependency)
- Model: `llama3.2:latest` (configured via `OLLAMA_MODEL` env var, default `llama3.2:latest`)
- Ollama URL: `http://localhost:11434` (configured via `OLLAMA_URL` env var)
- All three functions (`extract_insights`, `synthesize_patterns`, `generate_next_questions`) fail silently — return `[]` or fallback on any error
- JSON code-fence stripping + leading-prose skip in `_parse_json()`
- **Important**: `llava` and `llava-llama3` are vision models — unreliable for JSON extraction. Always use `llama3.2` or better for this agent.

### Local dev setup

```bash
ollama pull llama3.2          # one-time
# backend/.env:
OLLAMA_MODEL=llama3.2
OLLAMA_URL=http://localhost:11434
```

### Frontend

`Discovery.jsx` — 3-tab page (Log Interview / Patterns / Next Questions). Available in `AUTH_TABS` after login. Calls all `/api/discovery/*` endpoints with `credentials: "include"`.
