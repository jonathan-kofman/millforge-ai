"""
backend.visual_qa.supplier_recommend_check — verify /api/suppliers/recommend.

Hits the supplier recommendation endpoint with a known capability and
validates response shape: every recommendation has ``name``,
``confidence`` in [0..1], and ``state``. Also sanity-checks
``result_count >= 0``.

Never raises. Returns a dict with ``ok: bool`` and details.
"""
from __future__ import annotations

from typing import Any, Optional

from .endpoint_verify import verify_endpoint


def check_supplier_recommend(
    base_url: str = "http://localhost:8000",
    capability: str = "anodizing_line",
    limit: int = 3,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
) -> dict[str, Any]:
    """Verify supplier recommend endpoint shape + confidence bounds.

    Args:
        base_url: MillForge backend base URL.
        capability: capability string to search for.
        limit: max results to request.
        lat: optional latitude — when set, each result should have a
            ``distance_km`` (or ``distance``) field populated.
        lng: optional longitude.

    Returns:
        {
          "ok": bool,
          "endpoint": str,
          "status_code": int | None,
          "result_count": int,
          "results_valid": int,
          "errors": [str, ...],
        }
    """
    url = base_url.rstrip("/") + "/api/suppliers/recommend"
    params: dict[str, Any] = {"capability": capability, "limit": limit}
    if lat is not None and lng is not None:
        params["lat"] = lat
        params["lng"] = lng

    result: dict[str, Any] = {
        "ok": False,
        "endpoint": url,
        "status_code": None,
        "result_count": 0,
        "results_valid": 0,
        "errors": [],
    }

    raw = verify_endpoint(url, expected_keys=[], params=params)
    result["status_code"] = raw.get("status_code")
    if not raw.get("response_json") and raw.get("error"):
        result["errors"].append(raw["error"])
        return result

    body = raw.get("response_json")

    # Accept either a bare list or {"recommendations": [...]} shape.
    if isinstance(body, list):
        recs = body
    elif isinstance(body, dict):
        recs = body.get("recommendations") or body.get("results") or body.get("suppliers") or []
    else:
        result["errors"].append(f"unexpected body type {type(body).__name__}")
        return result

    if not isinstance(recs, list):
        result["errors"].append("recommendations field is not a list")
        return result

    result["result_count"] = len(recs)
    if len(recs) < 0:  # defensive, should never fire
        result["errors"].append("result_count < 0")

    valid = 0
    for i, r in enumerate(recs):
        if not isinstance(r, dict):
            result["errors"].append(f"result[{i}] not a dict")
            continue
        name = r.get("name")
        confidence = r.get("confidence")
        state = r.get("state")

        problems: list[str] = []
        if not isinstance(name, str) or not name:
            problems.append("missing name")
        if not isinstance(state, str) or not state:
            problems.append("missing state")
        try:
            conf_f = float(confidence)
            if not (0.0 <= conf_f <= 1.0):
                problems.append(f"confidence {conf_f} out of [0..1]")
        except (TypeError, ValueError):
            problems.append(f"confidence not a number: {confidence!r}")

        if lat is not None and lng is not None:
            dist = r.get("distance_km", r.get("distance"))
            if dist is None:
                problems.append("distance missing (lat/lng supplied)")

        if problems:
            result["errors"].append(f"result[{i}] ({name!r}): {'; '.join(problems)}")
        else:
            valid += 1

    result["results_valid"] = valid
    result["ok"] = (
        not result["errors"]
        and result["result_count"] >= 0
        and (result["result_count"] == 0 or valid == result["result_count"])
    )
    return result
