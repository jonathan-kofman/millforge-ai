# MillForge Development Roadmap

## Phase 0 – POC (Current) ✅

**Goal:** Working demo that proves the core value proposition.

- [x] FastAPI backend with quote, schedule, vision, contact endpoints
- [x] EDD scheduler with sequence-dependent setup times
- [x] React frontend with Gantt chart, quote form, vision demo
- [x] Docker Compose for one-command local startup
- [x] Pytest test suite for scheduler

---

## Phase 1 – Real Scheduling Algorithm

**Goal:** Replace heuristic with a provably optimal or near-optimal algorithm.

- [ ] Implement MILP formulation using OR-Tools or PuLP
  - Objective: minimize total weighted tardiness
  - Constraints: machine capacity, setup times, due dates
- [ ] Benchmark MILP vs EDD on 50/100/500 order instances
- [ ] Add Gantt chart time-window zoom in frontend
- [ ] Add order editing UI (priority overrides, due date adjustments)

---

## Phase 2 – Persistent Storage

**Goal:** Store orders, schedules, and inspection results.

- [ ] Add PostgreSQL via SQLAlchemy + Alembic migrations
- [ ] Order CRUD endpoints (`GET /api/orders`, `PATCH /api/orders/{id}`)
- [ ] Schedule history (store and retrieve past runs)
- [ ] Inspection result log with image thumbnail storage (S3/MinIO)

---

## Phase 3 – Real Quality Vision

**Goal:** Replace mock vision with a working CV model.

- [ ] Collect/label 500+ part images across 4 materials
- [ ] Fine-tune YOLOv8-nano on defect detection dataset
- [ ] Export to ONNX and load in `QualityVisionAgent`
- [ ] Add severity scoring (critical / major / minor)
- [ ] Integrate with schedule: flag orders with failed parts for rework scheduling

---

## Phase 4 – Energy Optimization

**Goal:** Measurably reduce energy cost through intelligent job shifting.

- [ ] Integrate EIA or Electricity Maps API for real-time pricing
- [ ] Capture machine power draw via OPC-UA or MQTT simulator
- [ ] Add energy cost to schedule optimization objective function
- [ ] Dashboard: energy cost per order, carbon intensity score

---

## Phase 5 – LLM Planning Layer

**Goal:** Natural language interface to the scheduling and planning engine.

- [ ] Integrate Claude (Anthropic) or GPT-4 as planning co-pilot
- [ ] Accept plain-English scheduling requests ("rush the aerospace orders")
- [ ] LLM generates schedule explanations for operators
- [ ] Anomaly detection: LLM flags unusual order patterns

---

## Phase 6 – Production Hardening

**Goal:** Ready for real pilot deployment.

- [ ] Auth (JWT, role-based: operator / manager / admin)
- [ ] Rate limiting and API key management
- [ ] Kubernetes deployment manifests (Helm chart)
- [ ] CI/CD pipeline (GitHub Actions: test → build → push → deploy)
- [ ] Monitoring: Prometheus metrics, Grafana dashboard
- [ ] Load testing: 1,000 orders / minute
