from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime


class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "user"


class UpdateUserRoleRequest(BaseModel):
    role: str


def create_admin_router(db_manager, auth_middleware):
    router = APIRouter(prefix="/api/admin", tags=["admin"])


    @router.get("/users")
    async def list_all_users(
        page: int = Query(1, ge=1),
        per_page: int = Query(20, ge=1, le=100),
        search: Optional[str] = None,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            users = db_manager.get_all_users()

            if search:
                search_lower = search.lower()
                users = [
                    u for u in users
                    if search_lower in u.get('name', '').lower() or
                       search_lower in u.get('email', '').lower() or
                       search_lower in u.get('handle', '').lower()
                ]

            total = len(users)
            start = (page - 1) * per_page
            end = start + per_page
            users_page = users[start:end]

            return {
                "success": True,
                "users": users_page,
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve users"
            )


    @router.get("/users/{user_id}")
    async def get_user(
        user_id: str,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            user = db_manager.get_user_by_id(user_id)

            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            stats = db_manager.get_user_stats(user_id)
            goals = db_manager.get_user_goals(user_id)

            return {
                "success": True,
                "user": user,
                "stats": stats,
                "goals_count": len(goals)
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve user"
            )


    @router.post("/users")
    async def create_user_admin(
        request: CreateUserRequest,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            if request.role not in ['user', 'admin']:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid role. Must be 'user' or 'admin'"
                )

            try:
                user = db_manager.create_user(
                    name=request.name,
                    email=request.email,
                    password=request.password,
                    role=request.role
                )
            except ValueError as e:
                if "already registered" in str(e):
                    raise HTTPException(
                        status_code=400,
                        detail="Email already registered"
                    )
                raise HTTPException(status_code=400, detail=str(e))

            return {
                "success": True,
                "message": "User created successfully",
                "user": user
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to create user"
            )


    @router.put("/users/{user_id}/role")
    async def update_user_role(
        user_id: str,
        request: UpdateUserRoleRequest,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            if request.role not in ['user', 'admin']:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid role. Must be 'user' or 'admin'"
                )

            if user_id == current_user['user_id']:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot change your own role"
                )

            updated_user = db_manager.update_user_role(user_id, request.role)

            return {
                "success": True,
                "message": "User role updated successfully",
                "user": updated_user
            }

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to update user role"
            )


    @router.post("/users/{user_id}/deactivate")
    async def deactivate_user(
        user_id: str,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            if user_id == current_user['user_id']:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot deactivate your own account"
                )

            updated_user = db_manager.deactivate_user(user_id)

            return {
                "success": True,
                "message": "User deactivated successfully",
                "user": updated_user
            }

        except HTTPException:
            raise
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to deactivate user"
            )


    @router.post("/users/{user_id}/reactivate")
    async def reactivate_user(
        user_id: str,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            updated_user = db_manager.reactivate_user(user_id)

            return {
                "success": True,
                "message": "User reactivated successfully",
                "user": updated_user
            }

        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to reactivate user"
            )


    @router.delete("/users/{user_id}")
    async def delete_user(
        user_id: str,
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            if user_id == current_user['user_id']:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot delete your own account"
                )

            success = db_manager.delete_user(user_id)

            if not success:
                raise HTTPException(status_code=404, detail="User not found")

            return {
                "success": True,
                "message": "User deleted successfully"
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to delete user"
            )


    @router.get("/stats")
    async def get_system_stats(
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            stats = db_manager.get_system_stats()

            return {
                "success": True,
                "stats": stats
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve system stats"
            )


    @router.get("/audit-log")
    async def get_audit_log(
        limit: int = Query(100, ge=1, le=1000),
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            log = db_manager.get_audit_log(limit=limit)

            return {
                "success": True,
                "log": log,
                "total": len(log)
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve audit log"
            )


    @router.get("/dashboard")
    async def get_admin_dashboard(
        current_user: dict = Depends(auth_middleware.require_admin())
    ):
        try:
            users = db_manager.get_all_users()

            total_users = len(users)
            active_users = len([u for u in users if u.get('is_active', True)])
            admin_users = len([u for u in users if u.get('role') == 'admin'])

            recent_activity = db_manager.get_audit_log(limit=10)
            system_stats = db_manager.get_system_stats()

            return {
                "success": True,
                "dashboard": {
                    "users": {
                        "total": total_users,
                        "active": active_users,
                        "inactive": total_users - active_users,
                        "admins": admin_users
                    },
                    "system": system_stats,
                    "recent_activity": recent_activity
                }
            }

        except Exception as e:
            raise HTTPException(
                status_code=500,
                detail="Failed to retrieve admin dashboard"
            )


    return router
