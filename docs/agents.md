# MillForge Agent Modules

Each agent is a self-contained Python class in `backend/agents/`. Agents have no FastAPI dependency — they are pure business logic.

---

## 1. Scheduler (`agents/scheduler.py`)

**Purpose:** Optimize production order sequencing to minimize lateness and maximize machine utilization.

**Current Algorithm:** Modified Earliest Due Date (EDD)
- Sort orders by (due_date, priority, complexity)
- Assign each order to the machine with the earliest available time (greedy)
- Add sequence-dependent setup time based on material changeover matrix
- Calculate realistic processing time from material throughput rates

**Key Inputs:**
- `List[Order]` — order_id, material, quantity, dimensions, due_date, priority, complexity
- `start_time` — when production can begin

**Key Outputs:**
- `Schedule` — per-order assignment with machine_id, setup/processing/completion times, on-time flag

**Extension Path:**
- Replace greedy machine assignment with Integer Linear Program (PuLP/OR-Tools)
- Add genetic algorithm for large-scale instances (>100 orders)
- Integrate LLM for natural language priority overrides ("rush the aerospace parts")
- Connect to real machine sensor data for live availability

---

## 2. Quality Vision Agent (`agents/quality_vision.py`)

**Purpose:** Inspect manufactured parts for defects via computer vision.

**Current State:** Mock — returns simulated pass/fail with random confidence and defect labels.

**Defect Categories Modeled:**
- surface_crack, porosity, dimensional_deviation, surface_roughness, inclusions, delamination

**Key Interface:**
```python
agent.inspect(image_url: str, material: str) -> InspectionResult
```

**Extension Path:**
- Load YOLOv8 or ViT model from ONNX registry
- Pre-process: resize to model input, normalize, convert colorspace
- Post-process: map bounding box detections to defect categories with severity
- Add per-material threshold calibration
- Stream results to traceability database (order → inspection → part serial)

---

## 3. Energy Optimizer (`agents/energy_optimizer.py`)

**Purpose:** Minimize energy cost and carbon footprint by shifting non-critical jobs to off-peak windows.

**Current State:** Heuristic using simulated 24-hour pricing curve.

**Key Interface:**
```python
optimizer.estimate_energy_cost(start_time, duration_hours, material) -> EnergyProfile
optimizer.get_optimal_start_windows(duration_hours, material) -> List[Dict]
```

**Extension Path:**
- Integrate grid pricing API (CAISO, ERCOT, EnergyHub day-ahead prices)
- Fetch machine-level power draw from OPC-UA/MQTT sensor telemetry
- Add carbon intensity score (gCO₂/kWh) from Electricity Maps API
- Formulate as MILP: minimize cost subject to due-date constraints

---

## 4. Production Planner (Planned)

**Purpose:** High-level planning agent that interprets customer demand signals and sets capacity targets.

**Planned Interface:**
```python
planner.plan_week(demand_forecast, capacity) -> WeeklyPlan
```

- Will use LLM (Claude/GPT) to translate natural language demand signals
- Generates rough-cut capacity plans before detailed scheduling

---

## 5. Inventory Agent (Planned)

**Purpose:** Track raw material inventory and trigger procurement when stock falls below safety levels.

- Monitor material consumption from the schedule
- Generate purchase orders when reorder points are hit
- Integrate with ERP systems (SAP, Epicor) via REST
