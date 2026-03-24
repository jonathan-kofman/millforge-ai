# MillForge Observability Tooling

External dashboards and developer tools installed at `~/tools/` to monitor and explore the MillForge codebase during Claude Code sessions.

---

## Dashboard Summary

| Tool | URL | What it shows | Status |
|------|-----|---------------|--------|
| claude-code-dashboard | http://localhost:3001 | Live session cost, token usage, model activity | Installed |
| claude-watch | http://localhost:3853 | Codebase events, file changes, AI search | Installed + hooked |
| claude-hud | Statusline (in terminal) | Context %, token usage, active tools, todos | Installed |
| Understand-Anything | Skill: `/understand` | Interactive knowledge graph of codebase | Installed as skill |

---

## 1. claude-code-dashboard

**URL**: http://localhost:3001
**Repo**: https://github.com/Stargx/claude-code-dashboard
**Location**: `~/tools/claude-code-dashboard`

Watches `~/.claude/projects/*/` JSONL session files in real time. Shows per-session cost (input/output tokens × pricing), model used, and a live feed of tool calls.

**Start**:
```powershell
~/tools/start-dashboard.ps1
```
or in bash:
```bash
~/tools/start-dashboard.sh
```

---

## 2. claude-watch

**URL**: http://localhost:3853
**Repo**: https://github.com/NirDiamant/claude-watch
**Location**: `~/tools/claude-watch`

Open-source observability dashboard for Claude Code sessions. Visualizes project logic, tracks file changes, and provides AI-powered code search. The MillForge project is already hooked — Claude Code sends events to the dashboard automatically while the server is running.

**Start**:
```powershell
~/tools/start-watch.ps1
```
or directly:
```bash
node ~/tools/claude-watch/dist/cli.js start
```

**Hooks**: Configured in `.claude/settings.json` (events → `http://localhost:3853/api/events`).

---

## 3. claude-hud (Statusline)

**Repo**: https://github.com/jarrodwatts/claude-hud
**Location**: `~/tools/claude-hud` and `~/.claude/plugins/cache/claude-hud/`

Displays a multi-line real-time statusline at the bottom of the Claude Code terminal. Shows:
- Current model and git branch
- Context window usage bar (color-coded: green < 70%, yellow < 85%, red > 85%)
- Token usage and rate limit bars
- Active tool calls and running agents (when enabled)
- Todo progress (when enabled)

**No separate server needed** — runs as a Claude Code statusLine command.
**Takes effect after restarting Claude Code.**

To enable optional features (tools, agents, todos), run `/claude-hud:setup` after restart.

---

## 4. Understand-Anything

**Repo**: https://github.com/Lum1104/Understand-Anything
**Location**: `~/tools/understand-anything`, skills at `~/.claude/skills/understand-anything/`

Multi-agent pipeline that analyzes your codebase and builds an interactive knowledge graph. Saves output to `.understand-anything/knowledge-graph.json`.

**Available skills** (usable from any Claude Code session in this project):
- `/understand` — Full codebase analysis → knowledge graph
- `/understand-diff` — Analyze recent git changes
- `/understand-explain` — Explain a specific module or file
- `/understand-chat` — Ask questions about the architecture
- `/understand-dashboard` — Open the interactive visualization
- `/understand-onboard` — Generate a guided onboarding tour

**Run the initial scan**:
```
/understand
```

---

## Master Launcher

Start both web dashboards at once:

```powershell
~/tools/start-all-dashboards.ps1
```

This opens:
- http://localhost:3001 — Live session monitor
- http://localhost:3853 — Codebase visual map

---

## Installation Notes

All tools were installed from GitHub on 2026-03-23.

| Tool | Installed via | Build |
|------|--------------|-------|
| claude-code-dashboard | `git clone` + `npm install` | Runtime only (no build step) |
| claude-watch | `git clone` + `npm install` + `npm run build` | `~/tools/claude-watch/dist/cli.js` |
| claude-hud | `git clone` + `npm ci` + `npm run build` | `~/.claude/plugins/cache/claude-hud/claude-hud/0.0.11/dist/index.js` |
| Understand-Anything | `git clone`, skills copied to `~/.claude/skills/` | Runs as Claude Code sub-agents |

The `/plugin marketplace add` command is not used — all tools were installed manually.
The `/understand` skill is available immediately without a separate server.
