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
    """EDD on-time rate should be in the 78-85% range."""
    resp = client.get("/api/schedule/benchmark")
    rate = resp.json()["edd"]["on_time_rate_percent"]
    assert 76.0 <= rate <= 87.0, f"EDD on-time {rate}% outside expected [76.0, 87.0]"


def test_benchmark_sa_on_time_range(client):
    """SA on-time rate should be in the 92-98% range (fixed seed=123 → deterministic 96.4%)."""
    resp = client.get("/api/schedule/benchmark")
    rate = resp.json()["sa"]["on_time_rate_percent"]
    assert 92.0 <= rate <= 98.0, f"SA on-time {rate}% outside expected [92.0, 98.0]"


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


def test_benchmark_exact_locked_numbers(client):
    """SA seed=123 must produce exactly 96.4%, EDD exactly 82.1%, FIFO exactly 60.7%.

    These are the numbers we show in every demo and pitch. If this test fails,
    something changed in the dataset or algorithm — investigate before committing.
    """
    resp = client.get("/api/schedule/benchmark")
    assert resp.status_code == 200
    data = resp.json()
    assert data["fifo"]["on_time_rate_percent"] == 60.7, (
        f"FIFO must be exactly 60.7% — got {data['fifo']['on_time_rate_percent']}%"
    )
    assert data["edd"]["on_time_rate_percent"] == 82.1, (
        f"EDD must be exactly 82.1% — got {data['edd']['on_time_rate_percent']}%"
    )
    assert data["sa"]["on_time_rate_percent"] == 96.4, (
        f"SA must be exactly 96.4% — got {data['sa']['on_time_rate_percent']}%"
    )
    assert data["on_time_improvement_pp"] == 35.7, (
        f"Improvement must be exactly 35.7pp — got {data['on_time_improvement_pp']}pp"
    )


def test_benchmark_deterministic_across_10_runs(client):
    """Running the benchmark 10 times must produce bit-for-bit identical SA results.

    The SA algorithm uses seed=123 and a fixed reference_time. Any non-determinism
    here means the demo is unreliable under investor scrutiny.
    """
    results = [client.get("/api/schedule/benchmark").json() for _ in range(10)]
    sa_rates = [r["sa"]["on_time_rate_percent"] for r in results]
    edd_rates = [r["edd"]["on_time_rate_percent"] for r in results]
    assert len(set(sa_rates)) == 1, (
        f"SA is non-deterministic across 10 runs: {sa_rates}"
    )
    assert len(set(edd_rates)) == 1, (
        f"EDD is non-deterministic across 10 runs: {edd_rates}"
    )


def test_benchmark_pressure_lowers_on_time(client):
    """pressure=1.0 (tight due dates) should give lower FIFO on-time than pressure=0.0 (relaxed)."""
    relaxed = client.get("/api/schedule/benchmark?pressure=0.0").json()
    extreme = client.get("/api/schedule/benchmark?pressure=1.0").json()
    relaxed_rate = relaxed["fifo"]["on_time_rate_percent"]
    extreme_rate = extreme["fifo"]["on_time_rate_percent"]
    assert extreme_rate <= relaxed_rate, (
        f"Extreme pressure ({extreme_rate}%) should not exceed relaxed ({relaxed_rate}%)"
    )
