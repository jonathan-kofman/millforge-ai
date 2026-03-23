# MillForge Code Review

**Reviewer**: Claude Code (automated)
**Date**: 2026-03-23
**Scope**: Full backend + frontend codebase
**Tests at review time**: 113 passing

---

## Overall Assessment: B+ (Production-Ready POC)

The codebase is well-structured and clearly designed. The separation of concerns (agents ↔ routers ↔ schemas) is consistent. The scheduler is the core intellectual property and is solid. Main gaps are around production hardening (no rate limiting, SQLite, no migrations) — all expected for a POC stage.

---

## Architecture

### Strengths
- Clean three-layer structure: router → agent → domain
- Pydantic v2 as single source of truth for API contracts
- Agents are stateless and instantiated once at module level (correct pattern)
- `optimize()` interface is stable across EDD and SA schedulers
- SA warm-starts from EDD — guaranteed to never regress below EDD solution
- `_record_to_domain()` helper correctly handles ORM → domain conversion
- User-scoped orders (no cross-user leakage)

### Issues

**[MEDIUM] `estimate_lead_time()` uses SA for quote endpoint**
- File: `backend/routers/quote.py:52`
- The quote endpoint calls `_scheduler.estimate_lead_time()` which runs the full EDD scheduler per call. This is fast. However, `backend/routers/orders.py` uses SA by default, which runs 12k iterations. If the quote endpoint is ever switched to SA, it will be slow (~200ms per request). Currently acceptable.
- Recommendation: Document this explicitly; add a fast-path for quote.

**[LOW] `Schedule.generated_at` strips timezone info**
- File: `backend/agents/scheduler.py:119`
- `datetime.now(timezone.utc).replace(tzinfo=None)` loses tz info. Consistent throughout codebase but worth noting for future API consumers expecting ISO 8601 with Z suffix.

**[LOW] `_find_best_machine` ignores setup time in machine selection**
- File: `backend/agents/scheduler.py:270-283`
- The greedy machine picker selects earliest-available without accounting for setup time. Machine A might be available 1 minute earlier but require 60 more minutes of setup than Machine B. SA corrects for this globally, but EDD could be improved.

---

## Security

### Strengths
- Argon2id password hashing (state-of-the-art KDF)
- JWT token validation on all protected endpoints
- User-scoped queries (cannot access other users' orders)
- Input validation via Pydantic on all endpoints

### Issues

**[HIGH] No rate limiting on any endpoint**
- Auth endpoints (`/api/auth/register`, `/api/auth/login`) have no brute-force protection
- Recommendation: Add `slowapi` with 5 req/min on auth endpoints before public exposure

**[MEDIUM] JWT stored in localStorage (XSS risk)**
- File: `frontend/src/App.jsx` (inferred)
- localStorage is readable by any JS on the page. Acceptable for internal POC.
- Recommendation: Switch to `httpOnly` SameSite=Strict cookie for production

**[MEDIUM] CORS allows `http://localhost:5173,localhost:3000,localhost:80`**
- File: `backend/main.py:56-59`
- Defaults are dev-only. Ensure `CORS_ORIGINS` env var is set strictly in production.

**[LOW] `image_url` not validated as URL**
- File: `backend/routers/vision.py:39`
- Only validates non-empty. A full URL validator (Pydantic `HttpUrl` or regex) would prevent SSRF if vision agent ever fetches images.

---

## Performance

### Strengths
- SA is O(max_iterations) with small constant per iteration
- Scheduler instances are module-level singletons (no per-request init)
- SQLAlchemy query is simple indexed lookup on `created_by_id` + `status`

### Issues

**[MEDIUM] No database indexes declared**
- File: `backend/db_models.py`
- `OrderRecord.created_by_id` and `OrderRecord.status` are filtered frequently but have no explicit index declaration. SQLite creates implicit indexes for FK, but explicit `index=True` would be safer for PostgreSQL migration.

**[LOW] `get_optimal_start_windows()` runs 24 iterations**
- File: `backend/agents/energy_optimizer.py:160-169`
- Computes a separate `estimate_energy_cost()` for each hour. Negligible at 24 iterations but would benefit from vectorization for longer lookaheads.

---

## Code Quality

### Strengths
- Consistent docstrings on all public methods
- Type annotations throughout
- Clean use of dataclasses for domain models
- Logging at INFO level on key operations
- Tests cover happy path + auth isolation + edge cases + validation errors

### Issues

**[LOW] `_volume_discount()` is a module-level function, not a method**
- File: `backend/routers/quote.py:85`
- Minor: would be cleaner as a staticmethod on a `PricingEngine` class or extracted to an agents module. Fine for POC.

**[LOW] `conftest.py` StaticPool pattern is clever but fragile**
- Module-level engine patching works because Python resolves globals at call time, but it could break if SQLAlchemy internals change. Well-documented in AGENT_MEMORY.md.

---

## Frontend

### Strengths
- Consistent error state pattern (`[loading, error, result]`)
- Auth token passed via headers (not query params)
- `useCallback` on `fetchOrders` prevents infinite loop

### Issues

**[MEDIUM] No loading skeleton / optimistic updates**
- Delete and status-change operations call `fetchOrders()` after completion, causing a full table refresh. For a large order list this creates visible flicker.

**[LOW] `window.confirm()` for delete is browser-native but not accessible**
- File: `frontend/src/components/OrdersView.jsx:76`
- No keyboard trap issue for POC, but consider a custom modal for production.

**[LOW] Schedule table uses `new Date(s.processing_start).toLocaleString()`**
- Timezone display will reflect the user's local timezone, which may differ from the server's timezone. Acceptable for POC.

---

## Test Coverage Assessment

| Module | Coverage | Notes |
|--------|---------|-------|
| agents/scheduler.py | Good | test_scheduler.py: 15 tests |
| agents/sa_scheduler.py | Good | test_sa_scheduler.py: 12 tests |
| agents/energy_optimizer.py | Good | test_energy_optimizer.py: 13 tests |
| routers/orders.py | Good | test_orders.py + test_order_schedule.py |
| routers/vision.py | Good | test_vision_persist.py: 4 tests |
| routers/auth_router.py | Good | test_auth.py: 10 tests |
| routers/quote.py | Good | test_quote.py: 25 tests |
| routers/contact.py | Good | test_contact.py: 13 tests |
| routers/schedule.py | Partial | Covered via scheduler tests, no dedicated HTTP test |

---

## Priority Action Items

1. **Add rate limiting** on `/api/auth/*` (HIGH, pre-public-launch)
2. **Add DB indexes** on `OrderRecord.created_by_id` and `OrderRecord.status` (MEDIUM, pre-PostgreSQL migration)
3. **Alembic migration files** before first prod deploy (MEDIUM)
4. **httpOnly cookie** for JWT in production (MEDIUM, security)
5. **Switch quote endpoint** to EDD for lead time estimation (LOW, perf)
