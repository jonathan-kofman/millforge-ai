# backend.visual_qa

HTTP endpoint verification framework for the MillForge FastAPI backend.
Sister package to `aria_os.visual_qa` (which handles file artifacts).

## Checks shipped

| Module | Target endpoint | What it verifies |
|--------|-----------------|------------------|
| `health_score_check` | `/api/analytics/health-score` | 4 pillars present, scores in [0..100], weights sum to 1.0 |
| `supplier_recommend_check` | `/api/suppliers/recommend` | `name`, `confidence` in [0..1], `state` on every result; `distance` present when lat/lng supplied |
| `onboarding_check` | `/api/onboarding/templates` + `/api/onboarding/milestones` | 4 templates (`cnc_job_shop`, `mixed`, `fab_shop`, `print_farm`), 5 milestones each with a `completed: bool` |

The generic primitive is `endpoint_verify.verify_endpoint(url,
expected_keys, validators=...)` — use it to build new checks.

## CLI

```bash
python -m backend.visual_qa run                               # all checks
python -m backend.visual_qa run --base-url http://localhost:8000 --token eyJ...
python -m backend.visual_qa health-score
python -m backend.visual_qa supplier-recommend
python -m backend.visual_qa onboarding
```

The `run` subcommand prints a markdown report to stdout; the other
subcommands print one JSON blob per check.

## Contract

Every check function returns a dict with an `ok: bool` key. Nothing
raises — transport and JSON errors show up as `errors: [...]` plus
`ok=False`. HTTP timeout is 10 seconds (hard-coded in
`endpoint_verify`).

## Deferred

Frontend screenshot verification of `DemoChainPage.jsx` is deferred —
`TODO: use Playwright when available`. The `visual_qa` package
intentionally has no heavy browser deps.
