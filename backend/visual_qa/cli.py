"""
backend.visual_qa.cli — run all MillForge visual QA checks.

Emits a markdown report of: /api/analytics/health-score,
/api/suppliers/recommend, /api/onboarding/templates (+ milestones).
Defaults to base URL http://localhost:8000 — override with
``--base-url``. Also supports ``--token`` for authenticated endpoints.

Frontend screenshot verification is deferred — see TODO in this file.
Use Playwright when available.

Usage:
    python -m backend.visual_qa run [--base-url URL] [--token TOKEN]
    python -m backend.visual_qa health-score [--base-url URL] [--token TOKEN]
    python -m backend.visual_qa supplier-recommend [--base-url URL]
    python -m backend.visual_qa onboarding [--base-url URL]
"""
from __future__ import annotations

import json
import sys
from typing import Any

from .health_score_check import check_health_score
from .onboarding_check import check_onboarding_templates
from .supplier_recommend_check import check_supplier_recommend


def _parse_flags(argv: list[str]) -> tuple[list[str], dict[str, str]]:
    pos: list[str] = []
    flags: dict[str, str] = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a.startswith("--"):
            key = a.lstrip("-")
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                flags[key] = argv[i + 1]
                i += 2
                continue
            flags[key] = "true"
            i += 1
            continue
        pos.append(a)
        i += 1
    return pos, flags


def _status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def _render_report(results: dict[str, dict[str, Any]]) -> str:
    lines: list[str] = []
    lines.append("# MillForge Visual QA Report")
    lines.append("")
    overall = all(r.get("ok", False) for r in results.values())
    lines.append(f"**Overall**: {_status(overall)}")
    lines.append("")
    lines.append("| Check | Status | Endpoint | Notes |")
    lines.append("|-------|--------|----------|-------|")
    for name, r in results.items():
        endpoint = r.get("endpoint") or r.get("templates_endpoint") or ""
        status = _status(bool(r.get("ok")))
        errs = r.get("errors") or []
        notes = ("; ".join(str(e) for e in errs)[:120]) if errs else "ok"
        lines.append(f"| {name} | {status} | {endpoint} | {notes} |")
    lines.append("")
    lines.append("## Raw results")
    lines.append("")
    lines.append("```json")
    lines.append(json.dumps(results, indent=2, default=str))
    lines.append("```")
    lines.append("")
    lines.append("## Deferred")
    lines.append("")
    lines.append("- Frontend screenshot of DemoChainPage.jsx "
                 "(TODO: use Playwright when available).")
    return "\n".join(lines)


def _run_all(base_url: str, token: str | None) -> int:
    results = {
        "health_score": check_health_score(base_url=base_url, token=token),
        "supplier_recommend": check_supplier_recommend(base_url=base_url),
        "onboarding": check_onboarding_templates(base_url=base_url, token=token),
    }
    print(_render_report(results))
    return 0 if all(r.get("ok") for r in results.values()) else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    pos, flags = _parse_flags(argv)
    cmd = pos[0] if pos else "run"
    base_url = flags.get("base-url", "http://localhost:8000")
    token = flags.get("token") or None

    if cmd == "run":
        return _run_all(base_url, token)
    if cmd == "health-score":
        r = check_health_score(base_url=base_url, token=token)
        print(json.dumps(r, indent=2, default=str))
        return 0 if r.get("ok") else 1
    if cmd == "supplier-recommend":
        r = check_supplier_recommend(base_url=base_url)
        print(json.dumps(r, indent=2, default=str))
        return 0 if r.get("ok") else 1
    if cmd == "onboarding":
        r = check_onboarding_templates(base_url=base_url, token=token)
        print(json.dumps(r, indent=2, default=str))
        return 0 if r.get("ok") else 1

    print(f"unknown subcommand: {cmd}")
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
