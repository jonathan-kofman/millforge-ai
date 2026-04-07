# McKinsey/QuantumBlack Agentic AI Patterns -- MillForge Analysis

**Sources analyzed (April 2026):**
1. [One Year of Agentic AI: Six Lessons from the People Doing the Work](https://www.mckinsey.com/capabilities/quantumblack/our-insights/one-year-of-agentic-ai-six-lessons-from-the-people-doing-the-work) -- QuantumBlack, Sep 2025
2. [Agentic Workflows for Software Development (SDD)](https://medium.com/quantumblack/agentic-workflows-for-software-development-dc8e64f4a79d) -- QuantumBlack, Feb 2026
3. [Seizing the Agentic AI Advantage](https://www.mckinsey.com/capabilities/quantumblack/our-insights/seizing-the-agentic-ai-advantage) -- McKinsey, Jun 2025
4. [The Change Agent: Goals, Decisions, and Implications for CEOs in the Agentic Age](https://www.mckinsey.com/capabilities/quantumblack/our-insights/the-change-agent-goals-decisions-and-implications-for-ceos-in-the-agentic-age) -- McKinsey, Oct 2025

**Purpose:** Map McKinsey's agentic AI findings to MillForge's 28-agent architecture for job shop manufacturing. Inform YC S26 narrative (deadline May 4, 2026).

---

## 1. The Six Lessons -- Mapped to MillForge

McKinsey distilled 50+ agentic AI builds into six lessons. Each is mapped below to MillForge's current architecture.

### Lesson 1: It's Not About the Agent -- It's About the Workflow

**McKinsey:** Agentic AI efforts that focus on fundamentally reimagining entire workflows -- the steps involving people, processes, and technology -- are more likely to deliver positive outcomes. Organizations that focus on building impressive agents without redesigning the surrounding workflow end up with "great-looking agents that don't actually improve the overall workflow, resulting in underwhelming value."

**MillForge mapping:** This is MillForge's core thesis. The product does not bolt an AI scheduler onto an existing whiteboard process. It reimagines the entire job shop workflow: quoting triggers scheduling, scheduling feeds energy optimization, quality inspection feeds rework dispatch, rework feeds back into the schedule. The "lights-out" framing -- eliminating human touchpoints from routine production -- is exactly the workflow-first thinking McKinsey recommends. The 10-touchpoint hierarchy (scheduling -> quoting -> quality triage -> anomaly detection -> rework -> energy -> inventory -> sourcing -> planning -> exception handling) is a complete workflow map, not a list of disconnected agents.

**Gap:** MillForge should articulate the full end-to-end workflow more explicitly in demos and YC materials. The benchmark currently showcases scheduling in isolation (FIFO vs EDD vs SA). A demo showing the full chain -- order arrives, anomaly gate holds bad orders, schedule runs, energy windows applied, vision inspects output, rework auto-dispatched -- would be more compelling and directly aligned with this lesson.

### Lesson 2: Agents Aren't Always the Answer

**McKinsey:** Not every task needs an AI agent. Simple, rule-based work benefits from traditional automation. Decision factors include input variance, required judgment, process stability, and evolving requirements. Often simpler approaches like automation, rules, or analytics are more effective.

**MillForge mapping:** MillForge already practices this implicitly. The anomaly detector uses deterministic rules (duplicate ID check, impossible deadline check), not an LLM. The setup time matrix is a lookup table. The inventory reorder agent uses threshold logic. The SA scheduler is a metaheuristic, not a language model. Only the NL scheduler and production planner are intended to use LLMs, and both are deferred/mock.

**Gap:** Make this explicit in architecture docs. Label each of the 28 modules by technology type: deterministic rule, optimization algorithm, ML model, LLM agent. This classification strengthens the YC pitch ("we use the right tool for each job, not LLMs everywhere") and aligns with McKinsey's guidance.

### Lesson 3: Stop "AI Slop" -- Invest in Evaluations and Build Trust

**McKinsey:** Users encounter disappointing quality outputs ("AI slop") that rapidly erode trust and kill adoption. Addressing this requires substantial investment in evaluation, mirroring employee development practices. Agents should be given "clear job descriptions, onboarded, and given continual feedback."

**MillForge mapping:** The scheduling twin architecture (machine state machine -> setup time predictor -> feedback logger -> scheduling twin) is a direct implementation of this principle. The feedback logger captures predicted vs actual times with provenance tracking. The setup time predictor retrains from real data once 20+ feedback records accumulate. The calibration report endpoint exposes prediction accuracy. This is the "continual feedback" McKinsey describes.

**Gap:** Quality vision is the weak link. The NEU-DET YOLOv8n model (mAP50=0.759) is deployed but has no feedback loop from operators. When a human overrides an inspection result, that correction should feed back into model fine-tuning. Build a vision feedback endpoint: `POST /api/vision/feedback` with `{inspection_id, operator_verdict, notes}`.

### Lesson 4: Make It Easy to Track and Verify Every Step

**McKinsey:** As agent deployments scale, tracking becomes critical. Embedding monitoring and evaluation at each workflow step enables teams to catch errors early, refine logic, and continuously improve post-deployment.

**MillForge mapping:** The `/health` endpoint returns a `lights_out_readiness` object showing automated/mock/not-implemented status for each touchpoint. The anomaly report is included in every schedule response. The calibration report tracks prediction accuracy. Energy analysis includes `data_source` fields distinguishing real API data from fallback mocks.

**Gap:** MillForge lacks an agent observability layer. There is no centralized log of which agents ran, what they decided, and how long they took for a given order. A simple `AgentExecutionLog` table (order_id, agent_name, decision, latency_ms, timestamp) would close this gap and enable the kind of step-by-step verification McKinsey recommends. This also supports the manufacturing audit trail customers expect.

### Lesson 5: The Best Use Case Is the Reuse Case

**McKinsey:** Creating unique agents for each individual task generates redundancy. Developing reusable agents capable of handling different tasks sharing similar actions (ingesting, extracting, searching, analyzing) improves efficiency and scalability.

**MillForge mapping:** The Manufacturing Abstraction Layer is a textbook implementation. The `ProcessAdapter` protocol lets 16 adapters (CNC milling, welding, bending, cutting, stamping, EDM, molding, inspection) share the same interface: `validate_intent()`, `estimate_cycle_time()`, `estimate_cost()`, `generate_setup_sheet()`. The `RoutingEngine` scores all capable process/machine combinations using the same 4-factor model. One routing engine, many process types.

**Gap:** The bridge module (`bridge.py`) that connects the manufacturing layer to the legacy scheduler is the right pattern but could be extended. The quote endpoint, energy optimizer, and rework dispatcher all contain duplicated material-handling logic that could be consolidated through the adapter pattern.

### Lesson 6: Humans Remain Essential -- But Roles Change

**McKinsey:** People continue performing critical functions: overseeing accuracy, ensuring compliance, applying judgment, and managing edge cases. While agent capabilities expand, humans remain indispensable. Companies should be deliberate in redesigning work so people and agents collaborate well.

**MillForge mapping:** The lights-out hierarchy explicitly reserves "exception handling" as the human domain. The anomaly gate holds critical orders for human review rather than auto-scheduling them. The vision system triages (first-pass inspection) but doesn't make final accept/reject decisions on borderline parts. The discovery module is built entirely for human use (interview logging, pattern synthesis).

**Gap:** MillForge should define the human exception interface more concretely. What does the exception queue look like? What information does a human need to resolve a held order? The `exception_queue.py` agent exists but the frontend UX for exception resolution is underdeveloped. This is the "last mile" that McKinsey says determines adoption.

---

## 2. Spec-Driven Development (SDD) Pattern

**Source:** Article 2 -- QuantumBlack's Medium post on agentic workflows for software development.

### The Two-Layer Model

QuantumBlack's SDD architecture separates concerns into two layers:

**Orchestration Layer (Deterministic):**
- Phase enforcement: requirements must complete before tasks generate; architecture must be reviewed before implementation starts
- Dependency management: tasks execute only when prerequisites are satisfied
- State tracking: each artifact carries a state machine (draft -> in-review -> approved -> complete)
- Triggered execution: "When REQ-001 is approved, generate technical tasks" rather than agent self-direction
- Key insight: Early experiments showed agents would skip steps, create circular dependencies, or enter analysis loops when given meta-level workflow choices

**Execution Layer (Bounded Agents):**
- Specialized agents: requirements analyst, architecture designer, coding specialist, knowledge query agent
- Structured outputs: all artifacts follow templates with consistent structure and metadata
- Two-stage validation: deterministic checks first (linters, structural validation), then critic agent validates judgment calls
- Iteration bounds: agents get 3-5 attempts to pass evaluations; failures escalate for human intervention

### Comparison with MillForge's Architecture

| Aspect | SDD Pattern | MillForge Current | Assessment |
|--------|-------------|-------------------|------------|
| Orchestration | Deterministic workflow engine enforces phase ordering | FastAPI routers chain agents procedurally (e.g., anomaly gate -> scheduler -> energy analysis) | Partial match. MillForge's orchestration is implicit in router code, not a separate engine. Works at current scale but won't scale to complex multi-step jobs. |
| Agent boundaries | Each agent has explicit input/output contracts, iteration limits, and failure escalation | Agents have stable interfaces (`optimize()`, `inspect()`, `detect()`) but no iteration limits or escalation | Gap. No retry/escalation pattern. If the scheduler fails, the request fails. |
| Validation | Two-stage: deterministic checks + critic agent | Anomaly detector is a deterministic pre-check. No critic/quality gate on agent outputs. | Gap. Schedule quality is not validated -- a technically valid but poor schedule passes through. |
| State tracking | Each artifact has a state machine with frontmatter | Orders have status field (pending/scheduled). No state machine for the overall job lifecycle. | Gap. Need a WorkOrder FSM (the manufacturing layer has one but it's not wired to the main flow). |
| Knowledge management | Dedicated knowledge agent handles uncertainty; assumptions logged as reviewable items | No centralized knowledge system. Each agent has its own constants and lookup tables. | Gap. As the system grows, a shared knowledge layer (material properties, machine capabilities, customer preferences) would prevent drift between agents. |
| Git as state store | Commits represent completed phases | DB-backed with SQLAlchemy. Schedule runs persisted. | Acceptable. DB is the right choice for manufacturing -- git-as-state is software-dev-specific. |

### Key SDD Insight for MillForge

The SDD model's most transferable principle: **"The orchestration runs around the agents. Agents don't decide what phase we're in or what comes next; they execute tasks given to them by the workflow engine."**

MillForge should build a lightweight job lifecycle engine that:
1. Receives an order (or CAD upload or ARIA import)
2. Runs it through a defined sequence: validation -> anomaly gate -> scheduling -> energy optimization -> production -> inspection -> rework (if needed) -> completion
3. Tracks state transitions in a `JobLifecycleLog`
4. Allows human override at any gate
5. Never lets an agent decide what happens next -- the engine decides

This is more robust than the current approach where each router manually chains the right agents.

---

## 3. Workflow Redesign Principles

**Source:** Articles 1, 3, and 4.

### McKinsey's Central Finding

Nearly eight in ten companies report using gen AI -- yet just as many report no significant bottom-line impact. McKinsey attributes this to "scattered pilots" rather than end-to-end process reinvention.

The critical distinction:
- **Task automation:** Layering AI onto an existing process. The agent becomes a faster assistant within the same sequential, rule-bound workflow shaped by human constraints. Sufficient for standardized, low-variance workflows (payroll, password resets).
- **Process reinvention:** Rearchitecting the entire task flow from the ground up. Reordering steps, reallocating responsibilities between humans and agents, designing for parallel execution, real-time adaptability, and elastic capacity.

### How MillForge Aligns

MillForge is process reinvention, not task automation. Evidence:

1. **Reordered steps:** Traditional flow is quote -> accept -> schedule -> produce -> inspect. MillForge's flow adds anomaly detection before scheduling, energy optimization during scheduling, and automatic rework dispatch after inspection. Steps that didn't exist in the manual process.

2. **Reallocated responsibilities:** Scheduling moves from a single human to an algorithm. Quality triage moves from an inspector's eye to computer vision. Energy timing moves from "run when the machine is free" to "run when electricity is cheapest."

3. **Parallel execution:** The SA scheduler evaluates thousands of permutations in parallel. The routing engine scores all capable process/machine combinations simultaneously. These are not sequential human decisions sped up -- they are fundamentally parallel computations that a human cannot perform.

4. **Real-time adaptability:** The scheduling twin retrains from feedback data. Energy pricing adapts to real-time PJM demand. These adapt to changing conditions without human intervention.

### Where MillForge Can Strengthen Alignment

McKinsey notes that manufacturing lead times can shrink 20-30% with agentic process reinvention. MillForge's benchmark shows a 35.7pp improvement in on-time delivery (FIFO 60.7% -> SA 96.4%). This is even stronger than McKinsey's cited range and should be front-and-center in the YC application.

The gap: MillForge hasn't yet measured end-to-end cycle time reduction (from order receipt to shipment). The scheduling improvement is proven; the full workflow improvement (including automated quoting, anomaly gating, rework) needs to be quantified as a single number.

---

## 4. Learning Loops

### McKinsey's Framework

McKinsey describes feedback mechanisms as a "self-reinforcing system": the more frequently agents are used, the smarter and more aligned they become. Key elements:
- Agents require adaptive mechanisms capturing human corrections, usage patterns, and exceptions
- These refine prompts, knowledge bases, and decision logic progressively
- Monitoring and evaluation must be embedded at each workflow step
- Agent performance should be verified, not assumed

### MillForge's Learning Architecture

The scheduling twin is MillForge's primary learning loop:

```
Production Floor -> Feedback Logger -> JobFeedbackRecord (DB)
                                            |
                                            v
                                    Setup Time Predictor
                                    (RandomForest, n=200)
                                            |
                                            v
                                    Scheduling Twin
                                    (predict_setup_time)
                                            |
                                            v
                                    Scheduler (SA/EDD)
                                            |
                                            v
                                    Production Floor (loop)
```

Data provenance is tracked: `operator_logged > mtconnect_auto > estimated`. The predictor requires 20+ feedback records before switching from static lookup to ML prediction.

### Mapping to Manufacturing Customer Discovery

McKinsey's learning loop concept maps directly to MillForge's customer discovery process:

1. **Discovery interviews** -> Insight extraction (Ollama agent) -> Pattern synthesis -> Feature prioritization
2. **Pilot deployments** -> Operator feedback -> Calibration reports -> Model retraining
3. **Production use** -> Continuous feedback logging -> Scheduling twin improvement -> Better predictions

The discovery module (`backend/discovery/`) is itself a learning loop for the product, not just for the agents. Interview insights feed feature prioritization, which feeds the next interview's questions. This is the meta-learning loop that McKinsey says separates companies that learn from those that repeat mistakes.

### Gap: Vision Learning Loop

The quality vision agent has no learning loop. Operator overrides (accept a part the model rejected, or reject a part the model passed) are not captured. This is the highest-impact gap because vision inspection is a safety-critical function where trust depends on continuous improvement.

---

## 5. Manufacturing and Industrial Case Studies

### From McKinsey's 50+ Builds

McKinsey's articles reference several manufacturing-adjacent case studies:

1. **Manufacturing lead time compression:** Companies using agentic AI in manufacturing or product development see lead times shrink 20-30%. "Deciding how to translate initial product design into configuration of a manufacturing line and how to break down the different steps into an assembly process can be done in days or weeks with agentic AI" rather than months.

2. **Supply chain orchestration:** An AI agent "could continuously forecast demand, identify risks, and automatically reallocate inventory across warehouses while negotiating with external systems, improving service levels while reducing costs." MillForge's inventory agent + supplier directory partially implements this pattern.

3. **Procurement optimization:** Early movers see significant impact in procurement, where traditional AI (spend cubes, cost breakdowns) can be enhanced with agents. MillForge's supplier directory (1,100+ US suppliers with geo-search) is the data foundation for this.

4. **Incident resolution:** Up to 80% of common incidents resolved autonomously, with 60-90% reduction in time to resolution. MillForge's anomaly gate + rework dispatcher is an analogous pattern for production incidents.

5. **IT operations (analogous):** Service management workflows with agents that triage, diagnose, and resolve issues -- structurally identical to MillForge's quality triage -> rework dispatch pipeline.

### Notable Absence

McKinsey does not cite a specific job shop scheduling case study from their 50+ builds. This is an opportunity: MillForge could be the reference implementation they don't yet have for discrete manufacturing scheduling. The 35.7pp on-time delivery improvement is a result worth publishing.

---

## 6. YC-Relevant Insights

### Paraphrased Insights for the YC S26 Narrative

**1. Workflow redesign beats tool bolting.** McKinsey found across 50+ builds that agentic AI projects focused on reimagining entire workflows consistently outperform those that bolt agents onto existing processes. MillForge doesn't add AI to the whiteboard -- it replaces the whiteboard with a complete intelligence layer that reimagines every step from order intake to shipment.

**2. Domain expertise is the moat.** McKinsey emphasizes that successful agentic deployments require deep understanding of the specific workflow being transformed. MillForge embeds manufacturing-specific knowledge throughout: setup time matrices for material changeovers, throughput rates by material type, complexity multipliers, sequence-dependent scheduling constraints. This domain encoding is not something a horizontal AI platform can replicate without years of shop floor exposure.

**3. The market is in the "trough of disillusionment" -- and that's an opportunity.** McKinsey notes that nearly 80% of companies using gen AI report no significant bottom-line impact, and some are rehiring people where agents failed. CEOs are frustrated. The companies that push through this trough with real, measurable results will capture disproportionate value. MillForge's deterministic benchmark (35.7pp on-time improvement, reproducible every run) cuts through the hype.

**4. Manufacturing is seeing 20-30% lead time reduction with agentic AI.** McKinsey cites this range across manufacturing implementations. MillForge's scheduling improvement alone exceeds this. With full workflow automation (quoting + scheduling + energy + quality + rework), the compounding effect should be significantly larger. This validates the market opportunity.

**5. The "right tool for the right job" principle separates winners from losers.** McKinsey's second lesson -- agents aren't always the answer -- validates MillForge's architecture of mixing deterministic rules, optimization algorithms, ML models, and LLM agents rather than making everything an LLM call. This is engineering discipline, not AI hype.

---

## 7. Architecture Comparison Table

| Pattern | McKinsey Recommendation | MillForge Current State | Gap / Action |
|---------|------------------------|------------------------|--------------|
| **Workflow-first design** | Reimagine entire workflows, not just individual tasks. Map all steps involving people, processes, and technology. | 10-touchpoint lights-out hierarchy. Full chain: order -> anomaly gate -> schedule -> energy -> inspect -> rework. | Build an end-to-end demo showing the full chain, not just scheduling in isolation. Quantify total cycle time reduction. |
| **Selective agent use** | Use the right technology for each task: rules, optimization, ML, or LLM agents. Don't default to agents everywhere. | Mix of deterministic rules (anomaly detector), optimization (SA scheduler), ML (vision YOLOv8n, setup time RF), and LLM (discovery agent). | Explicitly label each module's technology type in docs and pitch materials. |
| **Deterministic orchestration** | Separate orchestration (deterministic) from execution (bounded agents). Agents should not decide workflow sequencing. | Orchestration is implicit in router code. Anomaly gate -> scheduler -> energy is hardcoded in the schedule router. | Build a lightweight job lifecycle engine. Define the state machine explicitly. Wire the WorkOrder FSM from the manufacturing layer into the main flow. |
| **Evaluation and trust** | Invest in agent evaluation. Two-stage validation: deterministic checks + quality assessment. Iteration limits with human escalation. | Anomaly detector is a pre-check. Calibration report tracks prediction accuracy. No output quality gate on schedules. | Add a schedule quality validator (e.g., reject schedules where >20% of orders are late when a better solution exists). Add iteration limits to the SA scheduler with escalation. |
| **Observability** | Track and verify every step. Embed monitoring at each workflow stage. | `/health` endpoint. `data_source` fields. Calibration reports. No centralized agent execution log. | Build `AgentExecutionLog` table. Log agent name, decision, latency, order_id for every execution. Expose via `/api/observability/trace/{order_id}`. |
| **Learning loops** | Feedback mechanisms create self-reinforcing improvement. Capture human corrections, usage patterns, exceptions. | Scheduling twin: feedback logger -> setup time predictor -> retraining. Data provenance tracking. | Add vision feedback loop (operator overrides). Add quoting feedback loop (actual vs quoted lead time). Wire discovery insights into feature prioritization programmatically. |
| **Reusable components** | Build reusable agents that share common actions (ingest, extract, search, analyze). Avoid unique agents per task. | Manufacturing Abstraction Layer: 16 adapters sharing `ProcessAdapter` protocol. Routing engine reusable across all process types. | Extend adapter pattern to quote and energy modules. Consolidate duplicated material-handling logic through shared adapters. |
| **Human exception handling** | Redesign work so people and agents collaborate. Define clear handoff points. Humans handle judgment, compliance, edge cases. | Exception handling is the 10th touchpoint, explicitly reserved for humans. Anomaly gate holds critical orders. | Build the exception resolution UX. Define what information humans need at each handoff point. Design the operator dashboard for held orders and borderline inspections. |
| **Agentic AI Mesh** | Composability, distributed intelligence, layered decoupling, vendor neutrality, governed autonomy. | Agents are plain Python classes with no framework dependency. ProcessRegistry is thread-safe. Bridge module decouples layers. | Formalize inter-agent communication. Currently agents don't talk to each other -- they're called sequentially by routers. A lightweight event bus would enable reactive patterns (e.g., energy price spike triggers rescheduling). |
| **Knowledge management** | Dedicated knowledge layer. Assumptions logged and reviewable. Knowledge grows from real implementation questions. | Each agent has its own constants (SETUP_MATRIX, THROUGHPUT, MACHINE_POWER_KW). No shared knowledge layer. | Build a centralized `ShopKnowledge` service: material properties, machine capabilities, customer preferences. Agents query it instead of maintaining their own constants. |

---

## Summary: Top 5 Actions for YC S26

1. **Build the full-chain demo.** Show order -> anomaly gate -> schedule -> energy optimization -> vision inspection -> rework dispatch in one flow. This is the "workflow redesign" story McKinsey says wins.

2. **Quantify end-to-end impact.** The 35.7pp scheduling improvement is strong. Stack it with automated quoting time (seconds vs hours), automated rework dispatch, and energy savings for a compound number.

3. **Label the technology mix.** In pitch materials, explicitly show that MillForge uses deterministic rules, optimization algorithms, ML models, AND LLM agents -- each where appropriate. This is McKinsey's Lesson 2 and differentiates from "LLM wrapper" startups.

4. **Close the vision feedback loop.** Add `POST /api/vision/feedback` so operator overrides improve the model over time. This demonstrates the learning loop pattern McKinsey identifies as critical.

5. **Build the exception resolution UX.** The human-in-the-loop interface for held orders and borderline inspections is what shop floor operators will actually interact with daily. McKinsey's Lesson 6 says this determines adoption.
