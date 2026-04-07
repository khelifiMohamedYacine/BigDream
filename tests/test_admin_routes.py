"""
Tests for admin_routes — all 10 admin endpoints.
Covers: user listing/search/pagination, CRUD, role changes,
deactivate/reactivate, system stats, audit log, dashboard.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.auth_routes import create_auth_router
from backend.admin_routes import create_admin_router


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

@pytest.fixture
def client(db, auth):
    app = FastAPI()
    app.include_router(create_auth_router(db, auth))
    app.include_router(create_admin_router(db, auth))
    return TestClient(app)


@pytest.fixture
def setup(client, db, auth):
    """Register an admin and a regular user; return (client, admin_token, user_id)."""
    # Register admin
    resp = client.post("/api/auth/register", json={
        "name": "Admin", "email": "admin@test.com",
        "password": "Password1!", "confirm_password": "Password1!",
    })
    admin_user = resp.json()["user"]
    db.update_user_role(admin_user["user_id"], "admin")
    admin_token = auth.generate_token(admin_user["user_id"], "admin@test.com", "admin")

    # Register normal user
    resp2 = client.post("/api/auth/register", json={
        "name": "Bob", "email": "bob@test.com",
        "password": "Password1!", "confirm_password": "Password1!",
    })
    bob_id = resp2.json()["user"]["user_id"]

    return client, admin_token, admin_user["user_id"], bob_id


def ah(token):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# List all users
# ---------------------------------------------------------------------------

class TestListUsers:
    def test_admin_can_list_users(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/users", headers=ah(admin_token))
        assert resp.status_code == 200
        assert "users" in resp.json()

    def test_non_admin_cannot_list_users(self, client, db, auth):
        user = db.create_user("Alice", "alice@test.com", "pass")
        token = auth.generate_token(user["user_id"], user["email"], "user")
        resp = client.get("/api/admin/users", headers=ah(token))
        assert resp.status_code == 403

    def test_unauthenticated_cannot_list_users(self, client):
        resp = client.get("/api/admin/users")
        assert resp.status_code in (401, 403, 422)

    def test_pagination_page_param(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/users?page=1&per_page=1", headers=ah(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "users" in data

    def test_search_filters_results(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/users?search=bob", headers=ah(admin_token))
        assert resp.status_code == 200
        users = resp.json()["users"]
        assert all("bob" in u["email"].lower() or "bob" in u["name"].lower() for u in users)


# ---------------------------------------------------------------------------
# Get single user
# ---------------------------------------------------------------------------

class TestGetUser:
    def test_admin_gets_user_details(self, setup):
        client, admin_token, _, bob_id = setup
        resp = client.get(f"/api/admin/users/{bob_id}", headers=ah(admin_token))
        assert resp.status_code == 200
        assert resp.json()["user"]["user_id"] == bob_id

    def test_nonexistent_user_returns_404(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/users/no-such-id", headers=ah(admin_token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Create user (admin)
# ---------------------------------------------------------------------------

class TestAdminCreateUser:
    def test_admin_creates_user(self, setup):
        client, admin_token, _, _ = setup
        resp = client.post("/api/admin/users",
                           json={"name": "Carol", "email": "carol@test.com",
                                 "password": "Password1!", "role": "user"},
                           headers=ah(admin_token))
        assert resp.status_code == 200

    def test_admin_creates_admin_user(self, setup):
        client, admin_token, _, _ = setup
        resp = client.post("/api/admin/users",
                           json={"name": "Carol", "email": "carol@test.com",
                                 "password": "Password1!", "role": "admin"},
                           headers=ah(admin_token))
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"

    def test_invalid_role_returns_400(self, setup):
        client, admin_token, _, _ = setup
        resp = client.post("/api/admin/users",
                           json={"name": "Carol", "email": "carol@test.com",
                                 "password": "Password1!", "role": "superuser"},
                           headers=ah(admin_token))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Update user role
# ---------------------------------------------------------------------------

class TestUpdateUserRole:
    def test_promote_to_admin(self, setup):
        client, admin_token, admin_id, bob_id = setup
        resp = client.put(f"/api/admin/users/{bob_id}/role",
                          json={"role": "admin"},
                          headers=ah(admin_token))
        assert resp.status_code == 200

    def test_cannot_change_own_role(self, setup):
        client, admin_token, admin_id, _ = setup
        resp = client.put(f"/api/admin/users/{admin_id}/role",
                          json={"role": "user"},
                          headers=ah(admin_token))
        assert resp.status_code == 400

    def test_nonexistent_user_returns_404(self, setup):
        client, admin_token, _, _ = setup
        resp = client.put("/api/admin/users/no-such/role",
                          json={"role": "admin"},
                          headers=ah(admin_token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Deactivate / reactivate
# ---------------------------------------------------------------------------

class TestDeactivateReactivate:
    def test_deactivate_user(self, setup, db):
        client, admin_token, _, bob_id = setup
        resp = client.post(f"/api/admin/users/{bob_id}/deactivate",
                           headers=ah(admin_token))
        assert resp.status_code == 200
        raw = db._read_json(db.users_file)
        assert raw[bob_id]["is_active"] is False

    def test_cannot_deactivate_self(self, setup):
        client, admin_token, admin_id, _ = setup
        resp = client.post(f"/api/admin/users/{admin_id}/deactivate",
                           headers=ah(admin_token))
        assert resp.status_code == 400

    def test_reactivate_user(self, setup, db):
        client, admin_token, _, bob_id = setup
        db.deactivate_user(bob_id)
        resp = client.post(f"/api/admin/users/{bob_id}/reactivate",
                           headers=ah(admin_token))
        assert resp.status_code == 200
        raw = db._read_json(db.users_file)
        assert raw[bob_id]["is_active"] is True


# ---------------------------------------------------------------------------
# Delete user (admin)
# ---------------------------------------------------------------------------

class TestAdminDeleteUser:
    def test_admin_deletes_user(self, setup, db):
        client, admin_token, _, bob_id = setup
        resp = client.delete(f"/api/admin/users/{bob_id}", headers=ah(admin_token))
        assert resp.status_code == 200
        assert db.get_user_by_id(bob_id) is None

    def test_cannot_delete_self(self, setup):
        client, admin_token, admin_id, _ = setup
        resp = client.delete(f"/api/admin/users/{admin_id}", headers=ah(admin_token))
        assert resp.status_code == 400

    def test_delete_nonexistent_returns_404(self, setup):
        client, admin_token, _, _ = setup
        resp = client.delete("/api/admin/users/no-such-id", headers=ah(admin_token))
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# System stats
# ---------------------------------------------------------------------------

class TestSystemStats:
    def test_admin_gets_system_stats(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/stats", headers=ah(admin_token))
        assert resp.status_code == 200
        data = resp.json()
        assert "stats" in data
        assert "users" in data["stats"]
        assert data["stats"]["users"]["total"] >= 0

    def test_non_admin_cannot_get_stats(self, client, db, auth):
        user = db.create_user("Alice", "a@test.com", "pass")
        token = auth.generate_token(user["user_id"], user["email"], "user")
        resp = client.get("/api/admin/stats", headers=ah(token))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class TestAuditLog:
    def test_admin_gets_audit_log(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/audit-log", headers=ah(admin_token))
        assert resp.status_code == 200
        assert "log" in resp.json()

    def test_non_admin_cannot_get_audit_log(self, client, db, auth):
        user = db.create_user("Alice", "a@test.com", "pass")
        token = auth.generate_token(user["user_id"], user["email"], "user")
        resp = client.get("/api/admin/audit-log", headers=ah(token))
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

class TestAdminDashboard:
    def test_admin_gets_dashboard(self, setup):
        client, admin_token, _, _ = setup
        resp = client.get("/api/admin/dashboard", headers=ah(admin_token))
        assert resp.status_code == 200

    def test_non_admin_cannot_get_dashboard(self, client, db, auth):
        user = db.create_user("Alice", "a@test.com", "pass")
        token = auth.generate_token(user["user_id"], user["email"], "user")
        resp = client.get("/api/admin/dashboard", headers=ah(token))
        assert resp.status_code == 403
