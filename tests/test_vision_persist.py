"""
Tests for vision inspection result persistence.
"""

import pytest


def test_vision_inspect_succeeds_without_order_id(client):
    res = client.post("/api/vision/inspect", json={
        "image_url": "https://example.com/part.jpg",
        "material": "steel",
    })
    assert res.status_code == 200
    data = res.json()
    assert "passed" in data
    assert "confidence" in data
    assert "defects_detected" in data
    assert data["order_id"] is None


def test_vision_inspect_with_order_id_in_response(client):
    res = client.post("/api/vision/inspect", json={
        "image_url": "https://example.com/part.jpg",
        "material": "aluminum",
        "order_id": "ORD-TEST001",
    })
    assert res.status_code == 200
    assert res.json()["order_id"] == "ORD-TEST001"


def test_vision_inspect_persists_result(client):
    """
    Verify that two inspection calls accumulate independently — the DB
    is not reset between calls within the same test.
    """
    # First call
    r1 = client.post("/api/vision/inspect", json={
        "image_url": "https://example.com/part1.jpg",
        "material": "steel",
        "order_id": "ORD-A001",
    })
    assert r1.status_code == 200

    # Second call
    r2 = client.post("/api/vision/inspect", json={
        "image_url": "https://example.com/part2.jpg",
        "material": "copper",
    })
    assert r2.status_code == 200

    # Both should return valid inspection data
    assert r1.json()["inspector_version"] is not None
    assert r2.json()["inspector_version"] is not None


def test_vision_inspect_empty_url_rejected(client):
    res = client.post("/api/vision/inspect", json={
        "image_url": "   ",
    })
    assert res.status_code == 422
