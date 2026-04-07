# Learnings & Patterns

## STL analysis & Pydantic Optional fields / 2026-04-06
Use `or 0.0` guard at point of use when Pydantic Optional fields may be None. FastAPI GET endpoints don't support JSON bodies reliably—use POST. trimesh Scene.dump(concatenate=True) is deprecated; use to_geometry().

## ARIA material mapping / 2026-04-06
Static MATERIAL_MAP dict is more maintainable than ML classifiers. Covers 80% of alloys with exact match; defaults to "steel" conservatively.

## Material-specific throughput matters / 2026-04-06
Steel ~30-40% slower than aluminum. Always use material-specific MRR, never average. Drives cost accuracy ±15% vs ±30%.

## STL analysis fallback / 2026-04-06
Parse binary STL headers without trimesh for CI compatibility. ~5 lines of struct unpack for bounding box.
