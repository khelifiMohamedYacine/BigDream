"""
test_auth_routes.py
===================
Integration tests for all auth_routes endpoints.

Endpoints covered:
  POST /api/auth/register
  POST /api/auth/login
  POST /api/auth/logout
  GET  /api/auth/me
  POST /api/auth/forgot-password
  POST /api/auth/reset-password
  PUT  /api/auth/profile
  POST /api/auth/profile/avatar
  PUT  /api/auth/password
  DELETE /api/auth/account
  PUT  /api/auth/preferences
  GET  /api/auth/stats

All external calls (email) are mocked.
"""
import io
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch


def _reg_payload(**overrides):
    base = {
        "name": "Alice",
        "email": "alice@example.com",
        "password": "Password1!",
        "confirm_password": "Password1!",
    }
    base.update(overrides)
    return base


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ===========================================================================
# Registration
# ===========================================================================

class TestRegister:
    def test_success_returns_200_with_token_and_user(self, auth_client):
        resp = auth_client.post("/api/auth/register", json=_reg_payload())
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert "access_token" in data
        assert "user" in data

    def test_user_in_response_has_no_password_hash(self, auth_client):
        resp = auth_client.post("/api/auth/register", json=_reg_payload())
        assert "password_hash" not in resp.json()["user"]

    def test_token_type_is_bearer(self, auth_client):
        resp = auth_client.post("/api/auth/register", json=_reg_payload())
        assert resp.json()["token_type"] == "bearer"

    def test_email_stored_as_lowercase(self, auth_client):
        resp = auth_client.post(
            "/api/auth/register", json=_reg_payload(email="ALICE@EXAMPLE.COM")
        )
        assert resp.json()["user"]["email"] == "alice@example.com"

    def test_duplicate_email_returns_400(self, auth_client):
        auth_client.post("/api/auth/register", json=_reg_payload())
        resp = auth_client.post("/api/auth/register", json=_reg_payload())
        assert resp.status_code == 400
        assert "registered" in resp.json()["detail"].lower()

    def test_password_mismatch_returns_400(self, auth_client):
        resp = auth_client.post(
            "/api/auth/register",
            json=_reg_payload(confirm_password="DifferentPass!")
        )
        assert resp.status_code == 400
        assert "match" in resp.json()["detail"].lower()

    def test_password_too_short_returns_400(self, auth_client):
        resp = auth_client.post(
            "/api/auth/register",
            json=_reg_payload(password="abc", confirm_password="abc")
        )
        assert resp.status_code == 400
        assert "6" in resp.json()["detail"]

    def test_invalid_email_format_returns_422(self, auth_client):
        resp = auth_client.post(
            "/api/auth/register",
            json=_reg_payload(email="not-an-email")
        )
        assert resp.status_code == 422

    def test_missing_name_returns_422(self, auth_client):
        payload = _reg_payload()
        del payload["name"]
        resp = auth_client.post("/api/auth/register", json=payload)
        assert resp.status_code == 422

    def test_missing_password_returns_422(self, auth_client):
        payload = _reg_payload()
        del payload["password"]
        resp = auth_client.post("/api/auth/register", json=payload)
        assert resp.status_code == 422

    def test_empty_body_returns_422(self, auth_client):
        resp = auth_client.post("/api/auth/register", json={})
        assert resp.status_code == 422


# ===========================================================================
# Login
# ===========================================================================

class TestLogin:
    def test_success_returns_200_with_token(self, auth_client_with_user):
        client, user, _ = auth_client_with_user
        resp = client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "Password1!"
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    def test_wrong_password_returns_401(self, auth_client_with_user):
        client, _, _ = auth_client_with_user
        resp = client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "WrongPass!"
        })
        assert resp.status_code == 401

    def test_unknown_email_returns_401(self, auth_client):
        resp = auth_client.post("/api/auth/login", json={
            "email": "nobody@example.com", "password": "pass"
        })
        assert resp.status_code == 401

    def test_deactivated_account_returns_403(self, auth_client, db, auth):
        resp = auth_client.post("/api/auth/register", json=_reg_payload())
        user_id = resp.json()["user"]["user_id"]
        db.deactivate_user(user_id)
        resp2 = auth_client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "Password1!"
        })
        assert resp2.status_code == 403

    def test_invalid_email_format_returns_422(self, auth_client):
        resp = auth_client.post("/api/auth/login", json={
            "email": "not-email", "password": "pass"
        })
        assert resp.status_code == 422

    def test_missing_email_returns_422(self, auth_client):
        resp = auth_client.post("/api/auth/login", json={"password": "pass"})
        assert resp.status_code == 422

    def test_user_in_response_no_password_hash(self, auth_client_with_user):
        client, _, _ = auth_client_with_user
        resp = client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "Password1!"
        })
        assert "password_hash" not in resp.json()["user"]


# ===========================================================================
# Logout
# ===========================================================================

class TestLogout:
    def test_logout_returns_200(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.post("/api/auth/logout", headers=bearer(token))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_token_blacklisted_after_logout(self, auth_client_with_user, db):
        client, _, token = auth_client_with_user
        client.post("/api/auth/logout", headers=bearer(token))
        assert db.is_token_blacklisted(token)

    def test_cannot_use_me_after_logout(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        client.post("/api/auth/logout", headers=bearer(token))
        resp = client.get("/api/auth/me", headers=bearer(token))
        assert resp.status_code == 401

    def test_logout_without_token_returns_403(self, auth_client):
        resp = auth_client.post("/api/auth/logout")
        assert resp.status_code == 403


# ===========================================================================
# GET /me
# ===========================================================================

class TestGetMe:
    def test_returns_200_with_user(self, auth_client_with_user):
        client, user, token = auth_client_with_user
        resp = client.get("/api/auth/me", headers=bearer(token))
        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == user["email"]

    def test_no_password_hash_in_response(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.get("/api/auth/me", headers=bearer(token))
        assert "password_hash" not in resp.json()["user"]

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.get("/api/auth/me")
        assert resp.status_code == 403

    def test_invalid_token_returns_401(self, auth_client):
        resp = auth_client.get(
            "/api/auth/me", headers={"Authorization": "Bearer bad.token.here"}
        )
        assert resp.status_code == 401


# ===========================================================================
# Forgot / Reset password
# ===========================================================================

class TestForgotPassword:
    def test_known_email_returns_200(self, auth_client_with_user):
        client, _, _ = auth_client_with_user
        with patch("backend.auth_routes.send_reset_email", return_value=True):
            resp = client.post("/api/auth/forgot-password", json={
                "email": "alice@example.com"
            })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_unknown_email_also_returns_200(self, auth_client):
        """Must not leak whether email exists."""
        with patch("backend.auth_routes.send_reset_email", return_value=True):
            resp = auth_client.post("/api/auth/forgot-password", json={
                "email": "nobody@example.com"
            })
        assert resp.status_code == 200

    def test_invalid_email_format_returns_422(self, auth_client):
        resp = auth_client.post("/api/auth/forgot-password", json={"email": "bad"})
        assert resp.status_code == 422


class TestResetPassword:
    def _get_code(self, db, email="alice@example.com"):
        code = db.create_reset_token(email)
        return code

    def test_valid_code_returns_200(self, auth_client_with_user, db):
        client, _, _ = auth_client_with_user
        code = self._get_code(db)
        resp = client.post("/api/auth/reset-password", json={
            "code": code,
            "new_password": "NewPassword1!",
            "confirm_password": "NewPassword1!",
        })
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_can_login_with_new_password(self, auth_client_with_user, db):
        client, _, _ = auth_client_with_user
        code = self._get_code(db)
        client.post("/api/auth/reset-password", json={
            "code": code,
            "new_password": "NewPassword1!",
            "confirm_password": "NewPassword1!",
        })
        resp = client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "NewPassword1!"
        })
        assert resp.status_code == 200

    def test_password_mismatch_returns_400(self, auth_client_with_user, db):
        client, _, _ = auth_client_with_user
        code = self._get_code(db)
        resp = client.post("/api/auth/reset-password", json={
            "code": code,
            "new_password": "AAA1!",
            "confirm_password": "BBB1!",
        })
        assert resp.status_code == 400

    def test_too_short_password_returns_400(self, auth_client_with_user, db):
        client, _, _ = auth_client_with_user
        code = self._get_code(db)
        resp = client.post("/api/auth/reset-password", json={
            "code": code,
            "new_password": "abc",
            "confirm_password": "abc",
        })
        assert resp.status_code == 400

    def test_invalid_code_returns_400(self, auth_client):
        resp = auth_client.post("/api/auth/reset-password", json={
            "code": "000000",
            "new_password": "NewPassword1!",
            "confirm_password": "NewPassword1!",
        })
        assert resp.status_code == 400
        assert "expired" in resp.json()["detail"].lower() or "invalid" in resp.json()["detail"].lower()

    def test_missing_code_returns_422(self, auth_client):
        resp = auth_client.post("/api/auth/reset-password", json={
            "new_password": "NewPassword1!",
            "confirm_password": "NewPassword1!",
        })
        assert resp.status_code == 422


# ===========================================================================
# Profile update
# ===========================================================================

class TestUpdateProfile:
    def test_update_name(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/profile",
            json={"name": "Alice Updated"},
            headers=bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["user"]["name"] == "Alice Updated"

    def test_update_bio(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/profile",
            json={"bio": "Python developer"},
            headers=bearer(token),
        )
        assert resp.status_code == 200

    def test_update_tagline(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/profile",
            json={"tagline": "Coding every day"},
            headers=bearer(token),
        )
        assert resp.status_code == 200

    def test_empty_body_returns_200_no_change(self, auth_client_with_user):
        """Partial update with no fields is fine — returns 200."""
        client, user, token = auth_client_with_user
        resp = client.put(
            "/api/auth/profile", json={}, headers=bearer(token)
        )
        assert resp.status_code == 200

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.put("/api/auth/profile", json={"name": "X"})
        assert resp.status_code == 403

    def test_response_has_no_password_hash(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/profile", json={"name": "New"}, headers=bearer(token)
        )
        assert "password_hash" not in resp.json()["user"]


# ===========================================================================
# Avatar upload
# ===========================================================================

class TestAvatarUpload:
    def test_valid_jpeg_accepted(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        file_bytes = b"\xff\xd8\xff" + b"\x00" * 100  # minimal JPEG header
        resp = client.post(
            "/api/auth/profile/avatar",
            files={"file": ("avatar.jpg", io.BytesIO(file_bytes), "image/jpeg")},
            headers=bearer(token),
        )
        assert resp.status_code == 200
        assert "avatar_url" in resp.json()

    def test_valid_png_accepted(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        file_bytes = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50
        resp = client.post(
            "/api/auth/profile/avatar",
            files={"file": ("avatar.png", io.BytesIO(file_bytes), "image/png")},
            headers=bearer(token),
        )
        assert resp.status_code == 200

    def test_invalid_file_type_returns_400(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.post(
            "/api/auth/profile/avatar",
            files={"file": ("doc.pdf", io.BytesIO(b"%PDF"), "application/pdf")},
            headers=bearer(token),
        )
        assert resp.status_code == 400
        assert "type" in resp.json()["detail"].lower()

    def test_file_too_large_returns_400(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        big_file = b"\xff\xd8\xff" + b"x" * (6 * 1024 * 1024)  # > 5MB
        resp = client.post(
            "/api/auth/profile/avatar",
            files={"file": ("big.jpg", io.BytesIO(big_file), "image/jpeg")},
            headers=bearer(token),
        )
        assert resp.status_code == 400
        assert "large" in resp.json()["detail"].lower()

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.post(
            "/api/auth/profile/avatar",
            files={"file": ("f.jpg", io.BytesIO(b"data"), "image/jpeg")},
        )
        assert resp.status_code == 403


# ===========================================================================
# Password change
# ===========================================================================

class TestChangePassword:
    def test_valid_change_returns_200(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/password",
            json={
                "current_password": "Password1!",
                "new_password": "NewPassword2!",
                "confirm_password": "NewPassword2!",
            },
            headers=bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_can_login_with_new_password(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        client.put(
            "/api/auth/password",
            json={
                "current_password": "Password1!",
                "new_password": "NewPassword2!",
                "confirm_password": "NewPassword2!",
            },
            headers=bearer(token),
        )
        resp = client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "NewPassword2!"
        })
        assert resp.status_code == 200

    def test_wrong_current_password_returns_400_or_500(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/password",
            json={
                "current_password": "WrongOld!",
                "new_password": "NewPassword2!",
                "confirm_password": "NewPassword2!",
            },
            headers=bearer(token),
        )
        assert resp.status_code in (400, 500)

    def test_new_passwords_mismatch_returns_400(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/password",
            json={
                "current_password": "Password1!",
                "new_password": "AAA2!",
                "confirm_password": "BBB2!",
            },
            headers=bearer(token),
        )
        assert resp.status_code == 400

    def test_new_password_too_short_returns_400(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/password",
            json={
                "current_password": "Password1!",
                "new_password": "abc",
                "confirm_password": "abc",
            },
            headers=bearer(token),
        )
        assert resp.status_code == 400

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.put(
            "/api/auth/password",
            json={
                "current_password": "X",
                "new_password": "NewPass1!",
                "confirm_password": "NewPass1!",
            },
        )
        assert resp.status_code == 403


# ===========================================================================
# Account deletion
# ===========================================================================

class TestDeleteAccount:
    def test_self_deletion_returns_200(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.delete("/api/auth/account", headers=bearer(token))
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_token_blacklisted_after_deletion(self, auth_client_with_user, db):
        client, _, token = auth_client_with_user
        client.delete("/api/auth/account", headers=bearer(token))
        assert db.is_token_blacklisted(token)

    def test_cannot_login_after_deletion(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        client.delete("/api/auth/account", headers=bearer(token))
        resp = client.post("/api/auth/login", json={
            "email": "alice@example.com", "password": "Password1!"
        })
        assert resp.status_code == 401

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.delete("/api/auth/account")
        assert resp.status_code == 403


# ===========================================================================
# Preferences
# ===========================================================================

class TestPreferences:
    def test_update_email_notifications(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/preferences",
            json={"email_notifications": False},
            headers=bearer(token),
        )
        assert resp.status_code == 200
        assert resp.json()["success"] is True

    def test_update_multiple_prefs(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/preferences",
            json={"weekly_summary": True, "content_updates": False},
            headers=bearer(token),
        )
        assert resp.status_code == 200

    def test_empty_body_allowed(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.put(
            "/api/auth/preferences", json={}, headers=bearer(token)
        )
        assert resp.status_code == 200

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.put(
            "/api/auth/preferences", json={"email_notifications": True}
        )
        assert resp.status_code == 403


# ===========================================================================
# User stats
# ===========================================================================

class TestUserStats:
    def test_returns_200_with_stats(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.get("/api/auth/stats", headers=bearer(token))
        assert resp.status_code == 200
        assert "stats" in resp.json()

    def test_stats_include_goals_created(self, auth_client_with_user):
        client, _, token = auth_client_with_user
        resp = client.get("/api/auth/stats", headers=bearer(token))
        stats = resp.json()["stats"]
        assert "goals_created" in stats

    def test_unauthenticated_returns_403(self, auth_client):
        resp = auth_client.get("/api/auth/stats")
        assert resp.status_code == 403
