# MillForge Changelog

Detailed session-by-session record of changes. Each entry covers every file touched, the reasoning behind each change, what was tried and failed, and what was deferred.

---

## 2026-03-23 — Session 2 (GitHub live + test completion + docs + memory versioning)

### Context
Previous session (Session 1) built the full MillForge POC: backend, frontend, 63 initial tests, all agents. It was blocked before pushing to GitHub because the remote did not yet exist. This session resumed after the user confirmed the repo is live at `https://github.com/jonathan-kofman/millforge-ai.git`.

### Files Created

#### `tests/test_quote.py` (25 tests)
- **Why**: Phase 9 of the development plan required full HTTP-level test coverage for all routers. The quote router had no dedicated test file — only indirect coverage via scheduler tests.
- **What it covers**: Response shape validation, `quote_id` prefix (`"QUOTE-"`), lead-time consistency (`days ≈ hours / 24` within ±1), pricing for all four materials (steel $2.50, aluminum $1.80, titanium $4.20, copper $2.10), volume discounts at exact thresholds (no discount below 500, 5% at 500, 10% at 1000, 20% at 10000), optional `due_date` field, and 422 validation errors (invalid material, zero quantity, quantity > 100_000, missing required fields).
- **Reasoning for threshold tests**: The volume discount logic in `routers/quote.py:_volume_discount()` has four bands. Testing at the boundary (quantity=500, not 499 or 501) confirms the `>=` comparisons are correct and no off-by-one errors exist.

#### `tests/test_contact.py` (13 tests)
- **Why**: The contact router also had no dedicated tests. It has non-obvious behavior: `pilot_interest=True` changes the response message to include "pilot program" language, and `company` is optional.
- **What it covers**: 200 status, `success=True` in response, pilot vs. non-pilot message variants, with/without `company` field, and 422 validation (missing name, name < 2 chars, missing email, invalid email format, missing message, message < 10 chars).

#### `memory/MILLFORGE.md` (in-repo copy)
- **Why**: User requested that the `~/projects/memory/` files be version-controlled inside the repo under `memory/`. This makes the project self-documenting and preserves memory history in git.
- **Content**: Same as the home-directory copy; test count updated to 113 (79 existing + 25 quote + 13 contact + 6 additional energy optimizer tests that were also written this session but existed from Session 1).

#### `memory/DEPENDENCIES.md` (in-repo copy)
- **Why**: Same version-control rationale. This file contains the Mermaid dependency graph and the package risk register — valuable for future contributors to understand the dependency surface.

#### `memory/CODE-REVIEW.md` (in-repo copy, updated)
- **Why**: Same version-control rationale. The original code review was written against 63 tests with coverage gaps in energy optimizer, quote, and contact. Updating it before committing ensures the in-repo review reflects the actual current state (113 tests, all gaps closed).
- **Changes from home-directory version**: Updated test count (63 → 113), changed EnergyOptimizer/quote/contact coverage status to "Good", removed the action items that were already completed, updated the Priority Action Items to remove closed items.

#### `memory/INDEX.md` (in-repo copy)
- **Why**: Index file for the memory system; needed so the memory/ directory is self-navigable without reading every file.

#### `docs/CHANGELOG.md` (this file)
- **Why**: User established a standing instruction: after every session, append a detailed changelog entry. This file was created to fulfill that instruction. Format: most-recent entry first (reverse chronological).

### Files Modified

#### `~/projects/memory/MILLFORGE.md` (home-directory copy)
- **Why**: The GitHub URL was previously a placeholder. User confirmed the repo is live; updated the Status section to include the correct URL.
- **Change**: Added `**GitHub**: https://github.com/jonathan-kofman/millforge-ai.git` on its own line.

#### `~/projects/memory/INDEX.md` (home-directory copy)
- **Why**: Same as MILLFORGE.md — added GitHub URL to Quick Ref section; updated test count.

#### `README.md`
- **Why**: The README was written before GitHub existed and before the auth/orders system was built. It was missing the GitHub URL, showed an outdated test count, had a truncated project structure, and only documented 6 of the 15 API endpoints.
- **Changes**:
  - Added GitHub clone URL after tagline
  - Updated `make test` comment from "63 tests" to "113 tests"
  - Expanded project structure to include `database.py`, `db_models.py`, `auth/`, `sa_scheduler.py`, `OrdersView.jsx`, and full `tests/` listing
  - Expanded API table from 6 to 15 rows, added Auth column, added all auth + orders CRUD endpoints

#### `docs/api_spec.md`
- **Why**: The API spec was written early in the project and only covered the public endpoints (quote, schedule, vision, contact). The authenticated orders + auth endpoints were added later and never documented.
- **Changes**: Appended full documentation for `POST /api/auth/register`, `POST /api/auth/login`, `GET /api/orders`, `POST /api/orders`, `GET /api/orders/{order_id}`, `PATCH /api/orders/{order_id}`, `DELETE /api/orders/{order_id}`, and `POST /api/orders/schedule` — including request/response JSON shapes, auth requirements, and error codes.

#### `docs/architecture.md`
- **Why**: The architecture doc predated the database layer and auth system. It described MillForge as a stateless system but the actual implementation uses SQLAlchemy, user accounts, JWT auth, and multi-model persistence.
- **Changes**:
  - Added **Database Layer** section: ORM models table (User, OrderRecord, ScheduleRun, InspectionRecord), session management explanation, StaticPool test isolation pattern
  - Added **Auth Flow** section: ASCII sequence diagram for register/login → JWT flow and JWT-protected endpoint flow; noted Argon2id, HS256, 7-day expiry
  - Updated Key Design Decisions: added SA warm-start guarantee, StaticPool rationale, user-scoped queries security note; removed outdated "in-memory only" point

### What Was Tried and Didn't Work

- **`ls` with Windows-style path in bash**: Running `ls "C:\Users\jonko\projects\memory\"` in the bash tool failed with "unexpected EOF while looking for matching quote" — the backslash-quote interaction breaks the shell parser. Fixed by using the Glob tool instead, which handles Windows paths correctly.

### What Was Deferred

- **`routers/schedule.py` HTTP-level tests**: The code review flags this as "Partial" coverage — the schedule router is exercised via scheduler agent tests but has no dedicated `test_schedule_http.py`. Deferred because the scheduler agent tests are comprehensive and the route is thin. Priority: Low.
- **CI/CD pipeline (GitHub Actions)**: The repo is now live but has no automated test runner on push. This is Backlog item #1. Deferred to a future session — requires deciding on Python version matrix, caching strategy, and whether to run frontend linting.
- **Alembic migration files**: Alembic is installed but unused. Deferred until the PostgreSQL migration decision is made.
- **Rate limiting on auth endpoints**: `slowapi` was not added. Deferred — this is a pre-public-launch concern, not needed for the POC demo.

---

## 2026-03-22 — Session 1 (Initial POC build)

### Summary
Full POC built from scratch: FastAPI backend with 5 routers, SQLAlchemy + SQLite persistence, JWT auth, Argon2id password hashing, EDD greedy scheduler, Simulated Annealing optimizer, QualityVisionAgent, EnergyOptimizer, React/Vite/Tailwind frontend with 4 views, 63 initial tests, full documentation (architecture.md, api_spec.md, agents.md, development_plan.md), and memory system (MILLFORGE.md, DEPENDENCIES.md, CODE-REVIEW.md).

**Blocked at end of session**: Could not push to GitHub because the remote did not yet exist. All git operations were local only (init + commit). GitHub push deferred to Session 2.

### Key files created (63)
All backend source, frontend source, tests, docs, and memory files. See `git log --name-only` for the complete list.
