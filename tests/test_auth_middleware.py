"""
Tests for AuthMiddleware — JWT generation, verification, blacklist integration,
and the require_user / require_admin dependency factories.
"""
import time
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import jwt as pyjwt
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from backend.auth_middleware import AuthMiddleware, SECRET_KEY, ALGORITHM


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.is_token_blacklisted.return_value = False
    db.get_user_by_id.return_value = {"user_id": "u1", "role": "user", "is_active": True}
    return db


@pytest.fixture
def auth(mock_db):
    return AuthMiddleware(mock_db)


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------

class TestGenerateToken:
    def test_returns_string(self, auth):
        tok = auth.generate_token("u1", "a@test.com", "user")
        assert isinstance(tok, str)

    def test_token_contains_user_id(self, auth):
        tok = auth.generate_token("u1", "a@test.com", "user")
        payload = pyjwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["user_id"] == "u1"

    def test_token_contains_email(self, auth):
        tok = auth.generate_token("u1", "a@test.com", "user")
        payload = pyjwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["email"] == "a@test.com"

    def test_token_contains_role(self, auth):
        tok = auth.generate_token("u1", "a@test.com", "admin")
        payload = pyjwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
        assert payload["role"] == "admin"

    def test_token_has_expiry(self, auth):
        tok = auth.generate_token("u1", "a@test.com", "user")
        payload = pyjwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
        assert "exp" in payload

    def test_token_expiry_is_24h_from_now(self, auth):
        before = datetime.utcnow()
        tok = auth.generate_token("u1", "a@test.com", "user")
        after = datetime.utcnow()
        payload = pyjwt.decode(tok, SECRET_KEY, algorithms=[ALGORITHM])
        exp = datetime.utcfromtimestamp(payload["exp"])
        assert timedelta(hours=23, minutes=59) < (exp - before) < timedelta(hours=24, minutes=1)

    def test_different_users_different_tokens(self, auth):
        t1 = auth.generate_token("u1", "a@test.com", "user")
        t2 = auth.generate_token("u2", "b@test.com", "user")
        assert t1 != t2


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------

class TestVerifyToken:
    def test_valid_token_returns_payload(self, auth):
        tok = auth.generate_token("u1", "a@test.com", "user")
        payload = auth.verify_token(tok)
        assert payload["user_id"] == "u1"

    def test_expired_token_raises_401(self, auth):
        payload = {
            "user_id": "u1",
            "email": "a@test.com",
            "role": "user",
            "exp": datetime.utcnow() - timedelta(seconds=1),
            "iat": datetime.utcnow() - timedelta(hours=25),
        }
        expired_tok = pyjwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            auth.verify_token(expired_tok)
        assert exc_info.value.status_code == 401

    def test_invalid_signature_raises_401(self, auth):
        tok = pyjwt.encode({"user_id": "u1", "exp": datetime.utcnow() + timedelta(hours=1)},
                           "wrong-secret", algorithm=ALGORITHM)
        with pytest.raises(HTTPException) as exc_info:
            auth.verify_token(tok)
        assert exc_info.value.status_code == 401

    def test_blacklisted_token_raises_401(self, mock_db, auth):
        mock_db.is_token_blacklisted.return_value = True
        tok = auth.generate_token("u1", "a@test.com", "user")
        with pytest.raises(HTTPException) as exc_info:
            auth.verify_token(tok)
        assert exc_info.value.status_code == 401

    def test_malformed_token_raises_401(self, auth):
        with pytest.raises(HTTPException) as exc_info:
            auth.verify_token("not.a.token")
        assert exc_info.value.status_code == 401

    def test_blacklist_is_checked(self, mock_db, auth):
        tok = auth.generate_token("u1", "a@test.com", "user")
        auth.verify_token(tok)
        mock_db.is_token_blacklisted.assert_called_once_with(tok)


# ---------------------------------------------------------------------------
# require_user dependency
# ---------------------------------------------------------------------------

class TestRequireUser:
    @pytest.mark.asyncio
    async def test_valid_token_returns_user(self, auth, mock_db):
        tok = auth.generate_token("u1", "a@test.com", "user")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        dep = auth.require_user()
        user = await dep(credentials=creds)
        assert user["user_id"] == "u1"

    @pytest.mark.asyncio
    async def test_nonexistent_user_raises_401(self, auth, mock_db):
        mock_db.get_user_by_id.return_value = None
        tok = auth.generate_token("u1", "a@test.com", "user")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        dep = auth.require_user()
        with pytest.raises(HTTPException) as exc_info:
            await dep(credentials=creds)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_deactivated_user_raises_403(self, auth, mock_db):
        mock_db.get_user_by_id.return_value = {
            "user_id": "u1", "role": "user", "is_active": False
        }
        tok = auth.generate_token("u1", "a@test.com", "user")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        dep = auth.require_user()
        with pytest.raises(HTTPException) as exc_info:
            await dep(credentials=creds)
        assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# require_admin dependency
# ---------------------------------------------------------------------------

class TestRequireAdmin:
    @pytest.mark.asyncio
    async def test_admin_token_passes(self, auth, mock_db):
        mock_db.get_user_by_id.return_value = {
            "user_id": "u1", "role": "admin", "is_active": True
        }
        tok = auth.generate_token("u1", "a@test.com", "admin")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        dep = auth.require_admin()
        user = await dep(credentials=creds)
        assert user["role"] == "admin"

    @pytest.mark.asyncio
    async def test_user_token_raises_403(self, auth, mock_db):
        mock_db.get_user_by_id.return_value = {
            "user_id": "u1", "role": "user", "is_active": True
        }
        tok = auth.generate_token("u1", "a@test.com", "user")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        dep = auth.require_admin()
        with pytest.raises(HTTPException) as exc_info:
            await dep(credentials=creds)
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_nonexistent_admin_raises_401(self, auth, mock_db):
        mock_db.get_user_by_id.return_value = None
        tok = auth.generate_token("u1", "a@test.com", "admin")
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        dep = auth.require_admin()
        with pytest.raises(HTTPException) as exc_info:
            await dep(credentials=creds)
        assert exc_info.value.status_code == 401
