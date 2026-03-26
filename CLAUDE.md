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
