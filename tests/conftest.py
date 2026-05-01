"""
Shared pytest fixtures for MillForge backend tests.

SQLite in-memory quirk: each new connection() call opens a FRESH empty DB.
StaticPool reuses a single underlying connection, so all sessions (across
auth + request handlers within one test) share the same in-memory store.
"""

import sys
import os

# Disable rate limiting during tests — TestClient uses the same IP so
# the 10/hour register limit would be exhausted after 10 tests.
os.environ.setdefault("AUTH_REGISTER_RATE_LIMIT", "10000/hour")
os.environ.setdefault("AUTH_LOGIN_RATE_LIMIT", "10000/hour")

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import database as db_module
from database import Base


def _make_heuristic_vision_agent():
    """Return a QualityVisionAgent in heuristic mode (no ONNX model loaded).

    Used by the test client fixture to prevent the real ONNX agent from trying
    to download test image URLs during unit/integration tests.
    """
    from agents.quality_vision import QualityVisionAgent
    a = QualityVisionAgent.__new__(QualityVisionAgent)
    a._session = None
    a._input_name = None
    a._model_name = "heuristic"
    a._model_map50 = None
    a.MAX_RETRIES = 3
    return a


@pytest.fixture(scope="function")
def client():
    """
    TestClient with a fresh in-memory SQLite DB per test.

    Uses StaticPool so all connections within one test share the same
    in-memory database — essential for multi-request tests (register then
    login, create then fetch, etc.).
    """
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Patch module globals: init_db() and get_db() will use test_engine
    original_engine = db_module.engine
    original_session_local = db_module.SessionLocal

    db_module.engine = test_engine
    db_module.SessionLocal = TestingSessionLocal

    # Create all tables before running tests
    Base.metadata.create_all(bind=test_engine)

    from main import app

    # Force heuristic vision mode so tests never try to download real image URLs
    import routers.vision as _vision_mod
    original_vision_agent = _vision_mod._vision_agent
    original_model_startup_check = _vision_mod._model_startup_check
    _vision_mod._vision_agent = _make_heuristic_vision_agent()
    # Initialize model startup check so endpoints don't fail
    _vision_mod._model_startup_check = {
        "available": True,
        "status": "test mode (heuristic agent)",
    }

    with TestClient(app) as c:
        yield c

    _vision_mod._vision_agent = original_vision_agent
    _vision_mod._model_startup_check = original_model_startup_check
    db_module.engine = original_engine
    db_module.SessionLocal = original_session_local
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
