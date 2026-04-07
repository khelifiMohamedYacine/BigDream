from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime
from pathlib import Path
import shutil
import uuid
from backend.email_service import send_reset_email


class RegisterRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    confirm_password: str

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class UpdateProfileRequest(BaseModel):
    name: Optional[str] = None
    bio: Optional[str] = None
    handle: Optional[str] = None
    tagline: Optional[str] = None

class UpdatePasswordRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str

class UpdatePreferencesRequest(BaseModel):
    email_notifications: Optional[bool] = None
    weekly_summary: Optional[bool] = None
    content_updates: Optional[bool] = None

class ForgotPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordRequest(BaseModel):
    code: str
    new_password: str
    confirm_password: str


def create_auth_router(db_manager, auth_middleware):
    router = APIRouter(prefix="/api/auth", tags=["authentication"])
    security = HTTPBearer()

    # Walk up from this file until we find the directory containing 'frontend/'
    _here = Path(__file__).resolve().parent
    while _here != _here.parent:
        if (_here / "frontend" / "static").is_dir():
            break
        _here = _here.parent
    UPLOAD_DIR = _here / "frontend" / "static" / "uploads" / "profiles"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


    @router.post("/register")
    async def register(request: RegisterRequest):
        try:
            if request.password != request.confirm_password:
                raise HTTPException(
                    status_code=400,
                    detail="Passwords do not match"
                )

            if len(request.password) < 6:
                raise HTTPException(
                    status_code=400,
                    detail="Password must be at least 6 characters"
                )

            try:
                user = db_manager.create_user(
                    name=request.name,
                    email=request.email,
                    password=request.password,
                    role="user"
                )
            except ValueError as e:
                if "already registered" in str(e):
                    raise HTTPException(
                        status_code=400,
                        detail="Email already registered"
                    )
                raise HTTPException(status_code=400, detail=str(e))

            token = auth_middleware.generate_token(
                user_id=user['user_id'],
                email=user['email'],
                role=user['role']
            )

            return {
                "success": True,
                "message": "Account created successfully",
                "access_token": token,
                "token_type": "bearer",
                "user": user
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail=f"Registration failed: {str(e)}"
            )


    @router.post("/login")
    async def login(request: LoginRequest):
        try:
            user = db_manager.authenticate_user(
                email=request.email,
                password=request.password
            )

            if not user:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid email or password"
                )

            token = auth_middleware.generate_token(
                user_id=user['user_id'],
                email=user['email'],
                role=user['role']
            )

            return {
                "success": True,
                "message": "Login successful",
                "access_token": token,
                "token_type": "bearer",
                "user": user
            }

        except HTTPException:
            raise
        except ValueError as e:
            if "deactivated" in str(e):
                raise HTTPException(
                    status_code=403,
                    detail="Account is deactivated. Contact administrator."
                )
            raise HTTPException(status_code=401, detail="Invalid credentials")
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Login failed"
            )


    @router.post("/forgot-password")
    async def forgot_password(request: ForgotPasswordRequest):
        """Request a password reset code — sends code by email."""
        try:
            code = db_manager.create_reset_token(request.email)

            if code:
                send_reset_email(to_email=request.email, code=code)

            # Always return the same response to avoid leaking whether the email exists
            return {
                "success": True,
                "message": "If an account with that email exists, a reset code has been sent to your inbox."
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Password reset request failed"
            )


    @router.post("/reset-password")
    async def reset_password(request: ResetPasswordRequest):
        try:
            if request.new_password != request.confirm_password:
                raise HTTPException(
                    status_code=400,
                    detail="Passwords do not match"
                )

            if len(request.new_password) < 6:
                raise HTTPException(
                    status_code=400,
                    detail="Password must be at least 6 characters"
                )

            success = db_manager.reset_password_with_token(
                code=request.code,
                new_password=request.new_password
            )

            if not success:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid or expired reset code"
                )

            return {
                "success": True,
                "message": "Password reset successfully. You can now log in."
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Password reset failed"
            )


    @router.post("/logout")
    async def logout(credentials: HTTPAuthorizationCredentials = Depends(security)):
        try:
            token = credentials.credentials
            db_manager.blacklist_token(token)

            return {
                "success": True,
                "message": "Logged out successfully"
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Logout failed"
            )


    @router.get("/me")
    async def get_current_user(current_user: dict = Depends(auth_middleware.require_user())):
        return {
            "success": True,
            "user": current_user
        }


    @router.put("/profile")
    async def update_profile(
        request: UpdateProfileRequest,
        current_user: dict = Depends(auth_middleware.require_user())
    ):
        try:
            updates = {}
            if request.name is not None:
                updates['name'] = request.name
            if request.bio is not None:
                updates['bio'] = request.bio
            if request.handle is not None:
                updates['handle'] = request.handle
            if request.tagline is not None:
                updates['tagline'] = request.tagline

            updated_user = db_manager.update_user_profile(
                user_id=current_user['user_id'],
                updates=updates
            )

            return {
                "success": True,
                "message": "Profile updated successfully",
                "user": updated_user
            }

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Profile update failed"
            )


    @router.post("/profile/avatar")
    async def upload_avatar(
        file: UploadFile = File(...),
        current_user: dict = Depends(auth_middleware.require_user())
    ):
        try:
            allowed_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
            if file.content_type not in allowed_types:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid file type. Only images allowed (JPEG, PNG, GIF, WEBP)"
                )

            file_content = await file.read()
            if len(file_content) > 5 * 1024 * 1024:
                raise HTTPException(
                    status_code=400,
                    detail="File too large. Maximum size is 5MB"
                )

            ext = Path(file.filename).suffix
            filename = f"{current_user['user_id']}_{uuid.uuid4().hex[:8]}{ext}"

            # Resolve upload dir at request time to avoid stale closures
            _upload = Path(__file__).resolve().parent.parent / "frontend" / "static" / "uploads" / "profiles"
            _upload.mkdir(parents=True, exist_ok=True)
            filepath = _upload / filename

            with open(filepath, 'wb') as f:
                f.write(file_content)

            avatar_url = f"/static/uploads/profiles/{filename}"
            updated_user = db_manager.update_user_profile(
                user_id=current_user['user_id'],
                updates={'avatar_url': avatar_url}
            )

            return {
                "success": True,
                "message": "Avatar uploaded successfully",
                "avatar_url": avatar_url,
                "user": updated_user
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Avatar upload failed"
            )


    @router.put("/password")
    async def update_password(
        request: UpdatePasswordRequest,
        current_user: dict = Depends(auth_middleware.require_user())
    ):
        try:
            if request.new_password != request.confirm_password:
                raise HTTPException(
                    status_code=400,
                    detail="New passwords do not match"
                )

            if len(request.new_password) < 6:
                raise HTTPException(
                    status_code=400,
                    detail="Password must be at least 6 characters"
                )

            success = db_manager.change_password(
                user_id=current_user['user_id'],
                old_password=request.current_password,
                new_password=request.new_password
            )

            if not success:
                raise HTTPException(
                    status_code=400,
                    detail="Current password is incorrect"
                )

            return {
                "success": True,
                "message": "Password updated successfully"
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Password update failed"
            )


    @router.delete("/account")
    async def delete_own_account(
        credentials: HTTPAuthorizationCredentials = Depends(security),
        current_user: dict = Depends(auth_middleware.require_user())
    ):
        try:
            user_id = current_user['user_id']

            success = db_manager.delete_user(user_id)

            if not success:
                raise HTTPException(
                    status_code=404,
                    detail="User not found"
                )

            # Blacklist the current token so it can't be reused
            token = credentials.credentials
            db_manager.blacklist_token(token)

            return {
                "success": True,
                "message": "Account deleted successfully"
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Account deletion failed"
            )


    @router.put("/preferences")
    async def update_preferences(
        request: UpdatePreferencesRequest,
        current_user: dict = Depends(auth_middleware.require_user())
    ):
        try:
            updates = {}
            if request.email_notifications is not None:
                updates['email_notifications'] = request.email_notifications
            if request.weekly_summary is not None:
                updates['weekly_summary'] = request.weekly_summary
            if request.content_updates is not None:
                updates['content_updates'] = request.content_updates

            updated_user = db_manager.update_user_preferences(
                user_id=current_user['user_id'],
                preferences=updates
            )

            return {
                "success": True,
                "message": "Preferences updated successfully",
                "user": updated_user
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Preferences update failed"
            )


    @router.get("/stats")
    async def get_user_stats(current_user: dict = Depends(auth_middleware.require_user())):
        try:
            stats = db_manager.get_user_stats(current_user['user_id'])

            return {
                "success": True,
                "stats": stats
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve stats"
            )


    return router
