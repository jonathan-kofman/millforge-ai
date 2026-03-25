"""
Tests for CAD parser agent and POST /api/orders/from-cad endpoint.

STL binary format (80-byte header + 4-byte triangle count + n × 50-byte triangles):
  header:         80 bytes (arbitrary)
  num_triangles:  uint32 LE
  per triangle:   12-byte normal + 3 × 12-byte vertices + 2-byte attr = 50 bytes
"""

import io
import struct
import sys
import os
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))


def _make_stl_bytes(triangles: list[tuple]) -> bytes:
    """
    Build a minimal binary STL from a list of (normal, v0, v1, v2) tuples.
    Each vertex/normal is a 3-tuple of floats.
    """
    header = b"\x00" * 80
    num = struct.pack("<I", len(triangles))
    body = b""
    for normal, v0, v1, v2 in triangles:
        body += struct.pack("<fff", *normal)
        body += struct.pack("<fff", *v0)
        body += struct.pack("<fff", *v1)
        body += struct.pack("<fff", *v2)
        body += struct.pack("<H", 0)   # attr byte count
    return header + num + body


def _unit_cube_stl() -> bytes:
    """12 triangles forming a 10×20×30mm box."""
    # Minimal box: just two triangles per face would suffice; use 12 for completeness
    tris = [
        # bottom (z=0)
        ((0,0,-1), (0,0,0),  (10,0,0),  (10,20,0)),
        ((0,0,-1), (0,0,0),  (10,20,0), (0,20,0)),
        # top (z=30)
        ((0,0,1),  (0,0,30), (10,20,30),(10,0,30)),
        ((0,0,1),  (0,0,30), (0,20,30), (10,20,30)),
        # front (y=0)
        ((0,-1,0), (0,0,0),  (10,0,30), (10,0,0)),
        ((0,-1,0), (0,0,0),  (0,0,30),  (10,0,30)),
        # back (y=20)
        ((0,1,0),  (0,20,0), (10,20,0), (10,20,30)),
        ((0,1,0),  (0,20,0), (10,20,30),(0,20,30)),
        # left (x=0)
        ((-1,0,0), (0,0,0),  (0,20,0),  (0,20,30)),
        ((-1,0,0), (0,0,0),  (0,20,30), (0,0,30)),
        # right (x=10)
        ((1,0,0),  (10,0,0), (10,0,30), (10,20,30)),
        ((1,0,0),  (10,0,0), (10,20,30),(10,20,0)),
    ]
    return _make_stl_bytes(tris)


# ---------------------------------------------------------------------------
# Test 1 — agent: extract_from_stl returns correct dimensions and metadata
# ---------------------------------------------------------------------------

def test_extract_from_stl_dimensions():
    pytest.importorskip("stl", reason="numpy-stl not installed")
    from agents.cad_parser import extract_from_stl

    stl_bytes = _unit_cube_stl()
    result = extract_from_stl(stl_bytes)

    assert result["source"] == "stl_upload"
    assert result["triangle_count"] == 12
    assert "x" in result["dimensions"] and "mm" in result["dimensions"]

    # Bounding box should be ~10×20×30mm
    parts = result["dimensions"].replace("mm", "").split("x")
    x, y, z = float(parts[0]), float(parts[1]), float(parts[2])
    assert abs(x - 10.0) < 0.5
    assert abs(y - 20.0) < 0.5
    assert abs(z - 30.0) < 0.5

    # Volume proxy: 10×20×30 / 1000 = 6.0 cm³
    assert abs(result["estimated_volume_cm3"] - 6.0) < 0.5

    # 12 triangles → complexity = max(1, 12//1000) = 1
    assert result["complexity"] == 1


# ---------------------------------------------------------------------------
# Test 2 — complexity scales with triangle count
# ---------------------------------------------------------------------------

def test_extract_from_stl_complexity_scaling():
    pytest.importorskip("stl", reason="numpy-stl not installed")
    from agents.cad_parser import extract_from_stl

    # Build a mesh with exactly 5000 triangles (all degenerate, but parseable)
    tris = [((0,0,1), (0,0,0), (1,0,0), (0,1,0))] * 5000
    stl_bytes = _make_stl_bytes(tris)
    result = extract_from_stl(stl_bytes)
    assert result["triangle_count"] == 5000
    assert result["complexity"] == 5   # 5000 // 1000 = 5

    # 12000 triangles → clamped at 10
    tris_big = [((0,0,1), (0,0,0), (1,0,0), (0,1,0))] * 12000
    stl_bytes_big = _make_stl_bytes(tris_big)
    result_big = extract_from_stl(stl_bytes_big)
    assert result_big["complexity"] == 10


# ---------------------------------------------------------------------------
# Test 3 — HTTP endpoint returns 400 for non-STL and 422 for corrupt file
# ---------------------------------------------------------------------------

def test_from_cad_endpoint_validation():
    pytest.importorskip("stl", reason="numpy-stl not installed")
    from main import app
    client = TestClient(app)

    # Wrong extension → 400
    resp = client.post(
        "/api/orders/from-cad",
        files={"file": ("model.obj", b"v 0 0 0\n", "application/octet-stream")},
    )
    assert resp.status_code == 400
    assert "stl" in resp.json()["detail"].lower()

    # Empty file → 400
    resp_empty = client.post(
        "/api/orders/from-cad",
        files={"file": ("empty.stl", b"", "application/octet-stream")},
    )
    assert resp_empty.status_code == 400

    # Valid STL → 200 with expected fields
    stl_bytes = _unit_cube_stl()
    resp_ok = client.post(
        "/api/orders/from-cad",
        files={"file": ("box.stl", stl_bytes, "application/octet-stream")},
    )
    assert resp_ok.status_code == 200
    body = resp_ok.json()
    assert body["source"] == "stl_upload"
    assert body["triangle_count"] == 12
    assert "mm" in body["dimensions"]
    assert body["complexity"] >= 1
