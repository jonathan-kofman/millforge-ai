"""
Unit tests for SupplierDirectory agent and /api/suppliers endpoints.

Ten tests:
  1. Empty list returns zero results
  2. Create supplier persists to DB
  3. Get by ID returns correct supplier
  4. Filter by material
  5. Filter by state
  6. Filter by category
  7. Nearby within radius returns match
  8. Nearby outside radius excludes supplier
  9. Pagination (skip/limit)
 10. List materials returns all categories
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker

from database import Base
from db_models import Supplier
from agents.supplier_directory import SupplierDirectory, haversine_miles, MATERIAL_CATEGORIES


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture()
def directory():
    return SupplierDirectory()


def _make_supplier(db, directory, **kwargs):
    defaults = dict(
        name="Acme Steel",
        city="Cleveland",
        state="OH",
        lat=41.49,
        lng=-81.69,
        materials=["steel", "aluminum"],
        verified=True,
        data_source="manual",
    )
    defaults.update(kwargs)
    return directory.create(db, **defaults)


# ---------------------------------------------------------------------------
# 1. Empty list
# ---------------------------------------------------------------------------

def test_empty_list(db, directory):
    suppliers, total = directory.search(db)
    assert total == 0
    assert suppliers == []


# ---------------------------------------------------------------------------
# 2. Create supplier
# ---------------------------------------------------------------------------

def test_create_supplier(db, directory):
    s = _make_supplier(db, directory)
    assert s.id is not None
    assert s.name == "Acme Steel"
    assert "steel" in s.materials
    assert s.verified is True


# ---------------------------------------------------------------------------
# 3. Get by ID
# ---------------------------------------------------------------------------

def test_get_by_id(db, directory):
    s = _make_supplier(db, directory, name="Beta Metals", city="Akron", state="OH")
    found = directory.get_by_id(db, s.id)
    assert found is not None
    assert found.name == "Beta Metals"


def test_get_by_id_missing(db, directory):
    assert directory.get_by_id(db, 99999) is None


# ---------------------------------------------------------------------------
# 4. Filter by material
# ---------------------------------------------------------------------------

def test_filter_by_material(db, directory):
    _make_supplier(db, directory, name="Steel Only", materials=["steel"])
    _make_supplier(db, directory, name="Titanium Spec", materials=["titanium"])
    suppliers, total = directory.search(db, material="titanium")
    assert total == 1
    assert suppliers[0].name == "Titanium Spec"


# ---------------------------------------------------------------------------
# 5. Filter by state
# ---------------------------------------------------------------------------

def test_filter_by_state(db, directory):
    _make_supplier(db, directory, name="Ohio Co", state="OH")
    _make_supplier(db, directory, name="Texas Co", state="TX")
    suppliers, total = directory.search(db, state="TX")
    assert total == 1
    assert suppliers[0].name == "Texas Co"


# ---------------------------------------------------------------------------
# 6. Filter by category
# ---------------------------------------------------------------------------

def test_filter_by_category(db, directory):
    _make_supplier(db, directory, name="Metal House", materials=["steel"], categories=["metals"])
    _make_supplier(db, directory, name="Plastic Co", materials=["abs"], categories=["plastics"])
    suppliers, total = directory.search(db, category="plastics")
    assert total == 1
    assert suppliers[0].name == "Plastic Co"


# ---------------------------------------------------------------------------
# 7. Nearby within radius
# ---------------------------------------------------------------------------

def test_nearby_within_radius(db, directory):
    # Cleveland, OH: lat=41.49, lng=-81.69
    _make_supplier(db, directory, name="Close Supplier", lat=41.49, lng=-81.69)
    results = directory.nearby(db, lat=41.50, lng=-81.70, radius_miles=50.0)
    assert len(results) == 1
    assert results[0][0].name == "Close Supplier"
    assert results[0][1] < 10.0  # less than 10 miles away


# ---------------------------------------------------------------------------
# 8. Nearby outside radius
# ---------------------------------------------------------------------------

def test_nearby_outside_radius(db, directory):
    # Put supplier in Miami, search from Seattle
    _make_supplier(db, directory, name="Far Supplier", lat=25.77, lng=-80.19)
    results = directory.nearby(db, lat=47.61, lng=-122.33, radius_miles=100.0)
    assert len(results) == 0


# ---------------------------------------------------------------------------
# 9. Pagination
# ---------------------------------------------------------------------------

def test_pagination(db, directory):
    for i in range(10):
        _make_supplier(db, directory, name=f"Supplier {i:02d}", state="OH")
    # All 10
    _, total = directory.search(db)
    assert total == 10
    # Skip 5, limit 3 → 3 results, total still 10
    page, total2 = directory.search(db, skip=5, limit=3)
    assert total2 == 10
    assert len(page) == 3


# ---------------------------------------------------------------------------
# 10. List materials
# ---------------------------------------------------------------------------

def test_list_materials():
    data = SupplierDirectory.list_materials()
    assert "categories" in data
    assert "all_materials" in data
    assert "metals" in data["categories"]
    assert "steel" in data["categories"]["metals"]
    assert "steel" in data["all_materials"]
    assert len(data["all_materials"]) > 10


# ---------------------------------------------------------------------------
# Bonus: haversine accuracy
# ---------------------------------------------------------------------------

def test_haversine_nyc_la():
    # NYC to LA is ~2,445 miles
    d = haversine_miles(40.7128, -74.0060, 34.0522, -118.2437)
    assert 2400 < d < 2500
