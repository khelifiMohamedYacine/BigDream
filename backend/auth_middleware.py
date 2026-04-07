import jwt
import os
from datetime import datetime, timedelta
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "bigdream-os-secret-key-change-in-production")
ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 24


class AuthMiddleware:
    def __init__(self, db_manager):
        self.db_manager = db_manager
        self.security = HTTPBearer()

    def generate_token(self, user_id: str, email: str, role: str) -> str:
        payload = {
            "user_id": user_id,
            "email": email,
            "role": role,
            "exp": datetime.utcnow() + timedelta(hours=TOKEN_EXPIRY_HOURS),
            "iat": datetime.utcnow()
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    def verify_token(self, token: str) -> dict:
        try:
            if self.db_manager.is_token_blacklisted(token):
                raise HTTPException(status_code=401, detail="Token has been revoked")

            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(status_code=401, detail="Invalid token")

    def require_user(self):
        async def dependency(credentials: HTTPAuthorizationCredentials = Depends(self.security)):
            token = credentials.credentials
            payload = self.verify_token(token)

            user = self.db_manager.get_user_by_id(payload["user_id"])
            if not user:
                raise HTTPException(status_code=401, detail="User not found")
            if not user.get("is_active", True):
                raise HTTPException(status_code=403, detail="Account is deactivated")

            return user

        return dependency

    def require_admin(self):
        async def dependency(credentials: HTTPAuthorizationCredentials = Depends(self.security)):
            token = credentials.credentials
            payload = self.verify_token(token)

            if payload.get("role") != "admin":
                raise HTTPException(status_code=403, detail="Admin access required")

            user = self.db_manager.get_user_by_id(payload["user_id"])
            if not user:
                raise HTTPException(status_code=401, detail="User not found")
            if not user.get("is_active", True):
                raise HTTPException(status_code=403, detail="Account is deactivated")

            return user

        return dependency
