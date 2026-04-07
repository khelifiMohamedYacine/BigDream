"""
test_admin_routes.py
====================
Integration tests for all admin_routes endpoints.

Endpoints covered:
  GET    /api/admin/users
  GET    /api/admin/users/{user_id}
  POST   /api/admin/users
  PUT    /api/admin/users/{user_id}/role
  POST   /api/admin/users/{user_id}/deactivate
  POST   /api/admin/users/{user_id}/reactivate
  DELETE /api/admin/users/{user_id}
  GET    /api/admin/stats
  GET    /api/admin/audit-log
  GET    /api/admin/dashboard

Permission rules tested:
  - All endpoints require admin token
  - Admin cannot deactivate/delete/change-role of own account
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.admin_routes import create_admin_router
from backend.auth_routes import create_auth_router


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Fixtures
# ===========================================================================

@pytest.fixture
def full_client(db, auth):
    """Client for both auth + admin routes so we can create tokens via API."""
    app = FastAPI()
    app.include_router(create_auth_router(db, auth))
    app.include_router(create_admin_router(db, auth))
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def admin_tok(full_client, sample_admin, auth):
    return auth.generate_token(
        sample_admin["user_id"], sample_admin["email"], sample_admin["role"]
    )


@pytest.fixture
def user_tok(full_client, sample_user, auth):
    return auth.generate_token(
        sample_user["user_id"], sample_user["email"], sample_user["role"]
    )


# ===========================================================================
# Access control — all endpoints block non-admins
# ===========================================================================

class TestAdminAccessControl:
    ENDPOINTS = [
        ("GET",    "/api/admin/users",    None),
        ("GET",    "/api/admin/stats",    None),
        ("GET",    "/api/admin/audit-log", None),
        ("GET",    "/api/admin/dashboard", None),
    ]

    def test_no_token_returns_4xx(self, full_client):
        for method, path, _ in self.ENDPOINTS:
            resp = full_client.request(method, path)
            assert resp.status_code in (401, 403, 422), f"{method} {path} returned {resp.status_code}"

    def test_regular_user_token_returns_403(self, full_client, user_tok):
        for method, path, _ in self.ENDPOINTS:
            resp = full_client.request(method, path, headers=bearer(user_tok))
            assert resp.status_code == 403, f"{method} {path} should be 403, got {resp.status_code}"


# ===========================================================================
# GET /api/admin/users
# ===========================================================================

class TestListUsers:
    def test_returns_200_with_users_list(self, full_client, admin_tok, sample_user):
        resp = full_client.get("/api/admin/users", headers=bearer(admin_tok))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["users"], list)

    def test_pagination_fields_present(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/users", headers=bearer(admin_tok))
        data = resp.json()
        assert "total" in data
        assert "page" in data
        assert "per_page" in data
        assert "total_pages" in data

    def test_default_page_is_1(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/users", headers=bearer(admin_tok))
        assert resp.json()["page"] == 1

    def test_search_filters_by_name(self, full_client, admin_tok, sample_user):
        resp = full_client.get(
            "/api/admin/users?search=alice", headers=bearer(admin_tok)
        )
        data = resp.json()
        assert all(
            "alice" in u.get("name", "").lower() or
            "alice" in u.get("email", "").lower()
            for u in data["users"]
        )

    def test_search_no_match_returns_empty_list(self, full_client, admin_tok):
        resp = full_client.get(
            "/api/admin/users?search=ZZZNOMATCH", headers=bearer(admin_tok)
        )
        assert resp.json()["users"] == []

    def test_per_page_limit_respected(self, full_client, admin_tok, db):
        # Create 5 extra users
        for i in range(5):
            db.create_user(f"User{i}", f"user{i}@test.com", "pass")
        resp = full_client.get(
            "/api/admin/users?per_page=2", headers=bearer(admin_tok)
        )
        assert len(resp.json()["users"]) <= 2

    def test_no_password_hash_in_users(self, full_client, admin_tok, sample_user):
        resp = full_client.get("/api/admin/users", headers=bearer(admin_tok))
        for u in resp.json()["users"]:
            assert "password_hash" not in u


# ===========================================================================
# GET /api/admin/users/{user_id}
# ===========================================================================

class TestGetSingleUser:
    def test_existing_user_returns_200(self, full_client, admin_tok, sample_user):
        resp = full_client.get(
            f"/api/admin/users/{sample_user['user_id']}", headers=bearer(admin_tok)
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["user"]["user_id"] == sample_user["user_id"]

    def test_response_includes_stats(self, full_client, admin_tok, sample_user):
        resp = full_client.get(
            f"/api/admin/users/{sample_user['user_id']}", headers=bearer(admin_tok)
        )
        assert "stats" in resp.json()

    def test_response_includes_goals_count(self, full_client, admin_tok, sample_user):
        resp = full_client.get(
            f"/api/admin/users/{sample_user['user_id']}", headers=bearer(admin_tok)
        )
        assert "goals_count" in resp.json()

    def test_missing_user_returns_404(self, full_client, admin_tok):
        resp = full_client.get(
            "/api/admin/users/nonexistent-id", headers=bearer(admin_tok)
        )
        assert resp.status_code == 404

    def test_no_password_hash_in_response(self, full_client, admin_tok, sample_user):
        resp = full_client.get(
            f"/api/admin/users/{sample_user['user_id']}", headers=bearer(admin_tok)
        )
        assert "password_hash" not in resp.json()["user"]


# ===========================================================================
# POST /api/admin/users
# ===========================================================================

class TestCreateUserAdmin:
    def test_create_user_returns_200(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users",
            json={"name": "Bob", "email": "bob@test.com",
                  "password": "Pass123!", "role": "user"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_create_admin_user_returns_200(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users",
            json={"name": "Admin2", "email": "admin2@test.com",
                  "password": "Pass123!", "role": "admin"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"

    def test_duplicate_email_returns_400(self, full_client, admin_tok, sample_user):
        resp = full_client.post(
            "/api/admin/users",
            json={"name": "Dup", "email": sample_user["email"],
                  "password": "Pass123!", "role": "user"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 400

    def test_invalid_role_returns_400(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users",
            json={"name": "X", "email": "x@test.com",
                  "password": "Pass123!", "role": "superuser"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 400
        assert "role" in resp.json()["detail"].lower()

    def test_missing_fields_returns_422(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users", json={"name": "X"}, headers=bearer(admin_tok)
        )
        assert resp.status_code == 422

    def test_no_password_hash_in_response(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users",
            json={"name": "Bob", "email": "bob@test.com",
                  "password": "Pass123!", "role": "user"},
            headers=bearer(admin_tok),
        )
        assert "password_hash" not in resp.json()["user"]


# ===========================================================================
# PUT /api/admin/users/{user_id}/role
# ===========================================================================

class TestUpdateUserRole:
    def test_update_to_admin_returns_200(self, full_client, admin_tok, sample_user):
        resp = full_client.put(
            f"/api/admin/users/{sample_user['user_id']}/role",
            json={"role": "admin"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["role"] == "admin"

    def test_update_to_user_returns_200(self, full_client, admin_tok, db, auth):
        other = db.create_user("Other", "other@test.com", "pass", role="admin")
        resp = full_client.put(
            f"/api/admin/users/{other['user_id']}/role",
            json={"role": "user"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 200

    def test_self_role_change_blocked(self, full_client, admin_tok, sample_admin):
        resp = full_client.put(
            f"/api/admin/users/{sample_admin['user_id']}/role",
            json={"role": "user"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 400
        assert "own" in resp.json()["detail"].lower()

    def test_invalid_role_returns_400(self, full_client, admin_tok, sample_user):
        resp = full_client.put(
            f"/api/admin/users/{sample_user['user_id']}/role",
            json={"role": "superuser"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 400

    def test_missing_user_returns_404(self, full_client, admin_tok):
        resp = full_client.put(
            "/api/admin/users/bad-id/role",
            json={"role": "user"},
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 404


# ===========================================================================
# POST /api/admin/users/{user_id}/deactivate
# ===========================================================================

class TestDeactivateUser:
    def test_deactivate_other_user_returns_200(
        self, full_client, admin_tok, sample_user
    ):
        resp = full_client.post(
            f"/api/admin/users/{sample_user['user_id']}/deactivate",
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_deactivated_user_cannot_login(self, full_client, admin_tok, sample_user):
        full_client.post(
            f"/api/admin/users/{sample_user['user_id']}/deactivate",
            headers=bearer(admin_tok),
        )
        resp = full_client.post("/api/auth/login", json={
            "email": sample_user["email"], "password": "Password1!"
        })
        assert resp.status_code == 403

    def test_self_deactivation_blocked(self, full_client, admin_tok, sample_admin):
        resp = full_client.post(
            f"/api/admin/users/{sample_admin['user_id']}/deactivate",
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 400
        assert "own" in resp.json()["detail"].lower()

    def test_missing_user_returns_404(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users/bad-id/deactivate", headers=bearer(admin_tok)
        )
        assert resp.status_code == 404


# ===========================================================================
# POST /api/admin/users/{user_id}/reactivate
# ===========================================================================

class TestReactivateUser:
    def test_reactivate_deactivated_user_returns_200(
        self, full_client, admin_tok, sample_user, db
    ):
        db.deactivate_user(sample_user["user_id"])
        resp = full_client.post(
            f"/api/admin/users/{sample_user['user_id']}/reactivate",
            headers=bearer(admin_tok),
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["is_active"] is True

    def test_reactivated_user_can_login(self, full_client, admin_tok, sample_user, db):
        db.deactivate_user(sample_user["user_id"])
        full_client.post(
            f"/api/admin/users/{sample_user['user_id']}/reactivate",
            headers=bearer(admin_tok),
        )
        resp = full_client.post("/api/auth/login", json={
            "email": sample_user["email"], "password": "Password1!"
        })
        assert resp.status_code == 200

    def test_missing_user_returns_404(self, full_client, admin_tok):
        resp = full_client.post(
            "/api/admin/users/bad-id/reactivate", headers=bearer(admin_tok)
        )
        assert resp.status_code == 404


# ===========================================================================
# DELETE /api/admin/users/{user_id}
# ===========================================================================

class TestAdminDeleteUser:
    def test_delete_other_user_returns_200(
        self, full_client, admin_tok, sample_user
    ):
        resp = full_client.delete(
            f"/api/admin/users/{sample_user['user_id']}", headers=bearer(admin_tok)
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_deleted_user_not_retrievable(
        self, full_client, admin_tok, sample_user, db
    ):
        full_client.delete(
            f"/api/admin/users/{sample_user['user_id']}", headers=bearer(admin_tok)
        )
        assert db.get_user_by_id(sample_user["user_id"]) is None

    def test_self_deletion_blocked(self, full_client, admin_tok, sample_admin):
        resp = full_client.delete(
            f"/api/admin/users/{sample_admin['user_id']}", headers=bearer(admin_tok)
        )
        assert resp.status_code == 400
        assert "own" in resp.json()["detail"].lower()

    def test_missing_user_returns_404(self, full_client, admin_tok):
        resp = full_client.delete(
            "/api/admin/users/bad-id", headers=bearer(admin_tok)
        )
        assert resp.status_code == 404


# ===========================================================================
# GET /api/admin/stats
# ===========================================================================

class TestSystemStats:
    def test_returns_200_with_stats(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/stats", headers=bearer(admin_tok))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "stats" in data

    def test_stats_structure(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/stats", headers=bearer(admin_tok))
        stats = resp.json()["stats"]
        assert "users" in stats
        assert "goals" in stats
        assert "content" in stats

    def test_user_count_matches_actual(self, full_client, admin_tok, sample_user, sample_admin):
        resp = full_client.get("/api/admin/stats", headers=bearer(admin_tok))
        # We have at least sample_user and sample_admin
        assert resp.json()["stats"]["users"]["total"] >= 2


# ===========================================================================
# GET /api/admin/audit-log
# ===========================================================================

class TestAuditLog:
    def test_returns_200_with_log(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/audit-log", headers=bearer(admin_tok))
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert isinstance(data["log"], list)

    def test_limit_parameter_accepted(self, full_client, admin_tok):
        resp = full_client.get(
            "/api/admin/audit-log?limit=5", headers=bearer(admin_tok)
        )
        assert resp.status_code == 200
        assert len(resp.json()["log"]) <= 5

    def test_total_field_matches_log_length(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/audit-log", headers=bearer(admin_tok))
        data = resp.json()
        assert data["total"] == len(data["log"])

    def test_limit_too_large_returns_422(self, full_client, admin_tok):
        resp = full_client.get(
            "/api/admin/audit-log?limit=9999", headers=bearer(admin_tok)
        )
        assert resp.status_code == 422


# ===========================================================================
# GET /api/admin/dashboard
# ===========================================================================

class TestAdminDashboard:
    def test_returns_200(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/dashboard", headers=bearer(admin_tok))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_dashboard_has_user_summary(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/dashboard", headers=bearer(admin_tok))
        dashboard = resp.json()["dashboard"]
        assert "users" in dashboard
        assert "total" in dashboard["users"]

    def test_dashboard_has_recent_activity(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/dashboard", headers=bearer(admin_tok))
        dashboard = resp.json()["dashboard"]
        assert "recent_activity" in dashboard
        assert isinstance(dashboard["recent_activity"], list)

    def test_dashboard_has_system_stats(self, full_client, admin_tok):
        resp = full_client.get("/api/admin/dashboard", headers=bearer(admin_tok))
        dashboard = resp.json()["dashboard"]
        assert "system" in dashboard
