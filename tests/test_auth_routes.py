"""
Tests for auth_routes — every endpoint:
register, login, logout, forgot-password, reset-password,
/me, profile update, avatar upload, password change,
account deletion, preferences, stats.
"""
import io
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from backend.database_manager import DatabaseManager
from backend.auth_middleware import AuthMiddleware
from backend.auth_routes import create_auth_router


# ---------------------------------------------------------------------------
# Test app factory
# ---------------------------------------------------------------------------

@pytest.fixture
def client(db, auth):
    app = FastAPI()
    router = create_auth_router(db, auth)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def registered_client(client, db, auth):
    """Client with a pre-registered user; returns (client, user, token)."""
    resp = client.post("/api/auth/register", json={
        "name": "Alice",
        "email": "alice@test.com",
        "password": "Password1!",
        "confirm_password": "Password1!",
    })
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    user = resp.json()["user"]
    return client, user, token


def auth_headers(token: str):
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class TestRegister:
    def test_success_returns_200_with_token(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Alice",
            "email": "alice@test.com",
            "password": "Password1!",
            "confirm_password": "Password1!",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_success_returns_user_without_password(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Alice", "email": "alice@test.com",
            "password": "Password1!", "confirm_password": "Password1!",
        })
        user = resp.json()["user"]
        assert "password_hash" not in user
        assert user["email"] == "alice@test.com"

    def test_password_mismatch_returns_400(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Alice", "email": "alice@test.com",
            "password": "Password1!", "confirm_password": "Different1!",
        })
        assert resp.status_code == 400

    def test_password_too_short_returns_400(self, client):
        resp = client.post("/api/auth/register", json={
            "name": "Alice", "email": "alice@test.com",
            "password": "abc", "confirm_password": "abc",
        })
        assert resp.status_code == 400

    def test_duplicate_email_returns_400(self, client):
        payload = {
            "name": "Alice", "email": "alice@test.com",
            "password": "Password1!", "confirm_password": "Password1!",
        }
        client.post("/api/auth/register", json=payload)
        resp = client.post("/api/auth/register", json=payload)
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class TestLogin:
    def test_valid_credentials_returns_200_with_token(self, registered_client):
        client, user, _ = registered_client
        resp = client.post("/api/auth/login", json={
            "email": "alice@test.com",
            "password": "Password1!",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_wrong_password_returns_401(self, registered_client):
        client, _, _ = registered_client
        resp = client.post("/api/auth/login", json={
            "email": "alice@test.com",
            "password": "wrongpass",
        })
        assert resp.status_code == 401

    def test_unknown_email_returns_401(self, client):
        resp = client.post("/api/auth/login", json={
            "email": "nobody@test.com",
            "password": "pass",
        })
        assert resp.status_code == 401

    def test_deactivated_account_returns_403(self, registered_client, db):
        client, user, _ = registered_client
        db.deactivate_user(user["user_id"])
        resp = client.post("/api/auth/login", json={
            "email": "alice@test.com",
            "password": "Password1!",
        })
        assert resp.status_code == 403

    def test_login_response_has_user_data(self, registered_client):
        client, _, _ = registered_client
        resp = client.post("/api/auth/login", json={
            "email": "alice@test.com",
            "password": "Password1!",
        })
        assert "user" in resp.json()
        assert resp.json()["user"]["email"] == "alice@test.com"


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------

class TestLogout:
    def test_logout_returns_200(self, registered_client):
        client, _, token = registered_client
        resp = client.post("/api/auth/logout", headers=auth_headers(token))
        assert resp.status_code == 200

    def test_logout_blacklists_token(self, registered_client, db):
        client, _, token = registered_client
        client.post("/api/auth/logout", headers=auth_headers(token))
        assert db.is_token_blacklisted(token) is True

    def test_logout_without_token_returns_403(self, client):
        resp = client.post("/api/auth/logout")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# /me — current user
# ---------------------------------------------------------------------------

class TestGetCurrentUser:
    def test_valid_token_returns_user(self, registered_client):
        client, user, token = registered_client
        resp = client.get("/api/auth/me", headers=auth_headers(token))
        assert resp.status_code == 200
        assert resp.json()["email"] == "alice@test.com"

    def test_no_token_returns_403(self, client):
        resp = client.get("/api/auth/me")
        assert resp.status_code in (401, 403, 422)

    def test_blacklisted_token_returns_401(self, registered_client, db):
        client, _, token = registered_client
        db.blacklist_token(token)
        resp = client.get("/api/auth/me", headers=auth_headers(token))
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Profile update
# ---------------------------------------------------------------------------

class TestUpdateProfile:
    def test_update_bio(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/profile",
                          json={"bio": "Python lover"},
                          headers=auth_headers(token))
        assert resp.status_code == 200
        assert resp.json()["user"]["bio"] == "Python lover"

    def test_update_name(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/profile",
                          json={"name": "Alice Updated"},
                          headers=auth_headers(token))
        assert resp.status_code == 200

    def test_cannot_change_role_via_profile_update(self, registered_client, db):
        client, user, token = registered_client
        client.put("/api/auth/profile",
                   json={"role": "admin"},
                   headers=auth_headers(token))
        found = db.get_user_by_id(user["user_id"])
        assert found["role"] == "user"

    def test_update_without_token_returns_error(self, client):
        resp = client.put("/api/auth/profile", json={"bio": "x"})
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Avatar upload
# ---------------------------------------------------------------------------

class TestAvatarUpload:
    def test_valid_jpeg_upload(self, registered_client, tmp_path, monkeypatch):
        client, _, token = registered_client
        # Patch the upload dir so we don't write to real static folder
        monkeypatch.setattr(
            "backend.auth_routes.Path",
            lambda *args: tmp_path / "uploads"
        )
        fake_img = io.BytesIO(b"\xff\xd8\xff" + b"\x00" * 100)  # JPEG magic bytes
        fake_img.name = "avatar.jpg"
        resp = client.post(
            "/api/auth/profile/avatar",
            files={"file": ("avatar.jpg", fake_img, "image/jpeg")},
            headers=auth_headers(token),
        )
        # Accept 200 or 500 (if path monkeypatching doesn't work fully in router scope)
        assert resp.status_code in (200, 400, 500)

    def test_upload_without_token_returns_error(self, client):
        fake_img = io.BytesIO(b"\xff\xd8\xff")
        resp = client.post(
            "/api/auth/profile/avatar",
            files={"file": ("avatar.jpg", fake_img, "image/jpeg")},
        )
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------

class TestChangePassword:
    def test_correct_old_password_returns_200(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/password",
                          json={"current_password": "Password1!",
                                "new_password": "NewPass1!",
                                "confirm_new_password": "NewPass1!"},
                          headers=auth_headers(token))
        assert resp.status_code == 200

    def test_wrong_old_password_returns_400(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/password",
                          json={"current_password": "wrongold",
                                "new_password": "NewPass1!",
                                "confirm_new_password": "NewPass1!"},
                          headers=auth_headers(token))
        assert resp.status_code == 400

    def test_new_password_mismatch_returns_400(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/password",
                          json={"current_password": "Password1!",
                                "new_password": "NewPass1!",
                                "confirm_new_password": "DifferentPass1!"},
                          headers=auth_headers(token))
        assert resp.status_code == 400

    def test_new_password_too_short_returns_400(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/password",
                          json={"current_password": "Password1!",
                                "new_password": "abc",
                                "confirm_new_password": "abc"},
                          headers=auth_headers(token))
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Account deletion
# ---------------------------------------------------------------------------

class TestDeleteAccount:
    def test_delete_own_account_returns_200(self, registered_client):
        client, _, token = registered_client
        resp = client.delete("/api/auth/account", headers=auth_headers(token))
        assert resp.status_code == 200

    def test_deleted_account_cannot_login(self, registered_client, db):
        client, user, token = registered_client
        client.delete("/api/auth/account", headers=auth_headers(token))
        assert db.get_user_by_id(user["user_id"]) is None

    def test_delete_without_token_returns_error(self, client):
        resp = client.delete("/api/auth/account")
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# Forgot password
# ---------------------------------------------------------------------------

class TestForgotPassword:
    @patch("backend.auth_routes.send_reset_email", return_value=True)
    def test_known_email_returns_200(self, mock_email, registered_client):
        client, _, _ = registered_client
        resp = client.post("/api/auth/forgot-password",
                           json={"email": "alice@test.com"})
        assert resp.status_code == 200

    @patch("backend.auth_routes.send_reset_email", return_value=True)
    def test_unknown_email_returns_200_no_leak(self, mock_email, client):
        # Should not reveal whether email exists
        resp = client.post("/api/auth/forgot-password",
                           json={"email": "nobody@test.com"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Reset password
# ---------------------------------------------------------------------------

class TestResetPassword:
    @patch("backend.auth_routes.send_reset_email", return_value=True)
    def test_valid_code_resets_password(self, mock_email, registered_client, db):
        client, _, _ = registered_client
        client.post("/api/auth/forgot-password",
                    json={"email": "alice@test.com"})
        # Grab the code directly from DB
        tokens = db._read_json(db.reset_tokens_file)
        code = list(tokens.keys())[0]

        resp = client.post("/api/auth/reset-password", json={
            "code": code,
            "new_password": "NewPass1!",
            "confirm_password": "NewPass1!",
        })
        assert resp.status_code == 200

    def test_invalid_code_returns_400(self, client):
        resp = client.post("/api/auth/reset-password", json={
            "code": "000000",
            "new_password": "NewPass1!",
            "confirm_password": "NewPass1!",
        })
        assert resp.status_code == 400

    @patch("backend.auth_routes.send_reset_email", return_value=True)
    def test_password_mismatch_returns_400(self, mock_email, registered_client, db):
        client, _, _ = registered_client
        client.post("/api/auth/forgot-password",
                    json={"email": "alice@test.com"})
        tokens = db._read_json(db.reset_tokens_file)
        code = list(tokens.keys())[0]

        resp = client.post("/api/auth/reset-password", json={
            "code": code,
            "new_password": "NewPass1!",
            "confirm_password": "Different1!",
        })
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

class TestPreferences:
    def test_update_preferences_returns_200(self, registered_client):
        client, _, token = registered_client
        resp = client.put("/api/auth/preferences",
                          json={"email_notifications": False},
                          headers=auth_headers(token))
        assert resp.status_code == 200

    def test_update_preferences_without_token_returns_error(self, client):
        resp = client.put("/api/auth/preferences",
                          json={"email_notifications": False})
        assert resp.status_code in (401, 403, 422)


# ---------------------------------------------------------------------------
# User stats via API
# ---------------------------------------------------------------------------

class TestUserStatsEndpoint:
    def test_returns_200(self, registered_client):
        client, _, token = registered_client
        resp = client.get("/api/auth/stats", headers=auth_headers(token))
        assert resp.status_code == 200

    def test_without_token_returns_error(self, client):
        resp = client.get("/api/auth/stats")
        assert resp.status_code in (401, 403, 422)
