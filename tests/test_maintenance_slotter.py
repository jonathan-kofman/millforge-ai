"""Tests for backend.agents.maintenance_slotter."""

import json
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from db_models import ScheduleRun
from agents.maintenance_slotter import find_maintenance_window


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    s = SessionLocal()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _make_run(db, scheduled: list[dict]) -> ScheduleRun:
    run = ScheduleRun(
        algorithm="SA",
        order_ids_json=json.dumps([e.get("order_id", f"o{i}") for i, e in enumerate(scheduled)]),
        summary_json=json.dumps({"dummy": True}),
        on_time_rate=0.95,
        makespan_hours=24.0,
        schedule_json=json.dumps(scheduled),
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


class TestFindMaintenanceWindow:

    def test_no_schedule_returns_immediate_slot(self, db_session):
        now = datetime(2026, 4, 14, 8, 0)
        r = find_maintenance_window(db_session, machine_id=1, duration_minutes=60, reference_time=now)
        assert r["slot"] is True
        assert r["reason"] == "no_active_schedule_machine_idle"
        assert r["slot_start"] == now.isoformat()
        assert r["slot_end"] == (now + timedelta(minutes=60)).isoformat()

    def test_no_operations_on_machine_returns_immediate(self, db_session):
        now = datetime(2026, 4, 14, 8, 0)
        _make_run(db_session, [
            {"order_id": "o1", "machine_id": 2,
             "start_time": now.isoformat(),
             "end_time": (now + timedelta(hours=2)).isoformat()},
        ])
        r = find_maintenance_window(db_session, machine_id=1, duration_minutes=90, reference_time=now)
        assert r["slot"] is True
        assert r["reason"] == "no_operations_on_machine"

    def test_gap_found_between_two_jobs(self, db_session):
        now = datetime(2026, 4, 14, 8, 0)
        _make_run(db_session, [
            {"order_id": "o1", "machine_id": 1,
             "start_time": now.isoformat(),
             "end_time": (now + timedelta(hours=2)).isoformat()},
            {"order_id": "o2", "machine_id": 1,
             "start_time": (now + timedelta(hours=5)).isoformat(),
             "end_time": (now + timedelta(hours=7)).isoformat()},
        ])
        # Need 60 min, gap is 180 min between hours 2 and 5.
        r = find_maintenance_window(db_session, machine_id=1, duration_minutes=60, reference_time=now)
        assert r["slot"] is True
        assert r["reason"] == "gap_found"
        start = datetime.fromisoformat(r["slot_start"])
        end = datetime.fromisoformat(r["slot_end"])
        assert start == now + timedelta(hours=2)
        assert end == now + timedelta(hours=3)

    def test_gap_too_small_skipped_finds_later(self, db_session):
        now = datetime(2026, 4, 14, 8, 0)
        _make_run(db_session, [
            {"order_id": "o1", "machine_id": 1,
             "start_time": now.isoformat(),
             "end_time": (now + timedelta(hours=2)).isoformat()},
            # 30 min gap, not enough for a 60-min task
            {"order_id": "o2", "machine_id": 1,
             "start_time": (now + timedelta(hours=2, minutes=30)).isoformat(),
             "end_time": (now + timedelta(hours=4)).isoformat()},
            # then unbounded tail (gap through end of horizon)
        ])
        r = find_maintenance_window(db_session, machine_id=1, duration_minutes=60, reference_time=now)
        assert r["slot"] is True
        assert r["reason"] == "gap_found"
        start = datetime.fromisoformat(r["slot_start"])
        # Should start right after the second job ends.
        assert start == now + timedelta(hours=4)

    def test_no_gap_in_horizon(self, db_session):
        now = datetime(2026, 4, 14, 8, 0)
        # Single continuous job filling the whole horizon.
        _make_run(db_session, [
            {"order_id": "o1", "machine_id": 1,
             "start_time": now.isoformat(),
             "end_time": (now + timedelta(hours=48)).isoformat()},
        ])
        r = find_maintenance_window(db_session, machine_id=1, duration_minutes=60,
                                     horizon_hours=24, reference_time=now)
        assert r["slot"] is False
        assert r["reason"] == "no_sufficient_gap_in_horizon"

    def test_invalid_duration_raises(self, db_session):
        with pytest.raises(ValueError):
            find_maintenance_window(db_session, machine_id=1, duration_minutes=0)

    def test_invalid_horizon_raises(self, db_session):
        with pytest.raises(ValueError):
            find_maintenance_window(db_session, machine_id=1, duration_minutes=60, horizon_hours=-1)

    def test_only_future_operations_counted(self, db_session):
        now = datetime(2026, 4, 14, 12, 0)
        _make_run(db_session, [
            # Ended in the past — ignored
            {"order_id": "past", "machine_id": 1,
             "start_time": (now - timedelta(hours=4)).isoformat(),
             "end_time":   (now - timedelta(hours=1)).isoformat()},
            # Future job starting at +3h
            {"order_id": "future", "machine_id": 1,
             "start_time": (now + timedelta(hours=3)).isoformat(),
             "end_time":   (now + timedelta(hours=5)).isoformat()},
        ])
        r = find_maintenance_window(db_session, machine_id=1, duration_minutes=60, reference_time=now)
        assert r["slot"] is True
        # Starts at now (not at past end)
        start = datetime.fromisoformat(r["slot_start"])
        assert start == now
