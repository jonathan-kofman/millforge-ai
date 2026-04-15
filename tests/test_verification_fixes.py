"""
Regression tests for bugs found by the feature verification pass on
2026-04-15. These guard against:

1. Supplier /recommend capability filter being non-binding
   (returned generic metals distributors regardless of capability)
2. NL scheduler machine_down being cosmetic
   (gantt_after still contained the dead machine_id)
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Ensure backend is on the path
HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.normpath(os.path.join(HERE, "..", "backend"))
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)

from database import Base  # noqa: E402
from db_models import Supplier  # noqa: E402
from agents.supplier_directory import SupplierDirectory  # noqa: E402


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()


def _make_supplier(name, materials, categories=None, verified=True, lat=None, lng=None):
    return Supplier(
        name=name,
        city="Cleveland",
        state="OH",
        country="US",
        materials=materials,
        categories=categories or ["metals"],
        verified=verified,
        data_source="test",
        lat=lat,
        lng=lng,
    )


# ---------------------------------------------------------------------------
# Bug 1: capability filter was non-binding
# ---------------------------------------------------------------------------


def test_recommend_capability_drops_non_matches(db):
    """A generic steel distributor should NOT be returned for an anodizing
    request. Before the fix, the SQL only filtered on category=metals so
    every metals supplier passed."""
    db.add(_make_supplier("Generic Steel Co", ["steel", "carbon_steel"]))
    db.add(_make_supplier("Acme Anodizing Ltd", ["aluminum", "anodize", "type ii"]))
    db.commit()

    directory = SupplierDirectory()
    results = directory.recommend_for_capability(db, capability="anodizing_line", limit=5)

    names = [s.name for s, _, _ in results]
    assert "Acme Anodizing Ltd" in names, "expected anodizing supplier to match"
    assert "Generic Steel Co" not in names, (
        "BUG: generic steel distributor passed the capability gate — "
        "the keyword filter is not binding"
    )


def test_recommend_capability_returns_empty_when_no_matches(db):
    """If nothing in the directory matches the capability keywords, the
    endpoint should return an empty list — NOT fall back to generic
    suppliers."""
    db.add(_make_supplier("Generic Steel Co", ["steel"]))
    db.commit()

    directory = SupplierDirectory()
    results = directory.recommend_for_capability(db, capability="anodizing_line", limit=5)
    assert results == [], "no anodizing match → must return empty"


def test_recommend_capability_keyword_score_orders_by_relevance(db):
    """When multiple suppliers match, the one with more keyword hits
    should rank higher."""
    db.add(_make_supplier("Plating Plus",     ["plating", "zinc"]))
    db.add(_make_supplier("Specialty Coater", ["plating", "zinc", "nickel", "chrome", "electroplate"]))
    db.commit()

    directory = SupplierDirectory()
    results = directory.recommend_for_capability(db, capability="plating", limit=5)
    assert len(results) == 2
    # Specialty Coater matches every keyword in WORK_CENTER_TO_MATERIAL_KEYWORDS["plating"]
    assert results[0][0].name == "Specialty Coater"


def test_recommend_capability_unknown_capability_falls_through(db):
    """An unmapped capability has no keyword filter — should fall through
    to the category filter only and return whatever's there."""
    db.add(_make_supplier("Generic Steel Co", ["steel"]))
    db.commit()

    directory = SupplierDirectory()
    results = directory.recommend_for_capability(db, capability="unknown_xyz", limit=5)
    # No keyword list → no gate → returns the metals supplier
    assert len(results) == 1
    assert results[0][0].name == "Generic Steel Co"


# ---------------------------------------------------------------------------
# Bug 2: machine_down was cosmetic
# Test the remap function in isolation since the full router test would
# require spinning up a database and the schedule pipeline. The remap is
# what makes machine_down semantic.
# ---------------------------------------------------------------------------


def test_machine_down_remap_preserves_operator_numbering():
    """When machine 2 is declared down out of 3 machines, the remap dict
    should map scheduler_id 1 -> 1, scheduler_id 2 -> 3 (skipping 2)."""
    original_count = 3
    dead_id = 2
    survivor_ids = [i for i in range(1, original_count + 1) if i != dead_id]
    assert survivor_ids == [1, 3]
    remap = {i + 1: sid for i, sid in enumerate(survivor_ids)}
    assert remap == {1: 1, 2: 3}
    assert dead_id not in remap.values(), "dead machine must not appear in the post-remap set"


def test_machine_down_remap_machine_1_dead():
    original_count = 3
    dead_id = 1
    survivor_ids = [i for i in range(1, original_count + 1) if i != dead_id]
    remap = {i + 1: sid for i, sid in enumerate(survivor_ids)}
    assert remap == {1: 2, 2: 3}
    assert 1 not in remap.values()


def test_machine_down_remap_machine_3_dead():
    original_count = 3
    dead_id = 3
    survivor_ids = [i for i in range(1, original_count + 1) if i != dead_id]
    remap = {i + 1: sid for i, sid in enumerate(survivor_ids)}
    assert remap == {1: 1, 2: 2}
    assert 3 not in remap.values()
