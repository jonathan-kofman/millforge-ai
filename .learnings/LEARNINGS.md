# Learnings & Patterns

## STL analysis & Pydantic Optional fields / 2026-04-06
Use `or 0.0` guard at point of use when Pydantic Optional fields may be None. FastAPI GET endpoints don't support JSON bodies reliably—use POST. trimesh Scene.dump(concatenate=True) is deprecated; use to_geometry().

## ARIA material mapping / 2026-04-06
Static MATERIAL_MAP dict is more maintainable than ML classifiers. Covers 80% of alloys with exact match; defaults to "steel" conservatively.

## Material-specific throughput matters / 2026-04-06
Steel ~30-40% slower than aluminum. Always use material-specific MRR, never average. Drives cost accuracy ±15% vs ±30%.

## STL analysis fallback / 2026-04-06
Parse binary STL headers without trimesh for CI compatibility. ~5 lines of struct unpack for bounding box.

## Manufacturing work-order DB persistence in tests / 2026-04-07
Registry bootstrap (which loads machines from DB) fails during app lifespan startup in tests because the lifespan runs before conftest patches the DB engine. Use `pytest.skip()` for tests that require a routed work order rather than forcing a fake route.

## AS9100 readiness response shape / 2026-04-07
Returns `{"overall_score": ..., "clause_scores": ..., "gaps": [...]}` — not `readiness_score` or `overall_percent`. Watch for this pattern when writing tests for agents that have their own summary shape.

## Manufacturing intent schema / 2026-04-07
`ManufacturingIntentRequest` requires `part_id` (str), `target_quantity` (int), and `material` (MaterialSpecIn with `material_name` required). Not `quantity` or `material_spec`.

## Frontend Polish Pattern / 2026-04-07
Inter font + lucide-react + card hover lift is the minimum viable "professional SaaS" upgrade trio. IntersectionObserver with a `started` ref guard prevents AnimatedCounter from re-firing on re-render—critical for scroll-triggered animations that must fire once. Applying hover micro-interactions via global CSS classes (`.card`, `.card-highlight`) is more maintainable than per-component prop drilling. Static trend values on KPI cards (e.g., "+2.1%") add enterprise visual credibility without requiring live data—be explicit that they're static in docs.

## API Contract Mismatches / 2026-04-07
Always verify field names between frontend data access and actual backend response schemas. Common pattern: frontend written speculatively before backend finalized.
- `rates_usd_per_kwh` from `/api/energy/rates` is a flat float array (indexed by hour 0-23), NOT array of objects
- `NegativePricingResponse.windows` contains `cheap_windows` field (not `windows.windows` double-nested); `rate_usd_per_mwh` requires `/1000` conversion for $/kWh display
- `FeasibilityResultOut` fields: `validation_errors`, `routing_warnings`, `supported_processes` (not `issues`, `recommendations`, `recommended_process`)
- `RouteOptionOut` has flat `machine_name` field (not nested `machine?.machine_name`)
- `/api/schedule` is the correct scheduling endpoint; `/api/orders/schedule` does not exist
- ScheduleViewer's `loadLive()` pattern is the reference implementation for client-side schedule submission (fetch orders, POST to /api/schedule with payload)
- NL Scheduler's `result.schedule?.schedule?.length` double-nesting is correct (response field contains ScheduleResponse which has its own .schedule array)

## Live spot pricing in quote & aria_scan endpoints / 2026-04-07
Replaced hardcoded UNIT_PRICE dict with real Yahoo Finance spot prices. Key patterns:
- `market_quoter.py:get_spot_price()` — fetches live commodity prices, caches for 1 hour, falls back to defaults on network failure
- Quote endpoint uses `_estimate_unit_weight_lb()` (volume × material density) and applies `MACHINING_OVERHEAD_PER_UNIT` dict for final cost
- `_load_db_queue()` pattern: query real pending orders from DB first, fall back to demo set only if empty — this is the right default for all scheduling/quoting endpoints to reflect real shop state
- Unit price assertions in tests must use ratio comparisons (e.g., `500-unit price / 100-unit price ≈ 0.95`) not absolute values — market prices fluctuate daily
- aria_scan.py mirrors quote.py logic for consistency (same spot-price pipeline, same DB queue loader)
