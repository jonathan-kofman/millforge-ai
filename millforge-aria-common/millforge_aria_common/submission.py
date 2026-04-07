"""
ARIA-OS side: submit a job to MillForge with retry + exponential backoff.

Usage (from ARIA-OS after successful CAM generation):

    from millforge_aria_common import ARIAToMillForgeJob
    from millforge_aria_common.submission import submit_to_millforge

    ack = await submit_to_millforge(job, endpoint="https://api.millforge.ai")
    print(f"Queued as MillForge job #{ack.millforge_job_id}")
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .models import ARIAToMillForgeJob, MillForgeJobAck

logger = logging.getLogger(__name__)

_DEFAULT_ENDPOINT = "http://localhost:8000"
_SUBMIT_PATH = "/api/jobs/from-aria"
_STATUS_PATH = "/api/bridge/status"

# Retry configuration
_MAX_ATTEMPTS = 5
_BASE_DELAY_S = 1.0
_MAX_DELAY_S = 30.0
_BACKOFF_FACTOR = 2.0

# Retryable HTTP status codes (server-side transient errors)
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


async def submit_to_millforge(
    job: "ARIAToMillForgeJob",
    *,
    endpoint: str = _DEFAULT_ENDPOINT,
    api_key: Optional[str] = None,
    max_attempts: int = _MAX_ATTEMPTS,
) -> "MillForgeJobAck":
    """
    POST the job to MillForge with exponential backoff.

    Raises RuntimeError after max_attempts if all attempts fail.
    Raises ValueError immediately for 400/422 (payload errors — no retry).
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise ImportError(
            "aiohttp is required for ARIA-OS submission. "
            "pip install aiohttp"
        ) from exc

    from .models import MillForgeJobAck
    from .validation import validate_aria_job

    validate_aria_job(job)

    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{endpoint.rstrip('/')}{_SUBMIT_PATH}"
    payload = json.dumps(job.to_dict())
    delay = _BASE_DELAY_S

    last_error: Exception = RuntimeError("No attempts made")

    async with aiohttp.ClientSession() as session:
        for attempt in range(1, max_attempts + 1):
            try:
                async with session.post(
                    url,
                    data=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return _parse_ack(data)

                    body = await resp.text()

                    if resp.status in (400, 422):
                        # Payload error — do not retry
                        raise ValueError(
                            f"MillForge rejected job (HTTP {resp.status}): {body}"
                        )

                    if resp.status not in _RETRYABLE_STATUSES:
                        raise RuntimeError(
                            f"MillForge returned HTTP {resp.status}: {body}"
                        )

                    last_error = RuntimeError(
                        f"HTTP {resp.status} on attempt {attempt}: {body}"
                    )

            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc

            if attempt < max_attempts:
                logger.warning(
                    "submit_to_millforge attempt %d/%d failed (%s), retrying in %.1fs…",
                    attempt, max_attempts, last_error, delay,
                )
                await asyncio.sleep(delay)
                delay = min(delay * _BACKOFF_FACTOR, _MAX_DELAY_S)

    raise RuntimeError(
        f"submit_to_millforge failed after {max_attempts} attempts. "
        f"Last error: {last_error}"
    )


def _parse_ack(data: dict) -> "MillForgeJobAck":
    from datetime import datetime, timezone
    from .models import MillForgeJobAck

    received_at_raw = data.get("received_at")
    received_at = (
        datetime.fromisoformat(received_at_raw)
        if received_at_raw
        else datetime.now(timezone.utc)
    )
    estimated_start_raw = data.get("estimated_start_time")
    estimated_start = (
        datetime.fromisoformat(estimated_start_raw) if estimated_start_raw else None
    )

    return MillForgeJobAck(
        aria_job_id=data["aria_job_id"],
        millforge_job_id=data["millforge_job_id"],
        status=data["status"],
        queue_position=data.get("queue_position"),
        estimated_start_time=estimated_start,
        rejection_reason=data.get("rejection_reason"),
        received_at=received_at,
    )


async def poll_job_status(
    aria_job_id: str,
    *,
    endpoint: str = _DEFAULT_ENDPOINT,
    api_key: Optional[str] = None,
) -> dict:
    """
    Poll MillForge for the current status of an ARIA-submitted job.

    Returns the raw JSON response dict.
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise ImportError("aiohttp required. pip install aiohttp") from exc

    headers = {}
    if api_key:
        headers["X-API-Key"] = api_key

    url = f"{endpoint.rstrip('/')}{_STATUS_PATH}/{aria_job_id}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 404:
                raise ValueError(f"No MillForge job found for aria_job_id='{aria_job_id}'")
            resp.raise_for_status()
            return await resp.json()
