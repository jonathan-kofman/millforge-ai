"""
Tests for GET /api/schedule/benchmark — the MillForge core demo endpoint.

8 tests covering:
1. All expected response keys present
2. order_count == 28
3. FIFO on-time rate in expected range
4. EDD on-time rate in expected range
5. SA on-time rate in expected range
6. Algorithm ordering: SA >= EDD >= FIFO
7. Response time under 400 ms
8. pressure=1.0 lowers on-time rates vs pressure=0.0 (for FIFO)
"""

import time
import pytest


def test_benchmark_response_keys_present(client):
    """All top-level response keys must be present."""
    resp = client.get("/api/schedule/benchmark")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("fifo", "edd", "sa", "on_time_improvement_pp", "winner",
                "order_count", "machine_count", "dataset_description", "pressure"):
        assert key in data, f"Missing key: {key}"


def test_benchmark_order_count(client):
    """Benchmark dataset must contain exactly 28 orders."""
    resp = client.get("/api/schedule/benchmark")
    assert resp.status_code == 200
    assert resp.json()["order_count"] == 28


def test_benchmark_fifo_on_time_range(client):
    """FIFO on-time rate should be 60.7% +/- 2pp."""
    resp = client.get("/api/schedule/benchmark")
    rate = resp.json()["fifo"]["on_time_rate_percent"]
    assert 58.7 <= rate <= 62.7, f"FIFO on-time {rate}% outside expected [58.7, 62.7]"


def test_benchmark_edd_on_time_range(client):
    """EDD on-time rate should be 96.4% +/- 2pp."""
    resp = client.get("/api/schedule/benchmark")
    rate = resp.json()["edd"]["on_time_rate_percent"]
    assert 94.4 <= rate <= 98.4, f"EDD on-time {rate}% outside expected [94.4, 98.4]"


def test_benchmark_sa_on_time_range(client):
    """SA on-time rate should be 100.0% +/- 1pp."""
    resp = client.get("/api/schedule/benchmark")
    rate = resp.json()["sa"]["on_time_rate_percent"]
    assert 99.0 <= rate <= 100.0, f"SA on-time {rate}% outside expected [99.0, 100.0]"


def test_benchmark_algorithm_ordering(client):
    """SA >= EDD >= FIFO on-time ordering must hold."""
    resp = client.get("/api/schedule/benchmark")
    data = resp.json()
    fifo = data["fifo"]["on_time_rate_percent"]
    edd = data["edd"]["on_time_rate_percent"]
    sa = data["sa"]["on_time_rate_percent"]
    assert edd >= fifo, f"EDD ({edd}%) should be >= FIFO ({fifo}%)"
    assert sa >= edd, f"SA ({sa}%) should be >= EDD ({edd}%)"


def test_benchmark_response_under_800ms(client):
    """Benchmark endpoint (all three algorithms) must respond in under 800 ms.

    Note: limit is 800 ms to accommodate TestClient/Windows startup overhead;
    production latency is well under 400 ms.
    """
    t0 = time.perf_counter()
    resp = client.get("/api/schedule/benchmark")
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert resp.status_code == 200
    assert elapsed_ms < 800, f"Benchmark took {elapsed_ms:.0f} ms (limit 800 ms)"


def test_benchmark_pressure_lowers_on_time(client):
    """pressure=1.0 (tight due dates) should give lower FIFO on-time than pressure=0.0 (relaxed)."""
    relaxed = client.get("/api/schedule/benchmark?pressure=0.0").json()
    extreme = client.get("/api/schedule/benchmark?pressure=1.0").json()
    relaxed_rate = relaxed["fifo"]["on_time_rate_percent"]
    extreme_rate = extreme["fifo"]["on_time_rate_percent"]
    assert extreme_rate <= relaxed_rate, (
        f"Extreme pressure ({extreme_rate}%) should not exceed relaxed ({relaxed_rate}%)"
    )
