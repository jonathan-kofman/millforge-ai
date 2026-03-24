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
