"""
Shared pytest fixtures for MillForge backend tests.

SQLite in-memory quirk: each new connection() call opens a FRESH empty DB.
StaticPool reuses a single underlying connection, so all sessions (across
auth + request handlers within one test) share the same in-memory store.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import database as db_module
from database import Base


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
    with TestClient(app) as c:
        yield c

    db_module.engine = original_engine
    db_module.SessionLocal = original_session_local
    Base.metadata.drop_all(bind=test_engine)
    test_engine.dispose()
