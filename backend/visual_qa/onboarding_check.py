"""
backend.visual_qa.onboarding_check — verify /api/onboarding/templates.

Hits the onboarding templates endpoint and verifies the four expected
templates are listed: ``cnc_job_shop``, ``mixed``, ``fab_shop``,
``print_farm``. Optionally also checks /api/onboarding/milestones for
5 milestones with a ``completed`` boolean each.

Never raises. Returns a dict with ``ok: bool`` and details.
"""
from __future__ import annotations

from typing import Any, Optional

from .endpoint_verify import verify_endpoint


_EXPECTED_TEMPLATES = ("cnc_job_shop", "mixed", "fab_shop", "print_farm")


def check_onboarding_templates(
    base_url: str = "http://localhost:8000",
    token: Optional[str] = None,
    check_milestones: bool = True,
) -> dict[str, Any]:
    """Verify onboarding templates (and optionally milestones).

    Args:
        base_url: MillForge backend base URL.
        token: optional bearer token.
        check_milestones: if True, also hit /api/onboarding/milestones.

    Returns:
        {
          "ok": bool,
          "templates_endpoint": str,
          "milestones_endpoint": str | None,
          "templates_found": [str, ...],
          "missing_templates": [str, ...],
          "milestone_count": int | None,
          "errors": [str, ...],
        }
    """
    headers = {"Authorization": f"Bearer {token}"} if token else None
    templates_url = base_url.rstrip("/") + "/api/onboarding/templates"
    milestones_url = base_url.rstrip("/") + "/api/onboarding/milestones"

    result: dict[str, Any] = {
        "ok": False,
        "templates_endpoint": templates_url,
        "milestones_endpoint": milestones_url if check_milestones else None,
        "templates_found": [],
        "missing_templates": [],
        "milestone_count": None,
        "errors": [],
    }

    # --- Templates ---
    raw = verify_endpoint(templates_url, expected_keys=[], headers=headers)
    if raw.get("error") and not raw.get("response_json"):
        result["errors"].append(f"templates: {raw['error']}")
        return result

    body = raw.get("response_json")
    template_keys: list[str] = []
    if isinstance(body, dict):
        if isinstance(body.get("templates"), dict):
            template_keys = list(body["templates"].keys())
        elif isinstance(body.get("templates"), list):
            # list of {name: ...} or list of strings
            for t in body["templates"]:
                if isinstance(t, dict):
                    k = t.get("key") or t.get("name") or t.get("id")
                    if k:
                        template_keys.append(str(k))
                elif isinstance(t, str):
                    template_keys.append(t)
        else:
            template_keys = list(body.keys())
    elif isinstance(body, list):
        for t in body:
            if isinstance(t, dict):
                k = t.get("key") or t.get("name") or t.get("id")
                if k:
                    template_keys.append(str(k))
            elif isinstance(t, str):
                template_keys.append(t)

    result["templates_found"] = template_keys
    missing = [t for t in _EXPECTED_TEMPLATES if t not in template_keys]
    result["missing_templates"] = missing
    if missing:
        result["errors"].append(f"missing templates: {missing}")

    # --- Milestones ---
    if check_milestones:
        raw_m = verify_endpoint(milestones_url, expected_keys=[], headers=headers)
        if raw_m.get("error") and not raw_m.get("response_json"):
            result["errors"].append(f"milestones: {raw_m['error']}")
        else:
            mbody = raw_m.get("response_json")
            milestones: list[Any] = []
            if isinstance(mbody, list):
                milestones = mbody
            elif isinstance(mbody, dict):
                milestones = (
                    mbody.get("milestones")
                    or mbody.get("items")
                    or []
                )
            result["milestone_count"] = len(milestones) if isinstance(milestones, list) else 0
            if not isinstance(milestones, list) or len(milestones) != 5:
                result["errors"].append(
                    f"expected 5 milestones, got {result['milestone_count']}"
                )
            else:
                for i, m in enumerate(milestones):
                    if not isinstance(m, dict):
                        result["errors"].append(f"milestone[{i}] not a dict")
                        continue
                    if "completed" not in m or not isinstance(m.get("completed"), bool):
                        result["errors"].append(
                            f"milestone[{i}] missing bool 'completed'"
                        )

    result["ok"] = not result["errors"]
    return result
