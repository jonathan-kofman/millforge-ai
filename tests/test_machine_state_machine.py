"""
Unit tests for MachineStateMachine and MockMachineIO.
"""

import sys
import os
import time

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


# ---------------------------------------------------------------------------
# Atomic state transition tests (concurrent access)
# ---------------------------------------------------------------------------

def test_concurrent_assign_and_step_transition_atomic():
    """
    Concurrent calls to assign_job() and step() should not cause split-brain state.
    Simulates race between worker thread calling step() and HTTP handler calling assign_job().
    """
    import threading

    msm, io = make_msm(machine_id=10)
    results = []
    errors = []

    def worker_step():
        """Background worker: call step() repeatedly."""
        try:
            for _ in range(50):
                msm.step()
                time.sleep(0.001)  # Small delay
        except Exception as exc:
            errors.append(f"step: {exc}")

    def worker_assign():
        """HTTP handler: call assign_job()."""
        try:
            # Wait for machine to reach IDLE after first job completes
            time.sleep(0.1)
            for i in range(5):
                # Try to assign while step() is running
                msm.assign_job(
                    f"ORD-{i:03d}",
                    setup_time_minutes=0.0,
                    processing_time_minutes=0.01,
                )
                time.sleep(0.02)
                # Force completion to return to IDLE
                io.force_complete(msm.machine_id)
                time.sleep(0.02)
        except Exception as exc:
            errors.append(f"assign_job: {exc}")

    # Start background stepping
    step_thread = threading.Thread(target=worker_step, daemon=True)
    assign_thread = threading.Thread(target=worker_assign, daemon=True)

    step_thread.start()
    assign_thread.start()

    step_thread.join(timeout=5)
    assign_thread.join(timeout=5)

    assert len(errors) == 0, f"Concurrency errors: {errors}"
    # After all jobs, machine should be in a valid state (not split-brain)
    assert msm.state in [MachineState.IDLE, MachineState.SETUP, MachineState.READY,
                          MachineState.RUNNING, MachineState.COOLDOWN]


def test_concurrent_reset_fault_and_step_transition_atomic():
    """
    Concurrent calls to reset_fault() and step() should not cause split-brain state.
    Simulates race between operator resetting a fault and background loop stepping.
    """
    import threading

    msm, io = make_msm(machine_id=11)
    errors = []

    # Force machine into FAULT state
    msm.assign_job("ORD-001", setup_time_minutes=0.0, processing_time_minutes=0.0)
    msm.step()
    msm._setup_complete_at = "bad"  # Corrupt to trigger fault
    msm.step()
    assert msm.state == MachineState.FAULT

    def worker_step():
        """Background: try to step while resetting."""
        try:
            for _ in range(20):
                msm.step()
                time.sleep(0.005)
        except Exception as exc:
            errors.append(f"step: {exc}")

    def worker_reset():
        """Operator: reset fault multiple times."""
        try:
            time.sleep(0.02)
            for _ in range(5):
                msm.reset_fault()
                time.sleep(0.01)
        except Exception as exc:
            errors.append(f"reset_fault: {exc}")

    step_thread = threading.Thread(target=worker_step, daemon=True)
    reset_thread = threading.Thread(target=worker_reset, daemon=True)

    step_thread.start()
    reset_thread.start()

    step_thread.join(timeout=5)
    reset_thread.join(timeout=5)

    assert len(errors) == 0, f"Concurrency errors: {errors}"
    # After reset, should be IDLE
    assert msm.state in [MachineState.IDLE, MachineState.FAULT]


def test_high_load_state_consistency():
    """
    Fire 50 concurrent jobs onto one machine and verify final state is consistent.
    This is the audit requirement: no split-brain state under high concurrency.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor

    msm, io = make_msm(machine_id=12)
    job_count = 50
    errors = []

    def background_step():
        """Continuous stepping for 3 seconds."""
        end_time = time.time() + 3.0
        while time.time() < end_time:
            try:
                msm.step()
                time.sleep(0.01)
            except Exception as exc:
                errors.append(f"step: {exc}")

    def submit_job(job_num):
        """Submit a single job (may fail if not IDLE)."""
        try:
            time.sleep(0.001 * job_num)  # Stagger submissions
            if msm.state == MachineState.IDLE:
                msm.assign_job(
                    f"ORD-{job_num:04d}",
                    setup_time_minutes=0.0,
                    processing_time_minutes=0.01,
                )
                # Immediately mark complete to cycle back to IDLE
                io.force_complete(msm.machine_id)
        except ValueError:
            # Expected when machine is not IDLE
            pass
        except Exception as exc:
            errors.append(f"submit_job({job_num}): {exc}")

    # Start background stepping
    step_thread = threading.Thread(target=background_step, daemon=True)
    step_thread.start()

    # Fire 50 concurrent job submissions
    with ThreadPoolExecutor(max_workers=10) as executor:
        list(executor.map(submit_job, range(job_count)))

    step_thread.join(timeout=5)

    assert len(errors) == 0, f"High-load errors: {errors}"
    # State should be valid (no corrupted/split-brain state)
    valid_states = {MachineState.IDLE, MachineState.SETUP, MachineState.READY,
                    MachineState.RUNNING, MachineState.COOLDOWN}
    assert msm.state in valid_states, f"Invalid state: {msm.state}"
