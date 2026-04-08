"""
ARIA-OS schema version registry.

Each ARIA CAM setup sheet version has a normalizer that maps its raw fields
to MillForge's internal canonical shape. To support a new ARIA schema version:

  1. Write a _normalize_vX function below.
  2. Register it in NORMALIZERS.
  3. Deploy MillForge BEFORE deploying the new ARIA version.

The import endpoint (POST /api/jobs/import-from-cam) dispatches through
normalize() — it has no version knowledge of its own.
"""

import logging
import os
from typing import Callable

import httpx

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------
# Each function receives the raw dict ARIA sent and returns a dict whose
# keys match MillForge's CAMImport Pydantic model (schema_version "1.0" shape).

def _normalize_v1(raw: dict) -> dict:
    """v1.0 — canonical shape with stock_dims key normalization."""
    out = dict(raw)
    # Normalize stock_dims: ARIA may emit x_mm/y_mm/z_mm instead of length/width/height
    sd = out.get("stock_dims", {}) or {}
    if "x_mm" in sd and "length_mm" not in sd:
        out["stock_dims"] = {
            "length_mm": sd.get("x_mm", 100.0),
            "width_mm":  sd.get("y_mm", 100.0),
            "height_mm": sd.get("z_mm", 10.0),
        }
    return out


def _normalize_v2(raw: dict) -> dict:
    """
    v2.0 — Multi-process setup sheet normalizer.

    New fields in v2:
      - process_type         (str) : e.g. "cnc_milling", "welding_arc", "cutting_laser"
      - process_parameters   (dict): generic process-specific parameters
      - consumables          (list): [{"name": str, "quantity": float, "unit": str}]
      - quality_standards    (list): e.g. ["AWS D1.1", "ASME IX"]
      - energy_profile       (dict): {"base_power_kw": float, "peak_power_kw": float}

    Normalization strategy:
      1. Carry forward all v1 fields unchanged (backward-compatible superset).
      2. If process_type is missing, default to "cnc_milling" (preserves v1 behaviour).
      3. Merge process_parameters into setup_sheet if present.
      4. Normalize schema_version to "1.0" so downstream CAMImport models work unchanged.
    """
    out = dict(raw)

    # Default process_type to cnc_milling for backward compat with v1 payloads
    if "process_type" not in out:
        out["process_type"] = "cnc_milling"

    # Ensure process_parameters is a dict, not None or missing
    if "process_parameters" not in out or out["process_parameters"] is None:
        out["process_parameters"] = {}

    # Ensure consumables is a list
    if "consumables" not in out or out["consumables"] is None:
        out["consumables"] = []

    # Ensure quality_standards is a list
    if "quality_standards" not in out or out["quality_standards"] is None:
        out["quality_standards"] = []

    # Ensure energy_profile is a dict
    if "energy_profile" not in out or out["energy_profile"] is None:
        out["energy_profile"] = {}

    # Normalise schema_version to "1.0" so the existing CAMImport Pydantic model
    # validates correctly (it was written for v1 shape; v2 is a strict superset).
    out["schema_version"] = "1.0"

    return out


def _rename(d: dict, old: str, new: str) -> None:
    """Rename a key in-place if it exists and the new key is absent."""
    if old in d and new not in d:
        d[new] = d.pop(old)


# ---------------------------------------------------------------------------
# Registry — add new entries here when ARIA ships a new version
# ---------------------------------------------------------------------------

NORMALIZERS: dict[str, Callable[[dict], dict]] = {
    "1.0": _normalize_v1,
    "2.0": _normalize_v2,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class UnsupportedAriaSchemaVersion(ValueError):
    pass


def normalize(raw: dict) -> dict:
    """
    Normalize a raw ARIA CAM payload to MillForge's internal canonical shape.

    Dispatches to the registered normalizer for raw["schema_version"].
    Raises UnsupportedAriaSchemaVersion if no normalizer is registered for
    that version — this is the only place that gate lives.
    """
    version = raw.get("schema_version", "")
    normalizer = NORMALIZERS.get(version)
    if normalizer is None:
        supported = sorted(NORMALIZERS.keys())
        raise UnsupportedAriaSchemaVersion(
            f"Unsupported ARIA schema version '{version}'. "
            f"MillForge supports: {supported}. "
            "Add a normalizer to services/aria_schema.py and deploy MillForge "
            "before rolling out the new ARIA schema version."
        )
    out = normalizer(raw)
    logger.debug("ARIA payload normalised: version=%s part_id=%s", version, raw.get("part_id"))
    return out


def supported_versions() -> list[str]:
    """Return sorted list of ARIA schema versions this MillForge instance handles."""
    return sorted(NORMALIZERS.keys())


async def probe_aria_version() -> str | None:
    """
    Fetch the schema version ARIA is currently emitting.

    Reads ARIA_API_BASE from the environment (e.g. http://aria-os.internal).
    Expects ARIA to expose GET {ARIA_API_BASE}/schema-version → {"schema_version": "1.0"}.

    Returns the version string, or None if ARIA_API_BASE is not set or the
    request fails. Never raises — used only for startup diagnostics.
    """
    base = os.getenv("ARIA_API_BASE", "").rstrip("/")
    if not base:
        return None
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base}/schema-version")
            resp.raise_for_status()
            version = resp.json().get("schema_version")
            logger.info("ARIA reports schema_version=%s", version)
            return version
    except Exception as exc:
        logger.warning("ARIA version probe failed (%s): %s", base, exc)
        return None


async def check_aria_compatibility() -> None:
    """
    Startup check: probe ARIA's current schema version and warn if MillForge
    has no normalizer registered for it.

    Logs a WARNING (not an exception) so a missing or unreachable ARIA instance
    never prevents MillForge from starting.
    """
    aria_version = await probe_aria_version()
    if aria_version is None:
        logger.info(
            "ARIA version probe skipped (ARIA_API_BASE not set). "
            "MillForge supports: %s", supported_versions()
        )
        return

    if aria_version not in NORMALIZERS:
        logger.warning(
            "ARIA is emitting schema_version='%s' but MillForge has no normalizer "
            "for it. Jobs from ARIA will be rejected with 400 until a normalizer "
            "is added to services/aria_schema.py. Supported: %s",
            aria_version, supported_versions(),
        )
    else:
        logger.info(
            "ARIA schema compatibility confirmed: version=%s is supported.", aria_version
        )
