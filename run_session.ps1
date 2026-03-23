# run_session.ps1 - MillForge Autonomous Development Runner (Windows PowerShell)
#
# Usage:
#   .\run_session.ps1                           # run one session
#   .\run_session.ps1 -LogFile logs\session.log # also append output to file
#   .\run_session.ps1 -DryRun                   # print prompt, do not invoke claude
#   .\run_session.ps1 -RegisterTask             # add Windows Task Scheduler job
#   .\run_session.ps1 -RegisterTask -IntervalHours 4

param(
    [string] $LogFile       = '',
    [switch] $DryRun,
    [switch] $RegisterTask,
    [int]    $IntervalHours = 2,
    [string] $ProjectRoot   = $PSScriptRoot
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$memoryFile = Join-Path $ProjectRoot 'AGENT_MEMORY.md'
$backendDir = Join-Path $ProjectRoot 'backend'
$testsDir   = Join-Path $ProjectRoot 'tests'
$today      = (Get-Date).ToString('yyyy-MM-dd')

function Log([string]$msg) {
    $line = "[$((Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))] $msg"
    Write-Host $line
    if ($LogFile) { Add-Content -Path $LogFile -Value $line }
}

# ---------------------------------------------------------------------------
# Register Windows Task Scheduler job (run once with -RegisterTask)
# ---------------------------------------------------------------------------
if ($RegisterTask) {
    $scriptPath = $MyInvocation.MyCommand.Path
    $logPath    = Join-Path $ProjectRoot 'logs\session.log'
    New-Item -ItemType Directory -Force -Path (Split-Path $logPath) | Out-Null

    $action   = New-ScheduledTaskAction `
        -Execute 'powershell.exe' `
        -Argument ('-NonInteractive -ExecutionPolicy Bypass -File "' + $scriptPath + '" -LogFile "' + $logPath + '"')
    $trigger  = New-ScheduledTaskTrigger `
        -RepetitionInterval (New-TimeSpan -Hours $IntervalHours) `
        -Once -At (Get-Date)
    $settings = New-ScheduledTaskSettingsSet `
        -ExecutionTimeLimit (New-TimeSpan -Hours 1) `
        -StartWhenAvailable

    Register-ScheduledTask `
        -TaskName 'MillForge-AutonomousSession' `
        -Action $action -Trigger $trigger -Settings $settings `
        -RunLevel Highest -Force | Out-Null

    Write-Host "Task registered: runs every $IntervalHours hour(s). Log -> $logPath"
    exit 0
}

# ---------------------------------------------------------------------------
# Build prompt (avoid here-string quoting issues by joining an array)
# ---------------------------------------------------------------------------
$lines = @(
    'You are running an autonomous development session for the MillForge project.',
    '',
    "Project root: $ProjectRoot",
    '',
    '## Instructions',
    '',
    "1. READ: Read AGENT_MEMORY.md at $memoryFile to understand previous progress, the current backlog, and known issues.",
    '',
    '2. TEST BASELINE: Run the test suite to confirm the codebase is healthy:',
    "   cd `"$backendDir`" && python -m pytest `"$testsDir`" -q",
    '',
    '3. PICK TASK: Choose the single highest-priority, non-blocked task from the backlog. State which task you are starting and why.',
    '',
    '4. IMPLEMENT: Write a 1-3 sentence plan, then implement the change. Follow the existing architecture:',
    '   - Agents in backend/agents/  (pure Python, no FastAPI imports)',
    '   - Routers in backend/routers/  (thin HTTP handlers)',
    '   - Pydantic schemas in backend/models/schemas.py',
    '   - Frontend components in frontend/src/components/',
    '   - Tests in tests/',
    '',
    '5. TEST: Run the full test suite again. Fix any failures before proceeding. Do not ship broken tests.',
    '',
    '6. UPDATE MEMORY: Update AGENT_MEMORY.md with:',
    "   - New row in Session Log (today is $today)",
    '   - Updated backlog (mark completed tasks done, reorder, add newly discovered tasks)',
    '   - Any new technical debt or architecture notes',
    '   - Updated Next Session Goals section',
    '',
    '7. DONE: Print a concise summary: what was implemented, test count before/after, any blockers encountered.',
    '',
    '## Constraints',
    '   - Prefer small focused changes over large rewrites',
    '   - Keep all existing tests passing',
    '   - Do not delete code without clear justification',
    '   - If blocked (missing API key, broken dep), note in AGENT_MEMORY.md and pick the next unblocked task'
)

$prompt = $lines -join "`n"

# ---------------------------------------------------------------------------
# Dry run: print prompt and exit
# ---------------------------------------------------------------------------
if ($DryRun) {
    Log '=== DRY RUN - prompt that would be sent ==='
    Write-Host ''
    Write-Host $prompt
    exit 0
}

# ---------------------------------------------------------------------------
# Preflight checks
# ---------------------------------------------------------------------------
if (-not (Test-Path $memoryFile)) {
    Log "ERROR: AGENT_MEMORY.md not found at $memoryFile"
    exit 1
}

if (-not (Get-Command 'claude' -ErrorAction SilentlyContinue)) {
    Log "ERROR: 'claude' not found in PATH. Install: https://claude.ai/code"
    exit 1
}

if ($LogFile) {
    New-Item -ItemType Directory -Force -Path (Split-Path $LogFile) | Out-Null
}

# ---------------------------------------------------------------------------
# Run Claude Code
# --dangerously-skip-permissions lets claude use Bash/Read/Write/Edit
# without prompting for approval on every tool call (needed for automation)
# ---------------------------------------------------------------------------
Log '=== MillForge Autonomous Session ==='
Log "Project root : $ProjectRoot"
Log "Memory file  : $memoryFile"
Log 'Starting session...'
Log '---'

if ($LogFile) {
    claude --dangerously-skip-permissions -p $prompt 2>&1 | Tee-Object -FilePath $LogFile -Append
} else {
    claude --dangerously-skip-permissions -p $prompt
}

$code = $LASTEXITCODE
Log '---'
Log "Session complete (exit code: $code)"
exit $code
