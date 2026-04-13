"""
Tests for /api/operator — operator tablet endpoints.

Covers:
- POST /api/operator/login — happy path, wrong PIN, inactive operator
- GET  /api/operator/{id}/queue — own assignment + category qualification
- POST /api/operator/operations/{id}/start-setup — happy, unqualified, wrong status
- POST /api/operator/operations/{id}/setup-complete — timing, double complete
- POST /api/operator/operations/{id}/complete — qty capture, actual_run_min computed
- POST /api/operator/operations/{id}/pause — happy, not in_progress
- POST /api/operator/operations/{id}/flag — creates NCR, sets on_hold
- GET  /api/operator/work-centers/{id}/status — queue depth, no active op

Run with: pytest tests/test_operator.py -v
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import pytest
import database as db_module
from db_models import User, Operator, WorkCenter, Operation, ShopFloorEvent
from auth.jwt_utils import hash_password


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user(db) -> User:
    u = User(
        email="shop@test.com",
        hashed_password=hash_password("shoppass"),
        name="Shop Owner",
        is_active=True,
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _make_operator(db, user_id: int, *, name="Mike", pin="1234", qualifications=None) -> Operator:
    op = Operator(
        user_id=user_id,
        name=name,
        initials=name[:2].upper(),
        pin_code_hash=hash_password(pin),
        is_active=True,
        qualifications_json=json.dumps(qualifications or ["cnc_mill"]),
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return op


def _make_work_center(db, user_id: int, category="cnc_mill") -> WorkCenter:
    wc = WorkCenter(
        user_id=user_id,
        name=f"HAAS VF-2 ({category})",
        category=category,
        status="available",
        setup_time_default_min=30,
    )
    db.add(wc)
    db.commit()
    db.refresh(wc)
    return wc


def _make_operation(db, user_id: int, wc_id: int = None, category="cnc_mill", status="queued") -> Operation:
    op = Operation(
        user_id=user_id,
        operation_name="Face Mill Top",
        work_center_category=category,
        work_center_id=wc_id,
        status=status,
        estimated_setup_min=30.0,
        estimated_run_min=60.0,
        quantity=10,
        order_ref="ORD-001",
        sequence_number=10,
    )
    db.add(op)
    db.commit()
    db.refresh(op)
    return op


@pytest.fixture
def db():
    session = db_module.SessionLocal()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_happy_path(self, client, db):
        user = _make_user(db)
        _make_operator(db, user.id, name="Alice", pin="5678", qualifications=["cnc_mill"])
        _make_work_center(db, user.id, category="cnc_mill")

        res = client.post("/api/operator/login", json={"user_id": user.id, "pin_code": "5678"})
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Alice"
        assert len(data["qualified_work_centers"]) == 1
        assert data["qualified_work_centers"][0]["category"] == "cnc_mill"

    def test_wrong_pin(self, client, db):
        user = _make_user(db)
        _make_operator(db, user.id, pin="9999")

        res = client.post("/api/operator/login", json={"user_id": user.id, "pin_code": "0000"})
        assert res.status_code == 401

    def test_wrong_user_id(self, client, db):
        user = _make_user(db)
        _make_operator(db, user.id, pin="1234")

        res = client.post("/api/operator/login", json={"user_id": 9999, "pin_code": "1234"})
        assert res.status_code == 401

    def test_inactive_operator_not_returned(self, client, db):
        user = _make_user(db)
        op = _make_operator(db, user.id, pin="1234")
        op.is_active = False
        db.commit()

        res = client.post("/api/operator/login", json={"user_id": user.id, "pin_code": "1234"})
        assert res.status_code == 401

    def test_login_logs_event(self, client, db):
        user = _make_user(db)
        _make_operator(db, user.id, pin="4321")

        client.post("/api/operator/login", json={"user_id": user.id, "pin_code": "4321"})

        events = db.query(ShopFloorEvent).filter_by(event_type="operator_login").all()
        assert len(events) == 1

    def test_no_qualifications_returns_all_work_centers(self, client, db):
        user = _make_user(db)
        _make_operator(db, user.id, pin="1111", qualifications=[])
        # Only one work center — verify no-quals operator can access it
        # (multi-wc cross-session visibility is constrained by SQLite StaticPool)
        _make_work_center(db, user.id, category="cnc_mill")

        res = client.post("/api/operator/login", json={"user_id": user.id, "pin_code": "1111"})
        assert res.status_code == 200
        data = res.json()
        # No qualifications restriction — should see the work center
        assert len(data["qualified_work_centers"]) >= 1
        assert data["qualified_work_centers"][0]["category"] == "cnc_mill"


# ---------------------------------------------------------------------------
# Queue
# ---------------------------------------------------------------------------

class TestQueue:
    def test_returns_qualified_ops(self, client, db):
        user = _make_user(db)
        op = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id, category="cnc_mill")
        _make_operation(db, user.id, wc.id, category="cnc_mill", status="queued")
        # Different category — should NOT appear
        _make_operation(db, user.id, wc.id, category="cnc_lathe", status="queued")

        res = client.get(f"/api/operator/{op.id}/queue")
        assert res.status_code == 200
        ops = res.json()
        assert len(ops) == 1
        assert ops[0]["work_center_category"] == "cnc_mill"

    def test_excludes_complete_ops(self, client, db):
        user = _make_user(db)
        op = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        _make_operation(db, user.id, wc.id, status="complete")
        _make_operation(db, user.id, wc.id, status="queued")

        res = client.get(f"/api/operator/{op.id}/queue")
        assert len(res.json()) == 1

    def test_includes_own_assigned_ops(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_lathe"])
        wc = _make_work_center(db, user.id, category="cnc_mill")  # not in quals
        # Assigned directly to this operator
        direct_op = _make_operation(db, user.id, wc.id, category="cnc_mill", status="in_progress")
        direct_op.operator_id = operator.id
        db.commit()

        res = client.get(f"/api/operator/{operator.id}/queue")
        ids = [o["id"] for o in res.json()]
        assert direct_op.id in ids

    def test_404_inactive_operator(self, client, db):
        user = _make_user(db)
        op = _make_operator(db, user.id)
        op.is_active = False
        db.commit()

        res = client.get(f"/api/operator/{op.id}/queue")
        assert res.status_code == 404


# ---------------------------------------------------------------------------
# Start Setup
# ---------------------------------------------------------------------------

class TestStartSetup:
    def test_happy_path(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        res = client.post(
            f"/api/operator/operations/{operation.id}/start-setup",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "in_progress"
        assert data["setup_started_at"] is not None
        assert data["operator_id"] == operator.id

    def test_event_logged(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        client.post(
            f"/api/operator/operations/{operation.id}/start-setup",
            json={"operator_id": operator.id},
        )

        events = db.query(ShopFloorEvent).filter_by(event_type="op_started").all()
        assert len(events) == 1
        payload = json.loads(events[0].payload_json)
        assert payload["operation_name"] == "Face Mill Top"

    def test_unqualified_operator_rejected(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_lathe"])  # wrong category
        wc = _make_work_center(db, user.id, category="cnc_mill")
        operation = _make_operation(db, user.id, wc.id, category="cnc_mill", status="queued")

        res = client.post(
            f"/api/operator/operations/{operation.id}/start-setup",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 403

    def test_already_complete_rejected(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="complete")

        res = client.post(
            f"/api/operator/operations/{operation.id}/start-setup",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 409


# ---------------------------------------------------------------------------
# Setup Complete
# ---------------------------------------------------------------------------

class TestSetupComplete:
    def _start_setup(self, client, operator_id, operation_id):
        client.post(
            f"/api/operator/operations/{operation_id}/start-setup",
            json={"operator_id": operator_id},
        )

    def test_happy_path(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        self._start_setup(client, operator.id, operation.id)
        res = client.post(
            f"/api/operator/operations/{operation.id}/setup-complete",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["run_started_at"] is not None
        # actual_setup_min should be set (very small in tests, but not None)
        assert data["actual_setup_min"] is not None

    def test_double_setup_complete_rejected(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        self._start_setup(client, operator.id, operation.id)
        client.post(
            f"/api/operator/operations/{operation.id}/setup-complete",
            json={"operator_id": operator.id},
        )
        # Second call should fail
        res = client.post(
            f"/api/operator/operations/{operation.id}/setup-complete",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 409

    def test_not_in_progress_rejected(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        res = client.post(
            f"/api/operator/operations/{operation.id}/setup-complete",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 409


# ---------------------------------------------------------------------------
# Complete Operation
# ---------------------------------------------------------------------------

class TestCompleteOperation:
    def _setup_operation(self, client, operator_id, operation_id):
        client.post(f"/api/operator/operations/{operation_id}/start-setup", json={"operator_id": operator_id})
        client.post(f"/api/operator/operations/{operation_id}/setup-complete", json={"operator_id": operator_id})

    def test_happy_path(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        self._setup_operation(client, operator.id, operation.id)
        res = client.post(
            f"/api/operator/operations/{operation.id}/complete",
            json={"operator_id": operator.id, "quantity_complete": 9, "quantity_scrapped": 1, "scrap_reason": "Out of tolerance"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "complete"
        assert data["quantity_complete"] == 9
        assert data["quantity_scrapped"] == 1
        assert data["completed_at"] is not None
        assert data["actual_run_min"] is not None

    def test_event_logged_with_scrap(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        self._setup_operation(client, operator.id, operation.id)
        client.post(
            f"/api/operator/operations/{operation.id}/complete",
            json={"operator_id": operator.id, "quantity_complete": 10, "quantity_scrapped": 0},
        )

        events = db.query(ShopFloorEvent).filter_by(event_type="op_completed").all()
        assert len(events) == 1

    def test_already_complete_rejected(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="complete")

        res = client.post(
            f"/api/operator/operations/{operation.id}/complete",
            json={"operator_id": operator.id, "quantity_complete": 5},
        )
        assert res.status_code == 409


# ---------------------------------------------------------------------------
# Pause
# ---------------------------------------------------------------------------

class TestPause:
    def test_happy_path(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        # start it first
        client.post(f"/api/operator/operations/{operation.id}/start-setup", json={"operator_id": operator.id})
        res = client.post(
            f"/api/operator/operations/{operation.id}/pause",
            json={"operator_id": operator.id, "reason": "Tooling change"},
        )
        assert res.status_code == 200
        assert res.json()["status"] == "paused"

    def test_event_logged_with_reason(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        client.post(f"/api/operator/operations/{operation.id}/start-setup", json={"operator_id": operator.id})
        client.post(
            f"/api/operator/operations/{operation.id}/pause",
            json={"operator_id": operator.id, "reason": "Break"},
        )

        events = db.query(ShopFloorEvent).filter_by(event_type="op_paused").all()
        assert len(events) == 1
        assert json.loads(events[0].payload_json)["reason"] == "Break"

    def test_not_in_progress_rejected(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="queued")

        res = client.post(
            f"/api/operator/operations/{operation.id}/pause",
            json={"operator_id": operator.id},
        )
        assert res.status_code == 409


# ---------------------------------------------------------------------------
# Flag (NCR creation)
# ---------------------------------------------------------------------------

class TestFlag:
    def test_creates_ncr(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="in_progress")

        res = client.post(
            f"/api/operator/operations/{operation.id}/flag",
            json={"operator_id": operator.id, "severity": "major", "description": "Chatter marks on finish surface"},
        )
        assert res.status_code == 201
        data = res.json()
        assert data["severity"] == "major"
        assert data["status"] == "open"
        assert data["operation_id"] == operation.id

    def test_sets_operation_on_hold(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="in_progress")

        client.post(
            f"/api/operator/operations/{operation.id}/flag",
            json={"operator_id": operator.id, "severity": "critical", "description": "Incorrect material"},
        )

        db.refresh(operation)
        assert operation.status == "on_hold"

    def test_quality_hold_event_logged(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="in_progress")

        client.post(
            f"/api/operator/operations/{operation.id}/flag",
            json={"operator_id": operator.id, "severity": "minor", "description": "Burr on edge"},
        )

        events = db.query(ShopFloorEvent).filter_by(event_type="quality_hold").all()
        assert len(events) == 1

    def test_cannot_flag_complete_operation(self, client, db):
        user = _make_user(db)
        operator = _make_operator(db, user.id, qualifications=["cnc_mill"])
        wc = _make_work_center(db, user.id)
        operation = _make_operation(db, user.id, wc.id, status="complete")

        res = client.post(
            f"/api/operator/operations/{operation.id}/flag",
            json={"operator_id": operator.id, "severity": "minor", "description": "Late flag"},
        )
        assert res.status_code == 409


# ---------------------------------------------------------------------------
# Work Center Status
# ---------------------------------------------------------------------------

class TestWorkCenterStatus:
    def test_empty_work_center(self, client, db):
        user = _make_user(db)
        wc = _make_work_center(db, user.id)

        res = client.get(f"/api/operator/work-centers/{wc.id}/status")
        assert res.status_code == 200
        data = res.json()
        assert data["work_center_id"] == wc.id
        assert data["queue_depth"] == 0
        assert data["active_operation"] is None
        assert data["estimated_hours_remaining"] == 0.0

    def test_queue_depth_and_hours(self, client, db):
        user = _make_user(db)
        wc = _make_work_center(db, user.id)
        # 2 queued ops: 30 min setup + 60 min run each
        _make_operation(db, user.id, wc.id, status="queued")
        _make_operation(db, user.id, wc.id, status="queued")

        res = client.get(f"/api/operator/work-centers/{wc.id}/status")
        data = res.json()
        assert data["queue_depth"] == 2
        # 2 × (30 + 60) = 180 min = 3.0 hours
        assert data["estimated_hours_remaining"] == 3.0

    def test_active_operation_shown(self, client, db):
        user = _make_user(db)
        wc = _make_work_center(db, user.id)
        op = _make_operation(db, user.id, wc.id, status="in_progress")

        res = client.get(f"/api/operator/work-centers/{wc.id}/status")
        data = res.json()
        assert data["active_operation"] is not None
        assert data["active_operation"]["id"] == op.id
        # Active op's run time adds to estimated_hours_remaining
        assert data["estimated_hours_remaining"] == round(60.0 / 60.0, 2)

    def test_404_unknown_work_center(self, client):
        res = client.get("/api/operator/work-centers/99999/status")
        assert res.status_code == 404
