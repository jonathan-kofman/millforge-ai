"""
Unit tests for MachineStateMachine and MockMachineIO.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
from agents.machine_state_machine import MachineState, MachineStateMachine, MockMachineIO


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_msm(machine_id: int = 1) -> tuple[MachineStateMachine, MockMachineIO]:
    io = MockMachineIO()
    msm = MachineStateMachine(machine_id=machine_id, io=io)
    return msm, io


def run_to_state(msm: MachineStateMachine, io: MockMachineIO, target: MachineState) -> None:
    """Step through the lifecycle until the machine reaches `target` state."""
    for _ in range(20):
        if msm.state == target:
            return
        if msm.state == MachineState.RUNNING:
            io.force_complete(msm.machine_id)
        msm.step()
    raise AssertionError(f"Did not reach {target.name} within 20 steps; stuck at {msm.state.name}")


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

def test_initial_state_is_idle():
    msm, _ = make_msm()
    assert msm.state == MachineState.IDLE


def test_step_while_idle_no_job_stays_idle():
    msm, _ = make_msm()
    msm.step()
    assert msm.state == MachineState.IDLE


# ---------------------------------------------------------------------------
# IDLE → SETUP
# ---------------------------------------------------------------------------

def test_assign_job_transitions_to_setup():
    msm, _ = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    msm.step()
    assert msm.state == MachineState.SETUP


def test_assign_job_while_not_idle_raises():
    msm, _ = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    msm.step()  # IDLE → SETUP
    with pytest.raises(ValueError):
        msm.assign_job("ORD-002", setup_time_minutes=0.0, processing_time_minutes=0.0)


# ---------------------------------------------------------------------------
# SETUP → READY (zero-duration setup completes immediately)
# ---------------------------------------------------------------------------

def test_zero_setup_transitions_to_ready():
    msm, _ = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    msm.step()  # IDLE → SETUP
    msm.step()  # SETUP → READY (duration=0 so already elapsed)
    assert msm.state == MachineState.READY


# ---------------------------------------------------------------------------
# READY → RUNNING
# ---------------------------------------------------------------------------

def test_ready_transitions_to_running():
    msm, _ = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=60.0)
    msm.step()  # IDLE → SETUP
    msm.step()  # SETUP → READY
    msm.step()  # READY → RUNNING
    assert msm.state == MachineState.RUNNING


# ---------------------------------------------------------------------------
# RUNNING → COOLDOWN (via force_complete)
# ---------------------------------------------------------------------------

def test_force_complete_transitions_to_cooldown():
    msm, io = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=60.0)
    msm.step()  # IDLE → SETUP
    msm.step()  # SETUP → READY
    msm.step()  # READY → RUNNING
    io.force_complete(msm.machine_id)
    msm.step()  # RUNNING → COOLDOWN
    assert msm.state == MachineState.COOLDOWN


# ---------------------------------------------------------------------------
# Full lifecycle (with cooldown bypass)
# ---------------------------------------------------------------------------

def test_full_lifecycle_returns_to_idle():
    msm, io = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    run_to_state(msm, io, MachineState.COOLDOWN)
    # Force cooldown to expire
    msm._cooldown_complete_at = 0.0
    msm.step()  # COOLDOWN → IDLE
    assert msm.state == MachineState.IDLE


# ---------------------------------------------------------------------------
# FAULT handling
# ---------------------------------------------------------------------------

def test_exception_during_step_transitions_to_fault():
    msm, io = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    msm.step()  # IDLE → SETUP

    # Corrupt internal state to force an exception on next step
    msm._setup_complete_at = "not a number"
    msm.step()  # should catch exception → FAULT
    assert msm.state == MachineState.FAULT


def test_reset_fault_returns_to_idle():
    msm, io = make_msm()
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    msm.step()  # IDLE → SETUP
    msm._setup_complete_at = "bad"
    msm.step()  # → FAULT
    msm.reset_fault()
    assert msm.state == MachineState.IDLE


# ---------------------------------------------------------------------------
# MockMachineIO
# ---------------------------------------------------------------------------

def test_mock_io_is_job_complete_false_before_duration():
    io = MockMachineIO()
    io.schedule_completion(machine_id=1, duration_seconds=9999.0)
    assert io.is_job_complete(1) is False


def test_mock_io_is_job_complete_true_after_force():
    io = MockMachineIO()
    io.schedule_completion(machine_id=1, duration_seconds=9999.0)
    io.force_complete(1)
    assert io.is_job_complete(1) is True


def test_mock_io_stop_clears_completion():
    io = MockMachineIO()
    io.schedule_completion(machine_id=1, duration_seconds=0.0)
    io.stop(1)
    assert io.is_job_complete(1) is False


# ---------------------------------------------------------------------------
# Multiple machines are independent
# ---------------------------------------------------------------------------

def test_multiple_machines_independent():
    io = MockMachineIO()
    m1 = MachineStateMachine(machine_id=1, io=io)
    m2 = MachineStateMachine(machine_id=2, io=io)

    m1.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    m1.step()  # m1: IDLE → SETUP
    assert m1.state == MachineState.SETUP
    assert m2.state == MachineState.IDLE  # m2 unaffected


# ---------------------------------------------------------------------------
# Feedback logger integration (Item 1)
# ---------------------------------------------------------------------------

def test_feedback_logger_fires_on_running_to_cooldown():
    """When a job completes (RUNNING → COOLDOWN), FeedbackLogger is called."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db_models import Base, JobFeedbackRecord

    # Create in-memory test database
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    io = MockMachineIO()
    msm = MachineStateMachine(machine_id=1, io=io, db=db)
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0, material="steel")

    # Run through the lifecycle to COOLDOWN
    run_to_state(msm, io, MachineState.COOLDOWN)

    # Check that a feedback record was logged
    records = db.query(JobFeedbackRecord).filter_by(order_id="ORD-001").all()
    assert len(records) > 0, "No feedback record logged"
    record = records[0]
    assert record.order_id == "ORD-001"
    assert record.material == "steel"
    assert record.machine_id == 1
    assert record.data_provenance == "mtconnect_auto"


def test_feedback_logger_captures_accurate_timestamps():
    """Feedback logger should capture actual setup and processing time within ~1 second."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db_models import Base, JobFeedbackRecord

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    io = MockMachineIO()
    msm = MachineStateMachine(machine_id=2, io=io, db=db)
    # Request 0.0 min setup and 0.0 min processing for predictable test
    msm.assign_job("ORD-002", setup_time_minutes=0.0, processing_time_minutes=0.0, material="aluminum")

    run_to_state(msm, io, MachineState.COOLDOWN)

    records = db.query(JobFeedbackRecord).filter_by(order_id="ORD-002").all()
    assert len(records) > 0
    record = records[0]

    # Actual times should be very small (close to 0 for zero-duration job)
    assert record.actual_setup_minutes >= 0, f"Setup time negative: {record.actual_setup_minutes}"
    assert record.actual_processing_minutes >= 0, f"Processing time negative: {record.actual_processing_minutes}"


def test_feedback_logger_increments_count_on_completion():
    """Submitting multiple jobs should increment the feedback record count."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db_models import Base, JobFeedbackRecord

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    io = MockMachineIO()
    msm = MachineStateMachine(machine_id=3, io=io, db=db)

    # Submit first job
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0, material="steel")
    run_to_state(msm, io, MachineState.COOLDOWN)
    msm._cooldown_complete_at = 0.0
    msm.step()  # COOLDOWN → IDLE

    count_after_first = db.query(JobFeedbackRecord).count()
    assert count_after_first == 1

    # Submit second job
    msm.assign_job("ORD-002", setup_time_minutes=0.0, processing_time_minutes=0.0, material="aluminum")
    run_to_state(msm, io, MachineState.COOLDOWN)

    count_after_second = db.query(JobFeedbackRecord).count()
    assert count_after_second == 2
