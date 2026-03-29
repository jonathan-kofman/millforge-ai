# MillForge Business Plan

**Version:** 1.0 — March 2026
**Author:** Jonathan Kofman
**Stage:** Pre-seed / YC S26

---

## 1. Problem

The United States has ~330,000 metalworking establishments. The vast majority are job shops — contract manufacturers producing custom metal parts. Most of them run scheduling on whiteboards, quoting in spreadsheets, and quality inspection by eye. China is building dark factories — fully automated metal production with software controlling the entire production floor. The US has almost none of this infrastructure.

The immediate pain is scheduling. A typical job shop with 5–20 machines loses 15–25% of theoretical throughput to bad sequencing: wrong job runs on the wrong machine at the wrong time because the scheduler (usually one person) can't hold the full state of the floor in their head. On-time delivery rates average 72–78% industry-wide. Customers leave over missed deadlines.

---

## 2. Solution

MillForge is the intelligence layer for lights-out American metal mills.

The core thesis: every routine decision on the production floor can be automated. Software should decide what runs next, price every order, inspect every part, manage every inventory reorder, and optimise every energy bill. Humans handle exceptions only.

**Current automated touchpoints:**
| Touchpoint | Status |
|---|---|
| Scheduling (EDD + SA) | Automated |
| Quoting (lead time + price) | Automated |
| Quality inspection (YOLOv8n NEU-DET) | ONNX inference |
| Anomaly detection | Automated |
| Rework dispatch | Automated |
| Energy procurement | Automated (EIA API v2) |
| Inventory reorder | Automated |
| Supplier sourcing | Directory active (1,100+ US suppliers) |

---

## 3. Market

**TAM:** ~$4.8B — US manufacturing execution system (MES) + ERP spend for job shops
**SAM:** ~$1.2B — shops with 5–100 machines that lack any scheduling software
**SOM (Year 3):** ~$24M ARR — 400 shops at $60K/year average ACV

**Why now:**
- YOLOv8 and open ONNX models make computer vision deployable on a $400 mini-PC
- LLM scheduling + constraint solvers now run in milliseconds on commodity hardware
- Reshoring wave creating new job shops that lack legacy ERP baggage
- China's dark factory push is a visible competitive threat that creates urgency

---

## 4. Revenue Model

### Subscription Tiers

| Tier | Price / Month | Machines | Target |
|------|--------------|----------|--------|
| **Starter** | $499 | Up to 5 | Single-operator shops |
| **Growth** | $1,499 | Up to 20 | Mid-size job shops |
| **Enterprise** | $3,999 | Unlimited | High-volume / multi-site |
| **Custom** | Negotiated | Unlimited + SLA | Defence / Tier 1 suppliers |

Annual billing: 2 months free (16.7% discount).

### Additional Revenue Lines
- **Onboarding & integration:** $2,500–$15,000 one-time (ERP/MES data migration)
- **Market quotes API:** Usage-based fee for supplier price comparison ($0.10/query above free tier)
- **Contract management:** $199/month add-on (MSA generation, SLA tracking)

### Unit Economics (Target Year 2)
- CAC: $4,200 (outbound + demo close)
- ACV: $18,000 (Growth tier, annual)
- LTV: $108,000 (6-year retention at 95% gross retention)
- LTV:CAC: 25.7×
- Payback: ~3 months

---

## 5. Go-To-Market

**Phase 1 — 0 to 10 customers (now → Month 6)**
Direct founder sales. Target: New England job shops within 200 miles. Jonathan is at Northeastern's Advanced Manufacturing lab daily — warm intros, machine operators who know him. Close 3–5 paying pilots at $499/month, collect feedback.

**Phase 2 — 10 to 50 customers (Month 6–18)**
- PMPA (Precision Machined Products Association) member list: 700+ shops
- NTMA (National Tooling & Machining Association): 1,200+ members
- Content: YouTube teardowns showing on-time delivery improvement
- Channel: Haas Automation and Mazak dealer networks (they sell to the same shops)

**Phase 3 — 50 to 400 customers (Month 18–36)**
- Inside sales team (2 AEs by Month 18)
- Integration marketplace: ERP partners (JobBOSS2, Epicor)
- OEM embedding: sell MillForge as a white-label module to Haas/Mazak

---

## 6. Competitive Landscape

| Company | Price | AI Scheduling | Lights-Out Vision | Notes |
|---------|-------|--------------|------------------|-------|
| **MillForge** | $499–$3,999/mo | ✅ SA + EDD | ✅ YOLOv8n | Only AI-native option |
| JobBOSS2 | ~$2,000/mo | ❌ | ❌ | Legacy web ERP |
| ProShop ERP | ~$1,800/mo | ❌ | ❌ | Good UX, no AI |
| Plex (Rockwell) | $50K+/yr | ❌ | ❌ | Enterprise, 12-month impl |
| Epicor | $100K+/yr | Partial | ❌ | Enterprise only |
| Paper/spreadsheet | $0 | ❌ | ❌ | 60%+ of SAM |

**Key differentiation:** MillForge is the only system built around removing human touchpoints, not augmenting them. Every other product adds a screen to the human decision loop. MillForge removes the human from the loop entirely for routine decisions.

---

## 7. Financials

### Year 1 Projections (seed funding)

| Month | Customers | MRR | ARR Run-Rate |
|-------|-----------|-----|-------------|
| 1–3 | 3 | $4,500 | $54,000 |
| 4–6 | 8 | $11,000 | $132,000 |
| 7–9 | 18 | $26,000 | $312,000 |
| 10–12 | 32 | $48,000 | $576,000 |

### Seed Ask: $1.5M

| Use | % | Amount |
|-----|---|--------|
| Engineering (2 FTEs × 18 months) | 55% | $825,000 |
| Sales & GTM | 25% | $375,000 |
| Infrastructure & ops | 12% | $180,000 |
| Legal & compliance | 8% | $120,000 |

**Runway:** 24 months at current burn. Break-even at ~55 customers (Growth tier average).

### Series A Trigger
- $2M ARR
- 80+ paying customers
- Gross margin ≥ 75%
- At least one Tier 1 supplier or defence contractor as reference customer

---

## 8. Team

**Jonathan Kofman — Founder/CEO**
Machines parts daily at Northeastern's Advanced Manufacturing lab. Built MillForge because he lives the scheduling problem himself. CS/MechE background, operator background.

**Needed (seed hires):**
- Senior Full-Stack Engineer (FastAPI + React, manufacturing domain a plus)
- Operations / Customer Success (ex-job-shop manager)

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| Shops resistant to AI | Start with read-only mode; prove value before touching schedule |
| ERP integration complexity | REST-first; accept CSV import on day one |
| Hardware reliability | Cloud-hosted; no on-prem requirement |
| Competition from Plex/Epicor moving downmarket | Speed; we ship in weeks, they take 12 months to implement |
| ARIA-OS dependency | ARIA schema registry auto-adapts; no hard coupling |

---

## 10. Milestones

| Date | Milestone |
|------|-----------|
| Q1 2026 | YC application submitted |
| Q2 2026 | First 5 paying customers; $7,500 MRR |
| Q3 2026 | Seed round close; first full-time hire |
| Q4 2026 | 25 customers; $40,000 MRR |
| Q2 2027 | 80 customers; $150,000 MRR; Series A process begins |
| Q4 2027 | $2M ARR; first defence/Tier 1 customer |
