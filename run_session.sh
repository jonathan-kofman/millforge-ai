#!/usr/bin/env bash
# run_session.sh — MillForge Autonomous Development Runner (bash / WSL / Git Bash)
#
# Usage:
#   ./run_session.sh                        # one session, output to console
#   ./run_session.sh --log logs/session.log # append output to file
#   ./run_session.sh --dry-run              # print prompt without running
#
# Cron (every 2 hours):
#   0 */2 * * * cd /path/to/millforge-ai && ./run_session.sh --log logs/cron.log >> logs/cron.log 2>&1

set -euo pipefail

# ---------------------------------------------------------------------------
# Defaults / arg parsing
# ---------------------------------------------------------------------------
LOG_FILE=""
DRY_RUN=false
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --log)     LOG_FILE="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        *)         echo "Unknown arg: $1"; exit 1 ;;
    esac
done

MEMORY_FILE="$PROJECT_ROOT/AGENT_MEMORY.md"
BACKEND_DIR="$PROJECT_ROOT/backend"
TESTS_DIR="$PROJECT_ROOT/tests"
TODAY=$(date +%Y-%m-%d)

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "$msg"
    [[ -n "$LOG_FILE" ]] && echo "$msg" >> "$LOG_FILE"
}

# ---------------------------------------------------------------------------
# Build prompt
# ---------------------------------------------------------------------------
PROMPT="You are running an autonomous development session for the MillForge project.

Project root: $PROJECT_ROOT

## Instructions

1. READ: Read AGENT_MEMORY.md at $MEMORY_FILE to understand previous progress, the current backlog, and known issues.

2. TEST BASELINE: Run the test suite to confirm the codebase is healthy before making changes:
   cd \"$BACKEND_DIR\" && python -m pytest \"$TESTS_DIR\" -q

3. PICK TASK: Choose the single highest-priority, non-blocked task from the backlog in AGENT_MEMORY.md. State which task you are starting and why.

4. IMPLEMENT: Write a short plan (1-3 sentences), then implement the change. Follow the existing architecture:
   - Agents in backend/agents/  (pure Python, no FastAPI imports)
   - Routers in backend/routers/  (thin HTTP handlers)
   - Pydantic schemas in backend/models/schemas.py
   - Frontend components in frontend/src/components/
   - Tests in tests/

5. TEST: Run the full test suite again. If tests fail, fix them before proceeding.

6. UPDATE MEMORY: Update AGENT_MEMORY.md with:
   - New row in Session Log (today's date is $TODAY)
   - Updated backlog (mark done, reorder, add new items discovered)
   - Any new technical debt or architecture notes
   - Updated 'Next Session Goals'

7. DONE: Print a concise summary: what was implemented, test count before/after, any blockers.

## Constraints
- Prefer small, focused changes over large rewrites
- Keep all existing tests passing
- Do not delete code without clear justification
- If you hit a blocker (missing API key, broken dependency), note it in AGENT_MEMORY.md and pick the next unblocked task instead"

# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------
if [[ "$DRY_RUN" == "true" ]]; then
    log "DRY RUN — prompt that would be sent:"
    echo ""
    echo "$PROMPT"
    exit 0
fi

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
if [[ ! -f "$MEMORY_FILE" ]]; then
    log "ERROR: AGENT_MEMORY.md not found at $MEMORY_FILE"
    exit 1
fi

if ! command -v claude &>/dev/null; then
    log "ERROR: 'claude' not found in PATH. Install Claude Code: https://claude.ai/code"
    exit 1
fi

[[ -n "$LOG_FILE" ]] && mkdir -p "$(dirname "$LOG_FILE")"

log "=== MillForge Autonomous Session ==="
log "Project root : $PROJECT_ROOT"
log "Memory file  : $MEMORY_FILE"
log "Starting session…"
log "---"

# ---------------------------------------------------------------------------
# Run Claude Code non-interactively
# --dangerously-skip-permissions: allows file/bash tools without per-call prompts
# ---------------------------------------------------------------------------
if [[ -n "$LOG_FILE" ]]; then
    claude --dangerously-skip-permissions -p "$PROMPT" 2>&1 | tee -a "$LOG_FILE"
else
    claude --dangerously-skip-permissions -p "$PROMPT"
fi

log "---"
log "Session complete."
