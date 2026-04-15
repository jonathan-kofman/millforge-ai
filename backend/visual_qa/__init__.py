"""
backend.visual_qa — visual verification framework for MillForge endpoints.

Lightweight, dependency-free (aside from ``requests``) checks that hit
the FastAPI backend and verify response shape, types, and value ranges.
Designed to complement ``aria_os.visual_qa`` which handles file-based
artifacts (DXF/STL). This package focuses on HTTP endpoints — JSON
responses from FastAPI routers.

Contract: every check function returns a dict with at least an
``ok: bool`` key and an ``error`` key on failure. Nothing raises.
"""

from .endpoint_verify import verify_endpoint
from .health_score_check import check_health_score
from .onboarding_check import check_onboarding_templates
from .supplier_recommend_check import check_supplier_recommend

__all__ = [
    "verify_endpoint",
    "check_health_score",
    "check_onboarding_templates",
    "check_supplier_recommend",
]
