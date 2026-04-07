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
