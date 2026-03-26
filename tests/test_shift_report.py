"""
Tests for ShiftReportAgent and shift handover REST endpoints.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from agents.shift_report import ShiftReportAgent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _window(hours: int = 8):
    end = _now()
    return end - timedelta(hours=hours), end


def _make_db(
    *,
    feedback_rows=None,
    held_orders=None,
    quality_failures=None,
    rework_orders=None,
):
    """Return a mock SQLAlchemy Session with pre-canned query results."""
    db = MagicMock()

    def _query_side_effect(model):
        from db_models import JobFeedbackRecord, OrderRecord, InspectionRecord

        mock_q = MagicMock()

        if model is JobFeedbackRecord:
            rows = feedback_rows or []
        elif model is OrderRecord:
            rows = []  # overridden by filter
        elif model is InspectionRecord:
            rows = quality_failures or []
        else:
            rows = []

        mock_q.filter.return_value = mock_q
        mock_q.order_by.return_value = mock_q
        mock_q.all.return_value = rows
        return mock_q

    db.query.side_effect = _query_side_effect
    return db


def _feedback_row(
    order_id="ORD-001",
    machine_id=1,
    material="steel",
    actual_setup=10.0,
    actual_proc=45.0,
    pred_setup=12.0,
    pred_proc=42.0,
    provenance="mtconnect_auto",
):
    row = MagicMock()
    row.order_id = order_id
    row.machine_id = machine_id
    row.material = material
    row.actual_setup_minutes = actual_setup
    row.actual_processing_minutes = actual_proc
    row.predicted_setup_minutes = pred_setup
    row.predicted_processing_minutes = pred_proc
    row.data_provenance = provenance
    row.logged_at = _now()
    return row


def _order_row(order_id="ORD-H1", material="steel", qty=100, priority=5):
    row = MagicMock()
    row.order_id = order_id
    row.material = material
    row.quantity = qty
    row.priority = priority
    row.complexity = 1.0
    row.due_date = _now() + timedelta(days=3)
    row.notes = None
    row.updated_at = _now()
    row.created_at = _now()
    return row


def _inspection_row(order_id="ORD-F1", confidence=0.91, defects=None, passed=False):
    row = MagicMock()
    row.order_id_str = order_id
    row.confidence = confidence
    row.defects = defects or ["scratches"]
    row.passed = passed
    row.recommendation = "Rework required"
    row.inspector_version = "heuristic"
    row.created_at = _now()
    return row


# ---------------------------------------------------------------------------
# ShiftReportAgent — data gathering
# ---------------------------------------------------------------------------

def test_gather_empty_db_returns_valid_structure():
    agent = ShiftReportAgent()
    db = _make_db()
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)

    assert "summary" in report
    assert "jobs_completed" in report
    assert "jobs_in_progress" in report
    assert "held_orders" in report
    assert "quality_failures" in report
    assert "rework_dispatched" in report
    assert "open_exceptions" in report
    assert "energy" in report


def test_gather_counts_match_summary():
    agent = ShiftReportAgent()
    db = _make_db(feedback_rows=[_feedback_row(), _feedback_row("ORD-002")])
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)

    assert report["summary"]["jobs_completed_count"] == 2
    assert report["summary"]["held_orders_count"] == 0


def test_jobs_completed_fields():
    agent = ShiftReportAgent()
    row = _feedback_row(order_id="ORD-X", machine_id=2, material="aluminum",
                        actual_setup=8.0, actual_proc=50.0, pred_setup=10.0, pred_proc=45.0)
    db = _make_db(feedback_rows=[row])
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)

    job = report["jobs_completed"][0]
    assert job["order_id"] == "ORD-X"
    assert job["machine_id"] == 2
    assert job["material"] == "aluminum"
    assert job["actual_setup_minutes"] == 8.0
    assert job["setup_delta_minutes"] == -2.0  # 8 - 10
    assert job["processing_delta_minutes"] == 5.0  # 50 - 45


def test_quality_failures_fields():
    agent = ShiftReportAgent()
    row = _inspection_row(order_id="ORD-F1", confidence=0.95, defects=["crazing", "scratches"])
    db = _make_db(quality_failures=[row])
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)

    assert report["summary"]["quality_failures_count"] == 1
    failure = report["quality_failures"][0]
    assert failure["order_id"] == "ORD-F1"
    assert "crazing" in failure["defects"]


def test_energy_estimate_nonzero_with_jobs():
    agent = ShiftReportAgent()
    # steel: 85 kW, 10 setup + 60 proc = 70 min = 85*70/60 ≈ 99.2 kWh
    row = _feedback_row(material="steel", actual_setup=10.0, actual_proc=60.0)
    db = _make_db(feedback_rows=[row])
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)

    assert report["energy"]["total_kwh"] > 0
    assert report["energy"]["cost_usd"] > 0
    assert "steel" in report["energy"]["by_material"]


def test_energy_zero_with_no_jobs():
    agent = ShiftReportAgent()
    db = _make_db()
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)

    assert report["energy"]["total_kwh"] == 0.0
    assert report["energy"]["cost_usd"] == 0.0


def test_energy_kwh_calculation():
    agent = ShiftReportAgent()
    # steel=85 kW, 60 min proc + 0 setup → 85 * 60 / 60 = 85 kWh
    row = _feedback_row(material="steel", actual_setup=0.0, actual_proc=60.0)
    db = _make_db(feedback_rows=[row])
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)
    assert abs(report["energy"]["total_kwh"] - 85.0) < 0.1


def test_jobs_in_progress_from_fleet():
    agent = ShiftReportAgent()
    fleet = MagicMock()
    fleet.snapshot.return_value = [
        {"machine_id": 1, "state": "RUNNING", "job_id": "ORD-LIVE"},
        {"machine_id": 2, "state": "IDLE", "job_id": None},
        {"machine_id": 3, "state": "SETUP", "job_id": "ORD-NEXT"},
    ]
    db = _make_db()
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end, fleet=fleet)

    # IDLE machines excluded
    assert report["summary"]["jobs_in_progress_count"] == 2
    states = {m["state"] for m in report["jobs_in_progress"]}
    assert states == {"RUNNING", "SETUP"}


def test_jobs_in_progress_empty_without_fleet():
    agent = ShiftReportAgent()
    db = _make_db()
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end, fleet=None)
    assert report["jobs_in_progress"] == []


def test_open_exceptions_graceful_fallback():
    """If ExceptionQueueAgent raises, open_exceptions returns []."""
    agent = ShiftReportAgent()
    db = _make_db()
    start, end = _window()
    # Pass a broken inventory_agent; exception should be swallowed
    with patch("agents.exception_queue.ExceptionQueueAgent.gather", side_effect=RuntimeError("oops")):
        report = agent.gather(db, shift_start=start, shift_end=end)
    assert isinstance(report["open_exceptions"], list)


# ---------------------------------------------------------------------------
# ShiftReportAgent — PDF export
# ---------------------------------------------------------------------------

def test_build_pdf_returns_bytes():
    agent = ShiftReportAgent()
    db = _make_db(feedback_rows=[_feedback_row()])
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)
    pdf = agent.build_pdf(report)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"


def test_build_pdf_empty_report():
    agent = ShiftReportAgent()
    db = _make_db()
    start, end = _window()
    report = agent.gather(db, shift_start=start, shift_end=end)
    pdf = agent.build_pdf(report)
    assert pdf[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

def test_get_shift_report_ok(client):
    resp = client.get("/api/shift/report")
    assert resp.status_code == 200
    body = resp.json()
    assert "summary" in body
    assert "jobs_completed" in body
    assert "shift_start" in body
    assert "shift_end" in body
    assert "generated_at" in body


def test_get_shift_report_summary_keys(client):
    resp = client.get("/api/shift/report")
    summary = resp.json()["summary"]
    for key in [
        "jobs_completed_count", "jobs_in_progress_count", "held_orders_count",
        "quality_failures_count", "rework_dispatched_count", "open_exceptions_count",
        "total_energy_kwh", "estimated_energy_cost_usd",
    ]:
        assert key in summary, f"Missing key: {key}"


def test_get_shift_report_hours_back(client):
    resp = client.get("/api/shift/report?hours_back=4")
    assert resp.status_code == 200
    body = resp.json()
    start = datetime.fromisoformat(body["shift_start"])
    end = datetime.fromisoformat(body["shift_end"])
    assert (end - start).total_seconds() / 3600 == pytest.approx(4, abs=0.1)


def test_get_shift_report_explicit_window(client):
    start = "2026-03-26T06:00:00"
    end = "2026-03-26T14:00:00"
    resp = client.get(f"/api/shift/report?shift_start={start}&shift_end={end}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["shift_start"].startswith("2026-03-26T06:00")
    assert body["shift_end"].startswith("2026-03-26T14:00")


def test_get_shift_report_invalid_window(client):
    resp = client.get("/api/shift/report?shift_start=2026-03-26T14:00:00&shift_end=2026-03-26T06:00:00")
    assert resp.status_code == 422


def test_post_shift_report_ok(client):
    resp = client.post("/api/shift/report", json={
        "shift_start": "2026-03-26T00:00:00",
        "shift_end": "2026-03-26T08:00:00",
    })
    assert resp.status_code == 200
    assert "summary" in resp.json()


def test_get_shift_report_pdf_ok(client):
    resp = client.get("/api/shift/report.pdf")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"
    assert "attachment" in resp.headers.get("content-disposition", "")
