"""MillForge Feature Flag System.

Two-layer architecture:
  1. Compile-time BuildFeatures  — set via BUILD_PROFILE env var or profile name.
     Immutable once loaded. Determines which modules are even imported.

  2. Runtime flags               — per-request or per-session overrides.
     Cached with a configurable TTL (default 60 s). Acceptable staleness
     for A/B tests and progressive rollouts.

Build profiles:
  demo      — YC pitch / investor demo; minimal surface area, sample data locked
  free      — Basic scheduling only; no vision, no supplier map
  pro       — Full features minus debug tools
  internal  — Everything on, including benchmarking and prompt logging

Usage::

    from config.features import features, get_feature_cached, requires_feature

    if features.QUALITY_INSPECTION:
        from agents.quality_vision import QualityVisionAgent

    @router.get("/inspect")
    @requires_feature("QUALITY_INSPECTION")
    async def inspect_part(...): ...

    # Runtime A/B flag
    if get_feature_cached("new_gantt_ui"):
        return render_new_gantt()
"""
from __future__ import annotations

import asyncio
import functools
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# ── Compile-time flags ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BuildFeatures:
    """
    Immutable set of compile-time feature flags.

    All flags are booleans. Changing these requires a process restart.
    Gated imports (quality vision, PDF export, etc.) should always be
    wrapped in `if features.FLAG:` to keep startup clean and deps optional.
    """
    DEMO_MODE: bool = False             # YC demo build — locks data, disables mutations
    QUALITY_INSPECTION: bool = True     # YOLOv8 ONNX defect detection
    SUPPLIER_DIRECTORY: bool = True     # 1,137-supplier map + geo-search
    BULK_IMPORT: bool = True            # CSV order import
    PDF_EXPORT: bool = True             # Schedule PDF generation
    BENCHMARK_MODE: bool = False        # /api/schedule/benchmark endpoint exposure
    DEBUG_PROMPTS: bool = False         # Dump LLM system prompts to data/debug/prompts/
    ENERGY_OPTIMIZER: bool = True       # EIA API grid pricing + NPV scenarios
    DISCOVERY_MODULE: bool = True       # Customer interview / Ollama synthesis
    COORDINATOR_MODE: bool = True       # Multi-agent coordinator pipeline
    TOOL_GATING: bool = True            # Permission-gated tool system
    MEMORY_CONSOLIDATION: bool = True   # Background knowledge consolidation
    MANUFACTURING_LAYER: bool = True    # Process-agnostic manufacturing abstraction
    NL_SCHEDULER: bool = False          # Natural-language schedule instructions (expensive)
    DIGITAL_TWIN: bool = True           # ML setup-time predictor + calibration loop


# ── Build profiles ────────────────────────────────────────────────────────────

_PROFILES: dict[str, BuildFeatures] = {
    "demo": BuildFeatures(
        DEMO_MODE=True,
        QUALITY_INSPECTION=True,
        SUPPLIER_DIRECTORY=True,
        BULK_IMPORT=False,
        PDF_EXPORT=True,
        BENCHMARK_MODE=True,       # show the on-time improvement number
        DEBUG_PROMPTS=False,
        ENERGY_OPTIMIZER=True,
        DISCOVERY_MODULE=False,
        COORDINATOR_MODE=False,
        TOOL_GATING=False,
        MEMORY_CONSOLIDATION=False,
        MANUFACTURING_LAYER=True,
        NL_SCHEDULER=False,
        DIGITAL_TWIN=False,
    ),
    "free": BuildFeatures(
        DEMO_MODE=False,
        QUALITY_INSPECTION=False,
        SUPPLIER_DIRECTORY=False,
        BULK_IMPORT=False,
        PDF_EXPORT=False,
        BENCHMARK_MODE=False,
        DEBUG_PROMPTS=False,
        ENERGY_OPTIMIZER=False,
        DISCOVERY_MODULE=False,
        COORDINATOR_MODE=False,
        TOOL_GATING=True,
        MEMORY_CONSOLIDATION=False,
        MANUFACTURING_LAYER=False,
        NL_SCHEDULER=False,
        DIGITAL_TWIN=False,
    ),
    "pro": BuildFeatures(
        DEMO_MODE=False,
        QUALITY_INSPECTION=True,
        SUPPLIER_DIRECTORY=True,
        BULK_IMPORT=True,
        PDF_EXPORT=True,
        BENCHMARK_MODE=False,
        DEBUG_PROMPTS=False,
        ENERGY_OPTIMIZER=True,
        DISCOVERY_MODULE=False,
        COORDINATOR_MODE=True,
        TOOL_GATING=True,
        MEMORY_CONSOLIDATION=True,
        MANUFACTURING_LAYER=True,
        NL_SCHEDULER=False,
        DIGITAL_TWIN=True,
    ),
    "internal": BuildFeatures(
        DEMO_MODE=False,
        QUALITY_INSPECTION=True,
        SUPPLIER_DIRECTORY=True,
        BULK_IMPORT=True,
        PDF_EXPORT=True,
        BENCHMARK_MODE=True,
        DEBUG_PROMPTS=True,
        ENERGY_OPTIMIZER=True,
        DISCOVERY_MODULE=True,
        COORDINATOR_MODE=True,
        TOOL_GATING=True,
        MEMORY_CONSOLIDATION=True,
        MANUFACTURING_LAYER=True,
        NL_SCHEDULER=True,
        DIGITAL_TWIN=True,
    ),
}

_DEFAULT_PROFILE = "pro"


def load_build_features(profile: str | None = None) -> BuildFeatures:
    """
    Load BuildFeatures from a named profile.

    Resolution order:
      1. `profile` argument
      2. BUILD_PROFILE env var
      3. Default ("pro")

    Individual flags can be overridden by env vars after profile load:
      FEATURE_DEMO_MODE=true
      FEATURE_BENCHMARK_MODE=false
    """
    resolved = profile or os.getenv("BUILD_PROFILE", _DEFAULT_PROFILE).lower()
    if resolved not in _PROFILES:
        logger.warning("Unknown build profile '%s' — falling back to '%s'", resolved, _DEFAULT_PROFILE)
        resolved = _DEFAULT_PROFILE

    base = _PROFILES[resolved]
    logger.info("Build profile loaded: %s", resolved)

    # Allow env-var overrides for individual flags
    overrides: dict[str, bool] = {}
    for flag_name in base.__dataclass_fields__:
        env_key = f"FEATURE_{flag_name}"
        env_val = os.getenv(env_key)
        if env_val is not None:
            overrides[flag_name] = env_val.lower() in ("1", "true", "yes")
            logger.info("Feature override: %s=%s (from env)", flag_name, overrides[flag_name])

    if overrides:
        # dataclass is frozen — replace with a new instance
        current = {f: getattr(base, f) for f in base.__dataclass_fields__}
        current.update(overrides)
        return BuildFeatures(**current)

    return base


# Module-level singleton — loaded once at import time
features: BuildFeatures = load_build_features()


def reload_features(profile: str | None = None) -> BuildFeatures:
    """Reload the module-level features singleton (useful in tests)."""
    global features  # noqa: PLW0603
    features = load_build_features(profile)
    return features


# ── Runtime flags (cached, GrowthBook-style) ──────────────────────────────────

_runtime_cache: dict[str, tuple[bool, float]] = {}  # flag → (value, expires_at)
_RUNTIME_CACHE_TTL = float(os.getenv("FEATURE_CACHE_TTL_SECONDS", "60"))


def _load_runtime_flag(flag: str, default: bool) -> bool:
    """
    Load a runtime flag value.

    Sources (in order):
      1. RUNTIME_FEATURE_{FLAG} env var
      2. default
    """
    env_val = os.getenv(f"RUNTIME_FEATURE_{flag.upper()}")
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes")
    return default


def get_feature_cached(flag: str, default: bool = False) -> bool:
    """
    Return the current value of a runtime feature flag.

    May be stale up to _RUNTIME_CACHE_TTL seconds — acceptable for A/B gates
    and progressive rollouts. Use compile-time `features.FLAG` for hard gates.
    """
    now = time.monotonic()
    cached = _runtime_cache.get(flag)
    if cached is not None and now < cached[1]:
        return cached[0]

    value = _load_runtime_flag(flag, default)
    _runtime_cache[flag] = (value, now + _RUNTIME_CACHE_TTL)
    return value


def set_runtime_feature(flag: str, value: bool, *, ttl: float | None = None) -> None:
    """Programmatically set a runtime flag (e.g. from a feature management API)."""
    expires = time.monotonic() + (ttl if ttl is not None else _RUNTIME_CACHE_TTL)
    _runtime_cache[flag] = (value, expires)
    logger.debug("Runtime feature set: %s=%s (expires in %.0fs)", flag, value, ttl or _RUNTIME_CACHE_TTL)


def invalidate_feature_cache() -> None:
    """Force all cached runtime flags to reload on next access."""
    _runtime_cache.clear()
    logger.debug("Runtime feature cache invalidated")


# ── @requires_feature decorator ───────────────────────────────────────────────

class FeatureDisabledError(Exception):
    """Raised when a feature-gated endpoint is called but the flag is off."""
    def __init__(self, flag: str) -> None:
        self.flag = flag
        super().__init__(f"Feature '{flag}' is not enabled in this build.")


def requires_feature(flag: str) -> Callable[[F], F]:
    """
    Decorator that gates a function or FastAPI endpoint behind a compile-time flag.

    Usage::

        @router.get("/inspect")
        @requires_feature("QUALITY_INSPECTION")
        async def inspect_part(req: InspectionRequest): ...

    Raises FeatureDisabledError (→ HTTP 501 if caught by FastAPI exception handler)
    when the flag is False.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not getattr(features, flag, False):
                raise FeatureDisabledError(flag)
            return await func(*args, **kwargs)

        @functools.wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            if not getattr(features, flag, False):
                raise FeatureDisabledError(flag)
            return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper  # type: ignore[return-value]

    return decorator


# ── Diagnostics ───────────────────────────────────────────────────────────────

def feature_report() -> dict[str, Any]:
    """Return a summary of the current feature state (for /health or /debug endpoints)."""
    profile = os.getenv("BUILD_PROFILE", _DEFAULT_PROFILE)
    compile_time = {f: getattr(features, f) for f in features.__dataclass_fields__}
    runtime_snapshot = {
        flag: {"value": val, "expires_in_seconds": round(exp - time.monotonic(), 1)}
        for flag, (val, exp) in _runtime_cache.items()
    }
    return {
        "build_profile": profile,
        "compile_time_flags": compile_time,
        "runtime_flags_cached": runtime_snapshot,
        "cache_ttl_seconds": _RUNTIME_CACHE_TTL,
    }
