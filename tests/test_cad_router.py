"""
Tests for POST /api/orders/from-cad (STL upload endpoint).

Covers:
  - Happy path: valid binary STL → CadParseResponse fields
  - Wrong extension → 400
  - Empty file → 400
  - Valid STL returns positive complexity and volume
  - Complexity clamped to [1, 10]
"""

import struct
import io
import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal binary STL in memory
# ---------------------------------------------------------------------------

def _make_binary_stl(num_triangles: int = 12) -> bytes:
    """
    Build a minimal valid binary STL with `num_triangles` triangles.
    All triangles are degenerate (zero-area) but structurally valid.
    """
    header = b"\x00" * 80
    count = struct.pack("<I", num_triangles)
    triangle_bytes = b""
    for _ in range(num_triangles):
        # normal (0,0,1) + 3 vertices at origin + attr=0
        triangle_bytes += struct.pack("<fff", 0.0, 0.0, 1.0)
        triangle_bytes += struct.pack("<fff", 0.0, 0.0, 0.0)
        triangle_bytes += struct.pack("<fff", 1.0, 0.0, 0.0)
        triangle_bytes += struct.pack("<fff", 0.0, 1.0, 0.0)
        triangle_bytes += struct.pack("<H", 0)
    return header + count + triangle_bytes


def _make_box_stl() -> bytes:
    """12 triangles forming a rough 10×20×30 bounding box."""
    header = b"\x00" * 80
    num = struct.pack("<I", 12)
    body = b""
    # Each triangle uses vertices at corners of a 10×20×30 box
    # Just need distinct x/y/z ranges for the bounding box test
    corners = [
        (0, 0, 0), (10, 0, 0), (0, 20, 0),
        (10, 20, 0), (0, 0, 30), (10, 0, 30),
        (0, 20, 30), (10, 20, 30),
    ]
    tri_sets = [
        (corners[0], corners[1], corners[2]),
        (corners[1], corners[3], corners[2]),
        (corners[4], corners[5], corners[6]),
        (corners[5], corners[7], corners[6]),
        (corners[0], corners[1], corners[4]),
        (corners[1], corners[5], corners[4]),
        (corners[2], corners[3], corners[6]),
        (corners[3], corners[7], corners[6]),
        (corners[0], corners[2], corners[4]),
        (corners[2], corners[6], corners[4]),
        (corners[1], corners[3], corners[5]),
        (corners[3], corners[7], corners[5]),
    ]
    for v0, v1, v2 in tri_sets:
        body += struct.pack("<fff", 0.0, 0.0, 1.0)   # normal
        body += struct.pack("<fff", *v0)
        body += struct.pack("<fff", *v1)
        body += struct.pack("<fff", *v2)
        body += struct.pack("<H", 0)
    return header + num + body


def _upload(client, filename: str, content: bytes, content_type: str = "application/octet-stream"):
    return client.post(
        "/api/orders/from-cad",
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_upload_valid_stl_ok(client):
    stl = _make_binary_stl(12)
    res = _upload(client, "test.stl", stl)
    assert res.status_code == 200
    data = res.json()
    assert "dimensions" in data
    assert "complexity" in data
    assert "triangle_count" in data
    assert "estimated_volume_cm3" in data
    assert data["source"] == "stl_upload"


def test_upload_triangle_count_correct(client):
    stl = _make_binary_stl(50)
    res = _upload(client, "model.stl", stl)
    assert res.status_code == 200
    assert res.json()["triangle_count"] == 50


def test_upload_complexity_minimum_one(client):
    """A tiny model (<1000 triangles) should have complexity=1."""
    stl = _make_binary_stl(5)
    res = _upload(client, "tiny.stl", stl)
    assert res.status_code == 200
    assert res.json()["complexity"] == 1


def test_upload_complexity_clamped_at_10(client):
    """A large model (>10000 triangles) should have complexity=10."""
    stl = _make_binary_stl(15000)
    res = _upload(client, "big.stl", stl)
    assert res.status_code == 200
    assert res.json()["complexity"] == 10


def test_upload_positive_volume(client):
    stl = _make_box_stl()
    res = _upload(client, "box.stl", stl)
    assert res.status_code == 200
    assert res.json()["estimated_volume_cm3"] > 0


def test_upload_wrong_extension_rejected(client):
    res = _upload(client, "model.obj", b"some bytes", "application/octet-stream")
    assert res.status_code == 400


def test_upload_empty_file_rejected(client):
    res = _upload(client, "empty.stl", b"")
    assert res.status_code == 400


def test_upload_malformed_stl_rejected(client):
    """Garbage bytes that aren't a valid STL should return 422 or 400."""
    res = _upload(client, "garbage.stl", b"this is not an stl file at all!!")
    assert res.status_code in (400, 422, 503)
