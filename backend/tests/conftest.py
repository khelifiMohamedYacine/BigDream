"""
conftest.py — Shared pytest fixtures for backend/tests.

Run from project root:
    pytest backend/tests/ -v
"""
import sys
import os
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Make project root importable so "from backend.xxx import yyy" works.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.database_manager import DatabaseManager
from backend.auth_middleware import AuthMiddleware


# ---------------------------------------------------------------------------
# Database / auth fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Fresh DatabaseManager backed by a temp directory (isolated per test)."""
    return DatabaseManager(data_dir=str(tmp_path))


@pytest.fixture
def auth(db):
    """AuthMiddleware wired to the temp db."""
    return AuthMiddleware(db)


# ---------------------------------------------------------------------------
# Pre-built user fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user(db):
    """A registered, active regular user."""
    return db.create_user("Alice", "alice@example.com", "Password1!")


@pytest.fixture
def sample_admin(db):
    """A registered admin user."""
    return db.create_user("Admin", "admin@example.com", "Password1!", role="admin")


@pytest.fixture
def second_user(db):
    """A second regular user for multi-user scenarios."""
    return db.create_user("Bob", "bob@example.com", "Password2!")


# ---------------------------------------------------------------------------
# Goal / plan data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_goal():
    """Minimal goal dict — user_id must be filled in before saving."""
    deadline = (datetime.now() + timedelta(weeks=8)).strftime("%Y-%m-%d")
    return {
        "id": "goal_test_01",
        "user_id": "PLACEHOLDER",
        "title": "Learn Python",
        "description": "Master Python from scratch",
        "status": "pending",
        "progress": 0.0,
        "deadline": deadline,
        "created_at": datetime.now().isoformat(),
        "total_weeks": 8,
        "skill_level": "beginner",
        "goal_type": "coding",
        "videos_per_week": 2,
        "articles_per_week": 2,
    }


@pytest.fixture
def sample_plan():
    """A 2-week learning plan with well-formed weekly_breakdown entries."""
    return {
        "goal": "Learn Python",
        "total_weeks": 2,
        "weekly_breakdown": [
            {
                "week": 1,
                "theme": "Python Foundations",
                "bloom_level": "remember",
                "focus": "Variables, types, print",
                "learning_objectives": [
                    "Understand variables",
                    "Use print() effectively",
                    "Know basic data types",
                ],
                "practice_exercises": [
                    "Write a hello-world program",
                    "Build a simple calculator",
                ],
                "spaced_review": [],
                "milestone_project": None,
                "psychological_hook": "Your first program!",
                "explanation": "Foundation week.",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            },
            {
                "week": 2,
                "theme": "Control Flow",
                "bloom_level": "understand",
                "focus": "Conditionals and loops",
                "learning_objectives": [
                    "Write if/else statements",
                    "Use for and while loops",
                ],
                "practice_exercises": [
                    "FizzBuzz challenge",
                    "Number guessing game",
                ],
                "spaced_review": ["Review data types"],
                "milestone_project": "Mini number game",
                "psychological_hook": "Keep going!",
                "explanation": "Control flow week.",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            },
        ],
    }


@pytest.fixture
def goal_with_plan(db, sample_user, sample_goal, sample_plan):
    """A goal with a generated plan already persisted in the DB."""
    goal = dict(sample_goal)
    goal["user_id"] = sample_user["user_id"]
    goal["plan"] = sample_plan
    db.save_goal(goal)
    return goal


# ---------------------------------------------------------------------------
# JWT token fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def user_token(auth, sample_user):
    """A valid JWT for sample_user."""
    return auth.generate_token(
        sample_user["user_id"],
        sample_user["email"],
        sample_user["role"],
    )


@pytest.fixture
def admin_token(auth, sample_admin):
    """A valid JWT for sample_admin."""
    return auth.generate_token(
        sample_admin["user_id"],
        sample_admin["email"],
        sample_admin["role"],
    )


# ---------------------------------------------------------------------------
# Auth-route FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture
def auth_client(db, auth):
    """TestClient for auth routes only (no processing_system needed)."""
    from backend.auth_routes import create_auth_router

    app = FastAPI()
    router = create_auth_router(db, auth)
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def auth_client_with_user(auth_client, db, auth):
    """auth_client with a pre-registered Alice; returns (client, user, token)."""
    resp = auth_client.post("/api/auth/register", json={
        "name": "Alice",
        "email": "alice@example.com",
        "password": "Password1!",
        "confirm_password": "Password1!",
    })
    assert resp.status_code == 200
    data = resp.json()
    return auth_client, data["user"], data["access_token"]


# ---------------------------------------------------------------------------
# Admin-route FastAPI test client
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client(db, auth):
    """TestClient for admin routes only."""
    from backend.admin_routes import create_admin_router

    app = FastAPI()
    router = create_admin_router(db, auth)
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# Main API test client (mocked processing_system)
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_processing_system():
    """A MagicMock that satisfies all api.py references to processing_system."""
    import threading
    from unittest.mock import AsyncMock, MagicMock

    ps = MagicMock()
    ps.running = True
    ps.shared_data = MagicMock()
    ps.shared_data.lock = threading.Lock()
    ps.shared_data.tasks = {}
    ps.chatbot = MagicMock()
    ps.chatbot.get_goals.return_value = []
    ps.chatbot.send_message = AsyncMock(return_value={
        "chat_response": "Hello!",
        "new_goal": None,
        "goal_detected": False,
        "action_required": None,
    })
    ps.db_manager = MagicMock()
    ps.db_manager.get_videos_by_goal.return_value = []
    ps.db_manager.get_articles_by_goal.return_value = []
    ps.db_manager.get_goal_by_id.return_value = None
    ps.db_manager.get_all_tasks_for_goal.return_value = []
    ps.start = AsyncMock()
    ps.stop = AsyncMock()
    return ps


@pytest.fixture
def api_client(mock_processing_system):
    """TestClient for the full api.py app with mocked processing_system."""
    from unittest.mock import patch
    import backend.api as api_module

    with patch("backend.api.GoalProcessingSystem", return_value=mock_processing_system):
        with TestClient(api_module.app, raise_server_exceptions=False) as client:
            yield client


# ---------------------------------------------------------------------------
# Helpers (importable by test files)
# ---------------------------------------------------------------------------

def bearer(token: str) -> dict:
    """Build an Authorization header dict."""
    return {"Authorization": f"Bearer {token}"}
