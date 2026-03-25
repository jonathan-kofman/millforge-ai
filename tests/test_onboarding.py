"""
Tests for the shop onboarding wizard endpoints.

Covers:
1. Status returns unconfigured for new user
2. PUT /api/onboarding/shop-config step 1 persists shop name and machine count
3. Wizard advances through all 3 steps and marks is_complete=True
4. wizard_step never regresses (lower step ignored)
5. GET /api/onboarding/shop-config returns 404 before any config saved
6. Auth required on all endpoints
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _register_and_token(client, email="wizard@example.com"):
    res = client.post("/api/auth/register", json={
        "email": email, "password": "password123", "name": "Wizard Tester",
    })
    assert res.status_code == 201
    return res.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Status for fresh user
# ---------------------------------------------------------------------------

def test_onboarding_status_new_user(client):
    """New user has no config: configured=False, is_complete=False, step=0."""
    token = _register_and_token(client)
    res = client.get("/api/onboarding/status", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["configured"] is False
    assert data["is_complete"] is False
    assert data["wizard_step"] == 0
    assert data["config"] is None


# ---------------------------------------------------------------------------
# 2. Step 1 — shop basics
# ---------------------------------------------------------------------------

def test_onboarding_step1_saves_name_and_machine_count(client):
    """Step 1 saves shop_name and machine_count; wizard_step advances to 1."""
    token = _register_and_token(client, "step1@example.com")
    res = client.put("/api/onboarding/shop-config", json={
        "shop_name": "Acme Metal Works",
        "machine_count": 4,
        "wizard_step": 1,
    }, headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["shop_name"] == "Acme Metal Works"
    assert data["machine_count"] == 4
    assert data["wizard_step"] == 1
    assert data["is_complete"] is False


# ---------------------------------------------------------------------------
# 3. All 3 steps → is_complete=True
# ---------------------------------------------------------------------------

def test_onboarding_three_steps_complete(client):
    """Completing all 3 wizard steps marks is_complete=True."""
    token = _register_and_token(client, "fullwiz@example.com")

    # Step 1
    client.put("/api/onboarding/shop-config", json={
        "shop_name": "Full Forge LLC",
        "machine_count": 6,
        "wizard_step": 1,
    }, headers=_auth(token))

    # Step 2
    client.put("/api/onboarding/shop-config", json={
        "materials": ["steel", "aluminum"],
        "weekly_order_volume": 50,
        "wizard_step": 2,
    }, headers=_auth(token))

    # Step 3
    res = client.put("/api/onboarding/shop-config", json={
        "scheduling_method": "edd",
        "baseline_otd": 62.0,
        "wizard_step": 3,
    }, headers=_auth(token))

    assert res.status_code == 200
    data = res.json()
    assert data["wizard_step"] == 3
    assert data["is_complete"] is True
    assert data["materials"] == ["steel", "aluminum"]
    assert data["weekly_order_volume"] == 50
    assert data["scheduling_method"] == "edd"
    assert data["baseline_otd"] == 62.0

    # Status also reflects completion
    status_res = client.get("/api/onboarding/status", headers=_auth(token))
    assert status_res.json()["is_complete"] is True


# ---------------------------------------------------------------------------
# 4. wizard_step never regresses
# ---------------------------------------------------------------------------

def test_onboarding_step_does_not_regress(client):
    """Sending a lower wizard_step does not overwrite a higher completed step."""
    token = _register_and_token(client, "regress@example.com")

    # Reach step 2
    client.put("/api/onboarding/shop-config", json={
        "shop_name": "Regress Shop",
        "machine_count": 2,
        "wizard_step": 2,
    }, headers=_auth(token))

    # Re-submit step 1 — should not regress
    res = client.put("/api/onboarding/shop-config", json={
        "shop_name": "Updated Name",
        "wizard_step": 1,
    }, headers=_auth(token))

    assert res.status_code == 200
    assert res.json()["wizard_step"] == 2  # unchanged
    assert res.json()["shop_name"] == "Updated Name"  # field still updated


# ---------------------------------------------------------------------------
# 5. GET 404 before any config
# ---------------------------------------------------------------------------

def test_onboarding_get_config_404_before_wizard(client):
    """GET /api/onboarding/shop-config returns 404 for unconfigured user."""
    token = _register_and_token(client, "noconfig@example.com")
    res = client.get("/api/onboarding/shop-config", headers=_auth(token))
    assert res.status_code == 404


# ---------------------------------------------------------------------------
# 6. Auth required
# ---------------------------------------------------------------------------

def test_onboarding_auth_required(client):
    """All onboarding endpoints require a bearer token."""
    assert client.get("/api/onboarding/status").status_code == 401
    assert client.put("/api/onboarding/shop-config", json={"wizard_step": 1}).status_code == 401
    assert client.get("/api/onboarding/shop-config").status_code == 401
