"""
test_auth_middleware.py
=======================
Tests for AuthMiddleware — JWT generation, verification, and FastAPI
dependency factories (require_user, require_admin).

Covers:
  - Token payload contents and expiry window
  - Verification of valid, expired, tampered, and blacklisted tokens
  - require_user dependency: success, missing user, deactivated user
  - require_admin dependency: admin success, non-admin blocked
"""
import time
import pytest
import jwt
from datetime import datetime, timedelta, timezone
from fastapi import FastAPI, Depends, HTTPException
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch

from backend.auth_middleware import AuthMiddleware, SECRET_KEY, ALGORITHM, TOKEN_EXPIRY_HOURS
from backend.database_manager import DatabaseManager


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

class TestGenerateToken:
    def test_returns_non_empty_string(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], sample_user["role"]
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_payload_contains_user_id(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], sample_user["role"]
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["user_id"] == sample_user["user_id"]

    def test_payload_contains_email(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], sample_user["role"]
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["email"] == sample_user["email"]

    def test_payload_contains_role(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "admin"
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"

    def test_token_expires_in_about_24h(self, auth, sample_user):
        before = datetime.utcnow()
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], sample_user["role"]
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        exp = datetime.utcfromtimestamp(payload["exp"])
        delta = exp - before
        # Should be close to TOKEN_EXPIRY_HOURS (allow ±2 min slop)
        assert abs(delta.total_seconds() - TOKEN_EXPIRY_HOURS * 3600) < 120

    def test_two_calls_produce_different_tokens(self, auth, sample_user):
        t1 = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        time.sleep(0.01)  # ensure iat differs
        t2 = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        assert t1 != t2

    def test_iat_field_present(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert "iat" in payload

    def test_admin_token_role_is_admin(self, auth, sample_admin):
        token = auth.generate_token(
            sample_admin["user_id"], sample_admin["email"], sample_admin["role"]
        )
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

class TestVerifyToken:
    def test_valid_token_returns_payload(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        payload = auth.verify_token(token)
        assert payload["user_id"] == sample_user["user_id"]

    def test_expired_token_raises_401(self, auth, sample_user):
        # Create token with -1h expiry
        payload = {
            "user_id": sample_user["user_id"],
            "email": sample_user["email"],
            "role": "user",
            "exp": datetime.utcnow() - timedelta(hours=1),
            "iat": datetime.utcnow() - timedelta(hours=2),
        }
        expired_token = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc:
            auth.verify_token(expired_token)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

    def test_tampered_token_raises_401(self, auth):
        with pytest.raises(HTTPException) as exc:
            auth.verify_token("not.a.valid.token")
        assert exc.value.status_code == 401

    def test_wrong_secret_raises_401(self, auth, sample_user):
        token = jwt.encode(
            {"user_id": "x", "email": "x@x.com", "role": "user",
             "exp": datetime.utcnow() + timedelta(hours=1)},
            "WRONG_SECRET",
            algorithm=ALGORITHM,
        )
        with pytest.raises(HTTPException) as exc:
            auth.verify_token(token)
        assert exc.value.status_code == 401

    def test_blacklisted_token_raises_401(self, auth, db, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        db.blacklist_token(token)
        with pytest.raises(HTTPException) as exc:
            auth.verify_token(token)
        assert exc.value.status_code == 401
        assert "revoked" in exc.value.detail.lower()

    def test_empty_string_raises_401(self, auth):
        with pytest.raises(HTTPException) as exc:
            auth.verify_token("")
        assert exc.value.status_code == 401

    def test_payload_roundtrip_preserves_all_fields(self, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        payload = auth.verify_token(token)
        assert payload["user_id"] == sample_user["user_id"]
        assert payload["email"] == sample_user["email"]
        assert payload["role"] == "user"


# ---------------------------------------------------------------------------
# require_user dependency
# ---------------------------------------------------------------------------

class TestRequireUser:
    """Build a tiny FastAPI app and exercise require_user via TestClient."""

    @pytest.fixture
    def protected_client(self, db, auth):
        app = FastAPI()

        @app.get("/protected")
        async def endpoint(user=Depends(auth.require_user())):
            return {"user_id": user["user_id"]}

        return TestClient(app, raise_server_exceptions=False)

    def test_valid_token_grants_access(self, protected_client, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        resp = protected_client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200
        assert resp.json()["user_id"] == sample_user["user_id"]

    def test_no_token_returns_403(self, protected_client):
        resp = protected_client.get("/protected")
        assert resp.status_code in (401, 403, 422)

    def test_invalid_token_returns_401(self, protected_client):
        resp = protected_client.get(
            "/protected", headers={"Authorization": "Bearer garbage.token.here"}
        )
        assert resp.status_code == 401

    def test_deactivated_user_returns_403(self, protected_client, db, auth, sample_user):
        db.deactivate_user(sample_user["user_id"])
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        resp = protected_client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403

    def test_deleted_user_returns_401(self, protected_client, db, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        db.delete_user(sample_user["user_id"])
        resp = protected_client.get(
            "/protected", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------

class TestRequireAdmin:
    """Build a tiny FastAPI app and exercise require_admin via TestClient."""

    @pytest.fixture
    def admin_protected_client(self, db, auth):
        app = FastAPI()

        @app.get("/admin-only")
        async def endpoint(user=Depends(auth.require_admin())):
            return {"role": user["role"]}

        return TestClient(app, raise_server_exceptions=False)

    def test_admin_token_grants_access(self, admin_protected_client, auth, sample_admin):
        token = auth.generate_token(
            sample_admin["user_id"], sample_admin["email"], "admin"
        )
        resp = admin_protected_client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200

    def test_regular_user_token_returns_403(self, admin_protected_client, auth, sample_user):
        token = auth.generate_token(
            sample_user["user_id"], sample_user["email"], "user"
        )
        resp = admin_protected_client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403
        assert "admin" in resp.json()["detail"].lower()

    def test_no_token_returns_4xx(self, admin_protected_client):
        resp = admin_protected_client.get("/admin-only")
        assert resp.status_code in (401, 403, 422)

    def test_deactivated_admin_returns_403(
        self, admin_protected_client, db, auth, sample_admin
    ):
        db.deactivate_user(sample_admin["user_id"])
        token = auth.generate_token(
            sample_admin["user_id"], sample_admin["email"], "admin"
        )
        resp = admin_protected_client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 403

    def test_deleted_admin_returns_401(
        self, admin_protected_client, db, auth, sample_admin
    ):
        token = auth.generate_token(
            sample_admin["user_id"], sample_admin["email"], "admin"
        )
        db.delete_user(sample_admin["user_id"])
        resp = admin_protected_client.get(
            "/admin-only", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401
