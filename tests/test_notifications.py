"""
Tests for /api/notifications router and Notification model.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _register_and_login(client, email="notif_user@example.com", name="Notif User"):
    client.post("/api/auth/register", json={
        "email": email,
        "password": "testpass123",
        "name": name,
    })
    client.post("/api/auth/login", json={
        "email": email,
        "password": "testpass123",
    })


def _create(client, **kwargs):
    payload = {
        "severity": "info",
        "category": "system",
        "title": "Test notification",
        "body": "hello world",
    }
    payload.update(kwargs)
    return client.post("/api/notifications", json=payload)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


class TestAuth:
    def test_list_requires_auth(self, client):
        r = client.get("/api/notifications")
        assert r.status_code == 401

    def test_create_requires_auth(self, client):
        r = client.post("/api/notifications", json={
            "severity": "info",
            "category": "system",
            "title": "x",
        })
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


class TestCreateAndList:

    def test_create_info(self, client):
        _register_and_login(client)
        r = _create(client)
        assert r.status_code == 200
        body = r.json()
        assert body["severity"] == "info"
        assert body["category"] == "system"
        assert body["title"] == "Test notification"
        assert body["is_read"] is False
        assert body["read_at"] is None

    def test_create_invalid_severity(self, client):
        _register_and_login(client)
        r = _create(client, severity="catastrophic")
        assert r.status_code == 400

    def test_create_invalid_category(self, client):
        _register_and_login(client)
        r = _create(client, category="fake_cat")
        assert r.status_code == 400

    def test_list_empty(self, client):
        _register_and_login(client)
        r = client.get("/api/notifications")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["unread"] == 0
        assert body["notifications"] == []

    def test_list_returns_created(self, client):
        _register_and_login(client)
        _create(client, title="first")
        _create(client, title="second", severity="warning", category="quality")
        r = client.get("/api/notifications")
        body = r.json()
        assert body["total"] == 2
        assert body["unread"] == 2
        titles = [n["title"] for n in body["notifications"]]
        assert set(titles) == {"first", "second"}

    def test_list_ordered_desc_by_created(self, client):
        _register_and_login(client)
        _create(client, title="older")
        _create(client, title="newer")
        r = client.get("/api/notifications")
        notifs = r.json()["notifications"]
        assert notifs[0]["title"] == "newer"
        assert notifs[1]["title"] == "older"

    def test_list_filter_by_category(self, client):
        _register_and_login(client)
        _create(client, category="quality", title="q")
        _create(client, category="scheduling", title="s")
        r = client.get("/api/notifications?category=quality")
        body = r.json()
        assert len(body["notifications"]) == 1
        assert body["notifications"][0]["category"] == "quality"

    def test_list_filter_by_severity(self, client):
        _register_and_login(client)
        _create(client, severity="critical", title="c")
        _create(client, severity="info", title="i")
        r = client.get("/api/notifications?severity=critical")
        body = r.json()
        assert len(body["notifications"]) == 1
        assert body["notifications"][0]["severity"] == "critical"

    def test_user_scoping(self, client):
        # User A creates a notification
        _register_and_login(client, email="a@example.com", name="Alice")
        _create(client, title="A_notif")
        # Logout + switch to user B
        client.post("/api/auth/logout")
        _register_and_login(client, email="b@example.com", name="Bob")
        r = client.get("/api/notifications")
        body = r.json()
        # B should not see A's notifications
        titles = [n["title"] for n in body["notifications"]]
        assert "A_notif" not in titles


class TestMarkRead:

    def test_mark_read_sets_read_at(self, client):
        _register_and_login(client)
        create_r = _create(client)
        nid = create_r.json()["id"]

        r = client.put(f"/api/notifications/{nid}/read")
        assert r.status_code == 200
        body = r.json()
        assert body["is_read"] is True
        assert body["read_at"] is not None

    def test_mark_read_is_idempotent(self, client):
        _register_and_login(client)
        nid = _create(client).json()["id"]
        r1 = client.put(f"/api/notifications/{nid}/read").json()
        r2 = client.put(f"/api/notifications/{nid}/read").json()
        assert r1["read_at"] == r2["read_at"]

    def test_mark_read_updates_unread_count(self, client):
        _register_and_login(client)
        nid = _create(client).json()["id"]
        assert client.get("/api/notifications/unread-count").json()["unread"] == 1
        client.put(f"/api/notifications/{nid}/read")
        assert client.get("/api/notifications/unread-count").json()["unread"] == 0

    def test_mark_read_nonexistent_404(self, client):
        _register_and_login(client)
        r = client.put("/api/notifications/99999/read")
        assert r.status_code == 404

    def test_cannot_mark_other_users_notification(self, client):
        _register_and_login(client, email="a@example.com", name="Alice")
        nid = _create(client).json()["id"]
        client.post("/api/auth/logout")

        _register_and_login(client, email="b@example.com", name="Bob")
        r = client.put(f"/api/notifications/{nid}/read")
        assert r.status_code == 404


class TestDismissAll:

    def test_dismiss_all_marks_everything_read(self, client):
        _register_and_login(client)
        for i in range(5):
            _create(client, title=f"n{i}")

        r = client.post("/api/notifications/dismiss-all")
        assert r.status_code == 200
        assert r.json()["dismissed"] == 5

        listing = client.get("/api/notifications").json()
        assert listing["unread"] == 0
        assert all(n["is_read"] for n in listing["notifications"])

    def test_dismiss_all_empty_is_zero(self, client):
        _register_and_login(client)
        r = client.post("/api/notifications/dismiss-all")
        assert r.json()["dismissed"] == 0

    def test_dismiss_all_scoped_to_user(self, client):
        _register_and_login(client, email="a@example.com", name="Alice")
        _create(client, title="A_notif")
        client.post("/api/auth/logout")

        _register_and_login(client, email="b@example.com", name="Bob")
        _create(client, title="B_notif")
        r = client.post("/api/notifications/dismiss-all")
        assert r.json()["dismissed"] == 1

        client.post("/api/auth/logout")
        _register_and_login(client, email="a@example.com", name="Alice")
        # A still has their unread notification
        assert client.get("/api/notifications/unread-count").json()["unread"] == 1


class TestUnreadCount:

    def test_unread_count_zero_initial(self, client):
        _register_and_login(client)
        r = client.get("/api/notifications/unread-count")
        assert r.status_code == 200
        assert r.json()["unread"] == 0

    def test_unread_count_increments(self, client):
        _register_and_login(client)
        _create(client)
        _create(client)
        assert client.get("/api/notifications/unread-count").json()["unread"] == 2
