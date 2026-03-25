"""
Tests for the AnomalyDetector agent and /api/anomaly/detect endpoint.
"""

import sys
import os
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from agents.anomaly_detector import AnomalyDetector


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _future(hours: int) -> str:
    return (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=hours)).isoformat() + "Z"


def _past(hours: int) -> str:
    return (datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)).isoformat() + "Z"


CLEAN_ORDERS = [
    {"order_id": "A-001", "material": "steel",    "quantity": 100, "due_date": _future(48), "priority": 3, "complexity": 1.0},
    {"order_id": "A-002", "material": "aluminum",  "quantity": 120, "due_date": _future(72), "priority": 4, "complexity": 1.2},
    {"order_id": "A-003", "material": "titanium",  "quantity":  90, "due_date": _future(96), "priority": 5, "complexity": 1.1},
    {"order_id": "A-004", "material": "copper",    "quantity": 110, "due_date": _future(60), "priority": 3, "complexity": 1.0},
]


# ---------------------------------------------------------------------------
# Rule-based detection
# ---------------------------------------------------------------------------

class TestCleanBatch:

    def test_no_anomalies_on_clean_batch(self):
        det = AnomalyDetector()
        report = det.detect(CLEAN_ORDERS)
        assert report.anomalies == []

    def test_no_validation_failures_on_clean_batch(self):
        det = AnomalyDetector()
        report = det.detect(CLEAN_ORDERS)
        assert report.validation_failures == []

    def test_orders_analysed_matches_input(self):
        det = AnomalyDetector()
        report = det.detect(CLEAN_ORDERS)
        assert report.orders_analysed == len(CLEAN_ORDERS)

    def test_summary_is_nonempty(self):
        det = AnomalyDetector()
        report = det.detect(CLEAN_ORDERS)
        assert isinstance(report.summary, str) and len(report.summary) > 0

    def test_analysed_at_is_datetime(self):
        det = AnomalyDetector()
        report = det.detect(CLEAN_ORDERS)
        assert isinstance(report.analysed_at, datetime)


class TestDuplicateId:

    def test_detects_duplicate_order_id(self):
        orders = list(CLEAN_ORDERS) + [
            {"order_id": "A-001", "material": "steel", "quantity": 50,
             "due_date": _future(24), "priority": 2, "complexity": 1.0},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        types = [a.anomaly_type for a in report.anomalies]
        assert "duplicate_id" in types

    def test_duplicate_id_severity_is_critical(self):
        orders = list(CLEAN_ORDERS) + [
            {"order_id": "A-001", "material": "steel", "quantity": 50,
             "due_date": _future(24), "priority": 2, "complexity": 1.0},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        dupes = [a for a in report.anomalies if a.anomaly_type == "duplicate_id"]
        assert all(a.severity == "critical" for a in dupes)


class TestImpossibleDeadline:

    def test_detects_past_due_date(self):
        orders = [
            {"order_id": "PAST-001", "material": "steel", "quantity": 100,
             "due_date": _past(2), "priority": 1, "complexity": 1.0},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        types = [a.anomaly_type for a in report.anomalies]
        assert "impossible_deadline" in types

    def test_past_deadline_severity_is_critical(self):
        orders = [
            {"order_id": "PAST-001", "material": "steel", "quantity": 100,
             "due_date": _past(2), "priority": 1, "complexity": 1.0},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        deadlines = [a for a in report.anomalies if a.anomaly_type == "impossible_deadline"]
        assert any(a.severity == "critical" for a in deadlines)


class TestQuantitySpike:

    def test_detects_quantity_spike(self):
        orders = [
            {"order_id": "Q-001", "material": "steel",    "quantity":  100, "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "Q-002", "material": "aluminum",  "quantity":  110, "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "Q-003", "material": "titanium",  "quantity":  90,  "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "Q-004", "material": "copper",    "quantity": 2000, "due_date": _future(48), "priority": 3, "complexity": 1.0},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        types = [a.anomaly_type for a in report.anomalies]
        assert "quantity_spike" in types

    def test_quantity_spike_points_to_correct_order(self):
        orders = [
            {"order_id": "Q-001", "material": "steel",   "quantity":  100, "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "Q-002", "material": "aluminum", "quantity":  110, "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "Q-003", "material": "titanium", "quantity":  90,  "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "Q-004", "material": "copper",   "quantity": 2000, "due_date": _future(48), "priority": 3, "complexity": 1.0},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        spikes = [a for a in report.anomalies if a.anomaly_type == "quantity_spike"]
        assert any(a.order_id == "Q-004" for a in spikes)


class TestMaterialClustering:

    def test_detects_material_clustering(self):
        orders = [
            {"order_id": f"S-{i}", "material": "steel", "quantity": 100,
             "due_date": _future(48), "priority": 3, "complexity": 1.0}
            for i in range(9)
        ] + [
            {"order_id": "A-001", "material": "aluminum", "quantity": 100,
             "due_date": _future(48), "priority": 3, "complexity": 1.0}
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        types = [a.anomaly_type for a in report.anomalies]
        assert "material_clustering" in types


class TestComplexityOutlier:

    def test_detects_complexity_outlier(self):
        orders = [
            {"order_id": "C-001", "material": "steel",   "quantity": 100, "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "C-002", "material": "steel",   "quantity": 100, "due_date": _future(48), "priority": 3, "complexity": 1.1},
            {"order_id": "C-003", "material": "steel",   "quantity": 100, "due_date": _future(48), "priority": 3, "complexity": 1.0},
            {"order_id": "C-004", "material": "steel",   "quantity": 100, "due_date": _future(48), "priority": 3, "complexity": 4.8},
        ]
        det = AnomalyDetector()
        report = det.detect(orders)
        types = [a.anomaly_type for a in report.anomalies]
        assert "complexity_outlier" in types


# ---------------------------------------------------------------------------
# Validation loop
# ---------------------------------------------------------------------------

class TestAnomalyValidation:

    def test_no_validation_failures_when_healthy(self):
        det = AnomalyDetector()
        report = det.detect(CLEAN_ORDERS)
        assert report.validation_failures == []

    def test_validation_catches_bad_severity(self, monkeypatch):
        from agents import anomaly_detector as mod
        det = AnomalyDetector()
        _real = det._rule_detect

        def bad_detect(orders):
            anomalies = _real(orders)
            from agents.anomaly_detector import Anomaly
            anomalies.append(Anomaly(
                order_id="BAD",
                anomaly_type="quantity_spike",
                severity="BOGUS_SEVERITY",
                description="injected for test",
            ))
            return anomalies

        monkeypatch.setattr(det, "_rule_detect", bad_detect)
        report = det.detect(CLEAN_ORDERS)
        assert any("invalid severity" in f for f in report.validation_failures)

    def test_validation_catches_bad_type(self, monkeypatch):
        det = AnomalyDetector()
        _real = det._rule_detect

        def bad_detect(orders):
            anomalies = _real(orders)
            from agents.anomaly_detector import Anomaly
            anomalies.append(Anomaly(
                order_id="BAD",
                anomaly_type="NOT_A_REAL_TYPE",
                severity="warning",
                description="injected for test",
            ))
            return anomalies

        monkeypatch.setattr(det, "_rule_detect", bad_detect)
        report = det.detect(CLEAN_ORDERS)
        assert any("invalid type" in f for f in report.validation_failures)

    def test_retry_stops_on_first_valid(self, monkeypatch):
        """After one bad attempt the heuristic fallback should produce a valid report."""
        det = AnomalyDetector()
        attempt_count = [0]
        _real = det._rule_detect

        def counting_detect(orders):
            attempt_count[0] += 1
            result = _real(orders)
            # First call injects a bad anomaly; subsequent calls are clean
            if attempt_count[0] == 1:
                from agents.anomaly_detector import Anomaly
                result.append(Anomaly(
                    order_id="BAD",
                    anomaly_type="NOT_VALID",
                    severity="warning",
                    description="injected",
                ))
            return result

        monkeypatch.setattr(det, "_rule_detect", counting_detect)
        report = det.detect(CLEAN_ORDERS)
        assert attempt_count[0] >= 2
        assert report.validation_failures == []


# ---------------------------------------------------------------------------
# API endpoint
# ---------------------------------------------------------------------------

class TestAnomalyAPI:

    def test_detect_endpoint_200(self, client):
        r = client.post("/api/anomaly/detect", json={"orders": CLEAN_ORDERS})
        assert r.status_code == 200

    def test_detect_response_shape(self, client):
        r = client.post("/api/anomaly/detect", json={"orders": CLEAN_ORDERS})
        data = r.json()
        assert "orders_analysed" in data
        assert "anomalies" in data
        assert "summary" in data
        assert isinstance(data["anomalies"], list)

    def test_detect_flags_past_due_date(self, client):
        orders = [
            {"order_id": "API-PAST", "material": "steel", "quantity": 100,
             "due_date": _past(5), "priority": 1, "complexity": 1.0},
        ]
        r = client.post("/api/anomaly/detect", json={"orders": orders})
        assert r.status_code == 200
        types = [a["anomaly_type"] for a in r.json()["anomalies"]]
        assert "impossible_deadline" in types

    def test_detect_returns_zero_anomalies_for_clean_batch(self, client):
        r = client.post("/api/anomaly/detect", json={"orders": CLEAN_ORDERS})
        assert r.status_code == 200
        assert r.json()["anomalies"] == []
