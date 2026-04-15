"""
backend.visual_qa.health_score_check — verify /api/analytics/health-score.

Hits the 4-pillar health score endpoint and validates: all pillars
present (scheduling/quality/supplier/energy), each has a score in
[0..100], and pillar weights sum to 1.0 (±0.01 to tolerate float
noise). Authentication is best-effort — if the endpoint requires a
token, the caller can pass one via ``token``.

Never raises. Returns a dict with ``ok: bool`` and details.
"""
from __future__ import annotations

from typing import Any, Optional

from .endpoint_verify import verify_endpoint


_EXPECTED_PILLARS = ("scheduling", "quality", "supplier", "energy")


def check_health_score(
    base_url: str = "http://localhost:8000",
    token: Optional[str] = None,
) -> dict[str, Any]:
    """Verify the 4-pillar health score endpoint.

    Args:
        base_url: MillForge backend base URL.
        token: optional bearer token for an authenticated request.

    Returns:
        {
          "ok": bool,
          "endpoint": str,
          "status_code": int | None,
          "pillars": {<name>: {"score": float, "weight": float}, ...},
          "weight_sum": float | None,
          "errors": [str, ...],
        }
    """
    url = base_url.rstrip("/") + "/api/analytics/health-score"
    headers = {"Authorization": f"Bearer {token}"} if token else None

    result: dict[str, Any] = {
        "ok": False,
        "endpoint": url,
        "status_code": None,
        "pillars": {},
        "weight_sum": None,
        "errors": [],
    }

    raw = verify_endpoint(url, expected_keys=[], headers=headers)
    result["status_code"] = raw.get("status_code")
    if not raw.get("response_json") and raw.get("error"):
        result["errors"].append(raw["error"])
        return result

    body = raw.get("response_json") or {}

    # Shape flexibility — some API versions nest under "pillars".
    pillars_obj = body.get("pillars") if isinstance(body, dict) else None
    if not isinstance(pillars_obj, dict):
        pillars_obj = body if isinstance(body, dict) else {}

    pillars: dict[str, dict[str, float]] = {}
    for name in _EXPECTED_PILLARS:
        p = pillars_obj.get(name)
        if p is None:
            result["errors"].append(f"missing pillar: {name}")
            continue
        if isinstance(p, (int, float)):
            score = float(p)
            weight = None
        elif isinstance(p, dict):
            score = p.get("score")
            weight = p.get("weight")
            try:
                score = float(score) if score is not None else None
            except (TypeError, ValueError):
                score = None
            try:
                weight = float(weight) if weight is not None else None
            except (TypeError, ValueError):
                weight = None
        else:
            result["errors"].append(f"pillar {name} has unexpected type {type(p).__name__}")
            continue

        if score is None or not (0.0 <= score <= 100.0):
            result["errors"].append(f"pillar {name} score out of [0..100]: {score}")
        pillars[name] = {"score": score, "weight": weight}

    result["pillars"] = pillars

    weights = [v["weight"] for v in pillars.values() if v.get("weight") is not None]
    if weights:
        wsum = sum(weights)
        result["weight_sum"] = wsum
        if abs(wsum - 1.0) > 0.01:
            result["errors"].append(f"pillar weights sum to {wsum:.3f}, expected 1.0")

    result["ok"] = (
        len(pillars) == len(_EXPECTED_PILLARS)
        and not result["errors"]
    )
    return result
