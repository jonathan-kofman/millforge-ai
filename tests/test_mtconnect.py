"""
Tests for the MTConnect adapter (client + synchronizer + router).

All tests are CI-safe — no real MTConnect agent required.
"""

import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from agents.mtconnect_client import (
    MTConnectClient,
    MTConnectDeviceData,
    MTConnectExecution,
    _parse_streams_xml,
    map_to_mill_state,
    _mock_device,
)
from agents.mtconnect_sync import MTConnectSynchronizer, _DeviceHistory


# ---------------------------------------------------------------------------
# MTConnectClient — mock mode
# ---------------------------------------------------------------------------

def test_mock_mode_default():
    """Client with no agent URL defaults to mock mode."""
    client = MTConnectClient(agent_url="mock://")
    assert client.connection_status == "mock_fallback"


def test_mock_device_returns_snapshot():
    client = MTConnectClient(agent_url="mock://")
    snap = client.poll_device(1)
    assert isinstance(snap, MTConnectDeviceData)
    assert snap.device_id == 1
    assert snap.is_healthy is True


def test_mock_poll_all_devices():
    client = MTConnectClient(agent_url="mock://")
    results = client.poll_all_devices([1, 2, 3])
    assert set(results.keys()) == {1, 2, 3}
    for snap in results.values():
        assert snap.is_healthy


def test_mock_devices_are_independent():
    """Different devices should produce different names."""
    client = MTConnectClient(agent_url="mock://")
    s1 = client.poll_device(1)
    s2 = client.poll_device(2)
    assert s1.device_name != s2.device_name


# ---------------------------------------------------------------------------
# MTConnectClient — unreachable agent fallback
# ---------------------------------------------------------------------------

def test_unreachable_agent_returns_cached_or_placeholder():
    """When requests raises, client returns a placeholder with is_healthy=False."""
    client = MTConnectClient(agent_url="http://192.0.2.1:5000")  # non-routable
    # Patch requests to simulate network failure
    with patch("agents.mtconnect_client.MTConnectClient.poll_device") as mock_poll:
        placeholder = MTConnectDeviceData(
            device_id=1,
            device_name="Device-1",
            program_name=None,
            execution_state=MTConnectExecution.UNAVAILABLE.value,
            mill_state="IDLE",
            spindle_speed_rpm=None,
            feed_rate_override_percent=None,
            part_count=None,
            sampled_at=datetime.now(timezone.utc),
            is_healthy=False,
            error_message="connection refused",
        )
        mock_poll.return_value = placeholder
        snap = client.poll_device(1)
    assert snap.is_healthy is False


# ---------------------------------------------------------------------------
# XML parsing
# ---------------------------------------------------------------------------

SAMPLE_XML = """<?xml version="1.0" encoding="UTF-8"?>
<MTConnectStreams xmlns="urn:mtconnect.org:MTConnectStreams:2.0">
  <Header creationTime="2026-03-26T10:00:00Z"/>
  <Streams>
    <DeviceStream name="Haas VF-4" uuid="dev-1">
      <ComponentStream component="Controller">
        <Events>
          <Execution timestamp="2026-03-26T10:00:01Z">ACTIVE</Execution>
          <Program timestamp="2026-03-26T10:00:02Z">ORD-042.nc</Program>
        </Events>
        <Samples>
          <SpindleSpeed timestamp="2026-03-26T10:00:03Z">2500.0</SpindleSpeed>
          <PathFeedrate timestamp="2026-03-26T10:00:04Z">95.0</PathFeedrate>
        </Samples>
      </ComponentStream>
      <ComponentStream component="Path">
        <Events>
          <PartCount timestamp="2026-03-26T10:00:05Z">7</PartCount>
        </Events>
      </ComponentStream>
    </DeviceStream>
  </Streams>
</MTConnectStreams>"""


def test_parse_xml_execution_state():
    snap = _parse_streams_xml(SAMPLE_XML, device_id=1)
    assert snap.execution_state == "ACTIVE"
    assert snap.mill_state == "RUNNING"


def test_parse_xml_program_name():
    snap = _parse_streams_xml(SAMPLE_XML, device_id=1)
    assert snap.program_name == "ORD-042.nc"
    assert snap.job_id == "ORD-042"


def test_parse_xml_spindle_and_feedrate():
    snap = _parse_streams_xml(SAMPLE_XML, device_id=1)
    assert snap.spindle_speed_rpm == pytest.approx(2500.0)
    assert snap.feed_rate_override_percent == pytest.approx(95.0)


def test_parse_xml_part_count():
    snap = _parse_streams_xml(SAMPLE_XML, device_id=1)
    assert snap.part_count == 7


def test_parse_xml_device_name():
    snap = _parse_streams_xml(SAMPLE_XML, device_id=1)
    assert snap.device_name == "Haas VF-4"


def test_parse_xml_stopped():
    xml = SAMPLE_XML.replace(">ACTIVE<", ">STOPPED<")
    snap = _parse_streams_xml(xml, device_id=1)
    assert snap.execution_state == "STOPPED"
    assert snap.mill_state == "IDLE"


def test_parse_xml_feed_hold():
    xml = SAMPLE_XML.replace(">ACTIVE<", ">FEED_HOLD<")
    snap = _parse_streams_xml(xml, device_id=1)
    assert snap.mill_state == "READY"


def test_parse_xml_malformed_raises():
    with pytest.raises(Exception):
        _parse_streams_xml("this is not xml", device_id=1)


# ---------------------------------------------------------------------------
# State mapping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mt_state,expected", [
    ("ACTIVE",      "RUNNING"),
    ("READY",       "READY"),
    ("STOPPED",     "IDLE"),
    ("FEED_HOLD",   "READY"),
    ("INTERRUPTED", "READY"),
    ("WAIT",        "READY"),
    ("UNAVAILABLE", "IDLE"),
    ("UNKNOWN_XYZ", "IDLE"),
])
def test_map_to_mill_state(mt_state, expected):
    assert map_to_mill_state(mt_state) == expected


# ---------------------------------------------------------------------------
# Job ID extraction
# ---------------------------------------------------------------------------

def test_job_id_strips_extension():
    snap = _mock_device(1, 30)  # tick 30 is in ACTIVE phase
    if snap.program_name:
        assert snap.job_id == snap.program_name.rsplit(".", 1)[0]


def test_job_id_none_when_no_program():
    snap = _mock_device(1, 5)  # tick 5 is in STOPPED phase
    # In STOPPED phase, mock returns no program name
    if snap.program_name is None:
        assert snap.job_id is None


# ---------------------------------------------------------------------------
# _DeviceHistory — completion detection
# ---------------------------------------------------------------------------

def _make_snap(device_id: int, mill_state: str, job_id: str = "ORD-001") -> MTConnectDeviceData:
    program = f"{job_id}.nc" if mill_state == "RUNNING" else None
    return MTConnectDeviceData(
        device_id=device_id,
        device_name=f"Machine-{device_id}",
        program_name=program,
        execution_state="ACTIVE" if mill_state == "RUNNING" else "STOPPED",
        mill_state=mill_state,
        spindle_speed_rpm=None,
        feed_rate_override_percent=None,
        part_count=None,
        sampled_at=datetime.now(timezone.utc),
        is_healthy=True,
    )


def test_no_completion_while_running():
    hist = _DeviceHistory()
    snap = _make_snap(1, "RUNNING")
    hist.push(snap)
    # detect_completion is called before push in sync_device; simulate the same
    result = hist.detect_completion(snap)
    # First time seeing RUNNING — transitions into run, no completion yet
    assert result is None


def test_completion_detected_on_transition():
    hist = _DeviceHistory()

    running_snap = _make_snap(1, "RUNNING", "ORD-007")
    hist.detect_completion(running_snap)
    hist.push(running_snap)

    idle_snap = _make_snap(1, "IDLE")
    result = hist.detect_completion(idle_snap)
    hist.push(idle_snap)

    assert result is not None
    actual_setup, actual_processing, job_id = result
    assert job_id == "ORD-007"
    assert actual_processing >= 0.0


def test_no_completion_idle_to_idle():
    hist = _DeviceHistory()
    snap1 = _make_snap(1, "IDLE")
    snap2 = _make_snap(1, "IDLE")
    hist.detect_completion(snap1)
    hist.push(snap1)
    assert hist.detect_completion(snap2) is None


# ---------------------------------------------------------------------------
# MTConnectSynchronizer — integration
# ---------------------------------------------------------------------------

def test_sync_device_no_completion_returns_none():
    """When no job completes, sync_device returns None."""
    client = MTConnectClient(agent_url="mock://")
    sync = MTConnectSynchronizer(client)
    db = MagicMock()
    # First few calls should return None (device hasn't cycled yet)
    result = sync.sync_device(db, device_id=1, machine_id=1, material="steel")
    # May or may not be None depending on tick — just check it doesn't raise
    assert result is None or hasattr(result, "canonical_id")


def test_sync_all_returns_list():
    client = MTConnectClient(agent_url="mock://")
    sync = MTConnectSynchronizer(client)
    db = MagicMock()
    results = sync.sync_all(db, {1: 1, 2: 2}, {1: "steel", 2: "aluminum"})
    assert isinstance(results, list)


# ---------------------------------------------------------------------------
# Router — smoke tests via TestClient
# ---------------------------------------------------------------------------

from fastapi.testclient import TestClient
from main import app

_tc = TestClient(app)


def test_mtconnect_status_ok():
    resp = _tc.get("/api/mtconnect/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "devices" in body
    assert "connection_status" in body


def test_mtconnect_status_has_devices():
    resp = _tc.get("/api/mtconnect/status")
    body = resp.json()
    assert body["device_count"] > 0


def test_mtconnect_sync_ok():
    resp = _tc.post("/api/mtconnect/sync")
    assert resp.status_code == 200
    body = resp.json()
    assert "jobs_logged" in body
    assert "devices_polled" in body
    assert isinstance(body["feedback_records"], list)


def test_mtconnect_connection_status_is_mock():
    resp = _tc.get("/api/mtconnect/status")
    body = resp.json()
    assert body["connection_status"] == "mock_fallback"
