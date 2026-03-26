"""
MTConnect client — polls a factory-floor MTConnect agent and returns device snapshots.

MTConnect is the ANSI/MTC1-1-2018 protocol for CNC machine data. A real MTConnect
agent runs on the shop floor and exposes an HTTP XML feed. This client polls that
feed, parses the XML, and converts execution state to MillForge MachineState values.

Graceful degradation:
  - MTCONNECT_AGENT_URL unset or set to "mock://" → mock mode (synthetic rotating states)
  - Agent unreachable → last-known cache returned with is_healthy=False
  - Partial connectivity → healthy devices returned normally, unreachable ones flagged

Environment variables:
  MTCONNECT_AGENT_URL              e.g. http://192.168.1.100:5000  (default: mock://)
  MTCONNECT_POLL_TIMEOUT_SECONDS   HTTP timeout per request         (default: 5.0)
  MTCONNECT_DEVICE_IDS             comma-separated machine IDs      (default: 1,2,3)
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# MTConnect XML namespace
# ---------------------------------------------------------------------------
_MT_NS_PREFIX = "urn:mtconnect.org:MTConnectStreams:"
# We match on any version suffix, so we strip the version at parse time.


# ---------------------------------------------------------------------------
# Execution state mapping
# ---------------------------------------------------------------------------

class MTConnectExecution(str, Enum):
    ACTIVE     = "ACTIVE"      # job is executing  → RUNNING
    READY      = "READY"       # loaded, waiting   → READY
    STOPPED    = "STOPPED"     # not running       → IDLE
    FEED_HOLD  = "FEED_HOLD"   # paused mid-run    → READY (will resume)
    INTERRUPTED = "INTERRUPTED" # program paused   → READY
    WAIT       = "WAIT"        # waiting for input → READY
    UNAVAILABLE = "UNAVAILABLE" # data not available → last known


_EXEC_TO_MILL_STATE: Dict[str, str] = {
    MTConnectExecution.ACTIVE:      "RUNNING",
    MTConnectExecution.READY:       "READY",
    MTConnectExecution.STOPPED:     "IDLE",
    MTConnectExecution.FEED_HOLD:   "READY",
    MTConnectExecution.INTERRUPTED: "READY",
    MTConnectExecution.WAIT:        "READY",
    MTConnectExecution.UNAVAILABLE: "IDLE",
}


def map_to_mill_state(mt_execution: str) -> str:
    """Map MTConnect execution string → MillForge MachineState name."""
    return _EXEC_TO_MILL_STATE.get(mt_execution.upper(), "IDLE")


# ---------------------------------------------------------------------------
# Device snapshot dataclass
# ---------------------------------------------------------------------------

@dataclass
class MTConnectDeviceData:
    """Immutable snapshot of a single device's current state."""

    device_id: int
    device_name: str
    program_name: Optional[str]          # e.g. "ORD-001.nc" → job_id = "ORD-001"
    execution_state: str                 # MTConnectExecution value
    mill_state: str                      # MillForge MachineState name
    spindle_speed_rpm: Optional[float]
    feed_rate_override_percent: Optional[float]
    part_count: Optional[int]
    sampled_at: datetime
    is_healthy: bool                     # False when agent was unreachable
    error_message: Optional[str] = None

    @property
    def job_id(self) -> Optional[str]:
        """Extract job ID from program filename (e.g. 'ORD-001.nc' → 'ORD-001')."""
        if not self.program_name:
            return None
        # Strip extension and whitespace
        name = self.program_name.rsplit(".", 1)[0].strip()
        return name if name else None


def _mock_device(device_id: int, tick: int) -> MTConnectDeviceData:
    """
    Generate a synthetic device snapshot for mock/CI mode.

    Cycles through IDLE → ACTIVE → STOPPED every ~60 ticks so the synchronizer
    can detect a completion event during integration tests.
    """
    phase = tick % 60
    if phase < 10:
        exec_state = MTConnectExecution.STOPPED
    elif phase < 50:
        exec_state = MTConnectExecution.ACTIVE
    else:
        exec_state = MTConnectExecution.STOPPED

    return MTConnectDeviceData(
        device_id=device_id,
        device_name=f"Mock-Machine-{device_id}",
        program_name=f"ORD-{device_id:03d}.nc" if exec_state == MTConnectExecution.ACTIVE else None,
        execution_state=exec_state.value,
        mill_state=map_to_mill_state(exec_state.value),
        spindle_speed_rpm=2500.0 if exec_state == MTConnectExecution.ACTIVE else None,
        feed_rate_override_percent=100.0,
        part_count=phase if exec_state == MTConnectExecution.ACTIVE else 0,
        sampled_at=datetime.now(timezone.utc),
        is_healthy=True,
    )


# ---------------------------------------------------------------------------
# XML parser helpers
# ---------------------------------------------------------------------------

def _strip_ns(tag: str) -> str:
    """Remove XML namespace prefix from a tag string."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _parse_streams_xml(xml_text: str, device_id: int) -> MTConnectDeviceData:
    """
    Parse MTConnect MTConnectStreams XML and extract device data.

    Returns an MTConnectDeviceData. Raises ValueError on parse failure.

    Example XML snippet::

        <MTConnectStreams xmlns="urn:mtconnect.org:MTConnectStreams:2.0">
          <Streams>
            <DeviceStream name="Haas VF-4" uuid="dev-1">
              <ComponentStream component="Controller">
                <Events>
                  <Execution timestamp="2026-01-01T00:00:00Z">ACTIVE</Execution>
                  <Program timestamp="2026-01-01T00:00:01Z">ORD-001.nc</Program>
                </Events>
                <Samples>
                  <SpindleSpeed timestamp="2026-01-01T00:00:02Z">2500</SpindleSpeed>
                  <PathFeedrate timestamp="2026-01-01T00:00:03Z">95</PathFeedrate>
                </Samples>
              </ComponentStream>
              <ComponentStream component="Path">
                <Events>
                  <PartCount timestamp="2026-01-01T00:00:04Z">42</PartCount>
                </Events>
              </ComponentStream>
            </DeviceStream>
          </Streams>
        </MTConnectStreams>
    """
    root = ET.fromstring(xml_text)
    device_name = f"Device-{device_id}"
    execution_state = MTConnectExecution.UNAVAILABLE.value
    program_name: Optional[str] = None
    spindle_speed: Optional[float] = None
    feed_rate_override: Optional[float] = None
    part_count: Optional[int] = None

    # Walk entire tree — namespace-agnostic
    for elem in root.iter():
        tag = _strip_ns(elem.tag)
        text = (elem.text or "").strip()

        if tag == "DeviceStream":
            device_name = elem.attrib.get("name", device_name)

        elif tag in ("Execution", "ExecutionState"):
            if text and text != "UNAVAILABLE":
                execution_state = text.upper()

        elif tag == "Program":
            if text and text not in ("UNAVAILABLE", ""):
                program_name = text

        elif tag in ("SpindleSpeed", "SpindleRotationalVelocity"):
            try:
                spindle_speed = float(text)
            except (ValueError, TypeError):
                pass

        elif tag in ("PathFeedrate", "FeedRateOverride", "FeedOverride"):
            try:
                feed_rate_override = float(text)
            except (ValueError, TypeError):
                pass

        elif tag == "PartCount":
            try:
                part_count = int(float(text))
            except (ValueError, TypeError):
                pass

    mill_state = map_to_mill_state(execution_state)

    return MTConnectDeviceData(
        device_id=device_id,
        device_name=device_name,
        program_name=program_name,
        execution_state=execution_state,
        mill_state=mill_state,
        spindle_speed_rpm=spindle_speed,
        feed_rate_override_percent=feed_rate_override,
        part_count=part_count,
        sampled_at=datetime.now(timezone.utc),
        is_healthy=True,
    )


# ---------------------------------------------------------------------------
# MTConnect HTTP client
# ---------------------------------------------------------------------------

class MTConnectClient:
    """
    Non-blocking MTConnect HTTP poller with caching and graceful fallback.

    Usage::

        client = MTConnectClient()
        data = client.poll_device(1)
        print(data.execution_state, data.job_id)

    Mock mode is activated when MTCONNECT_AGENT_URL is unset or set to "mock://".
    """

    def __init__(
        self,
        agent_url: Optional[str] = None,
        poll_timeout_seconds: float = 5.0,
    ) -> None:
        raw_url = agent_url or os.getenv("MTCONNECT_AGENT_URL", "mock://")
        self._mock_mode = raw_url.startswith("mock://") or not raw_url
        self._agent_url = raw_url if not self._mock_mode else ""
        self._timeout = poll_timeout_seconds
        self._cache: Dict[int, MTConnectDeviceData] = {}
        self._lock = threading.Lock()
        self._tick = 0  # monotonic counter for mock rotation

        if self._mock_mode:
            logger.info(
                "MTConnect client starting in MOCK mode "
                "(set MTCONNECT_AGENT_URL to a real agent to enable live data)"
            )
        else:
            logger.info("MTConnect client configured: agent_url=%s", self._agent_url)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def connection_status(self) -> str:
        if self._mock_mode:
            return "mock_fallback"
        with self._lock:
            cached = list(self._cache.values())
        if not cached:
            return "not_polled_yet"
        if all(d.is_healthy for d in cached):
            return "connected"
        if any(d.is_healthy for d in cached):
            return "partial"
        return "unreachable"

    def poll_device(self, device_id: int) -> MTConnectDeviceData:
        """
        Fetch the current state of a single device.

        Returns cached snapshot with is_healthy=False if the agent is unreachable.
        Never raises.
        """
        if self._mock_mode:
            with self._lock:
                self._tick += 1
                tick = self._tick
            return _mock_device(device_id, tick + device_id * 7)

        try:
            import requests  # optional dep — only needed for live mode

            url = f"{self._agent_url.rstrip('/')}/current?device={device_id}"
            resp = requests.get(url, timeout=self._timeout)
            resp.raise_for_status()
            data = _parse_streams_xml(resp.text, device_id)
            with self._lock:
                self._cache[device_id] = data
            return data

        except Exception as exc:
            logger.warning(
                "MTConnect poll failed for device %d: %s — returning cached/fallback",
                device_id, exc,
            )
            with self._lock:
                cached = self._cache.get(device_id)
            if cached is not None:
                # Return stale data flagged as unhealthy
                from dataclasses import replace
                return replace(cached, is_healthy=False, error_message=str(exc))
            # No cache yet — return an IDLE placeholder
            return MTConnectDeviceData(
                device_id=device_id,
                device_name=f"Device-{device_id}",
                program_name=None,
                execution_state=MTConnectExecution.UNAVAILABLE.value,
                mill_state="IDLE",
                spindle_speed_rpm=None,
                feed_rate_override_percent=None,
                part_count=None,
                sampled_at=datetime.now(timezone.utc),
                is_healthy=False,
                error_message=str(exc),
            )

    def poll_all_devices(self, device_ids: List[int]) -> Dict[int, MTConnectDeviceData]:
        """Poll every device_id. Failures are isolated — one unhealthy device won't block others."""
        return {did: self.poll_device(did) for did in device_ids}

    def default_device_ids(self) -> List[int]:
        """Device IDs from MTCONNECT_DEVICE_IDS env var, defaulting to [1, 2, 3]."""
        raw = os.getenv("MTCONNECT_DEVICE_IDS", "1,2,3")
        try:
            return [int(x.strip()) for x in raw.split(",") if x.strip()]
        except ValueError:
            return [1, 2, 3]
