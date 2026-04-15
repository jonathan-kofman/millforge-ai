"""
backend.visual_qa.endpoint_verify — generic HTTP endpoint shape checker.

Hits an HTTP endpoint with ``requests``, verifies the response shape
against a list of expected top-level keys, and runs optional per-key
validator callables. The building block used by the specific
``*_check.py`` modules in this package.

Contract: never raises. Returns a dict with ``ok: bool``, the request
status code, a list of missing keys, and a list of validation
failures. On transport/JSON errors, ``ok=False`` and an ``error`` key
is set.
"""
from __future__ import annotations

from typing import Any, Callable, Optional


# Default HTTP timeout per hard-constraint (10s).
_DEFAULT_TIMEOUT = 10.0


def verify_endpoint(
    url: str,
    expected_keys: list[str],
    validators: Optional[dict[str, Callable[[Any], bool]]] = None,
    method: str = "GET",
    params: Optional[dict[str, Any]] = None,
    json_body: Optional[dict[str, Any]] = None,
    headers: Optional[dict[str, str]] = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Verify an HTTP endpoint's response shape.

    Args:
        url: full URL to hit.
        expected_keys: top-level keys that must appear in the JSON body.
        validators: optional map of {key: callable(value) -> bool}. Any
            returning False (or raising) records a validation failure.
        method: HTTP method, default GET.
        params: querystring dict.
        json_body: JSON POST body.
        headers: request headers.
        timeout: seconds, default 10.

    Returns:
        {
          "ok": bool,
          "url": str,
          "status_code": int | None,
          "missing_keys": [str, ...],
          "validation_failures": [{"key","reason"}, ...],
          "response_json": dict | None,
          "error": str  (only when ok=False due to transport/JSON error)
        }
    """
    result: dict[str, Any] = {
        "ok": False,
        "url": url,
        "status_code": None,
        "missing_keys": [],
        "validation_failures": [],
        "response_json": None,
    }

    try:
        import requests  # type: ignore
    except Exception as exc:
        result["error"] = f"requests import failed: {exc}"
        return result

    try:
        resp = requests.request(
            method=method.upper(),
            url=url,
            params=params,
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
    except Exception as exc:
        result["error"] = f"request failed: {exc}"
        return result

    result["status_code"] = resp.status_code

    if resp.status_code >= 400:
        result["error"] = f"HTTP {resp.status_code}: {resp.text[:300]}"
        return result

    try:
        body = resp.json()
    except Exception as exc:
        result["error"] = f"response was not JSON: {exc}"
        return result

    result["response_json"] = body

    if not isinstance(body, dict):
        # Some endpoints return lists — in that case expected_keys must
        # be empty, and validators keyed with "__root__" run on the list.
        if expected_keys:
            result["error"] = f"expected dict body with keys, got {type(body).__name__}"
            return result
        missing: list[str] = []
    else:
        missing = [k for k in expected_keys if k not in body]
    result["missing_keys"] = missing

    failures: list[dict[str, str]] = []
    if validators:
        for key, fn in validators.items():
            try:
                if key == "__root__":
                    value = body
                else:
                    if not isinstance(body, dict) or key not in body:
                        failures.append({"key": key, "reason": "key missing"})
                        continue
                    value = body[key]
                ok = bool(fn(value))
                if not ok:
                    failures.append({"key": key, "reason": "validator returned False"})
            except Exception as exc:
                failures.append({"key": key, "reason": f"validator raised: {exc}"})
    result["validation_failures"] = failures

    result["ok"] = (not missing) and (not failures)
    return result
