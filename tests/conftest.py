"""
Shared fixtures for all BigDream test suites.
"""
import pytest
from pathlib import Path
from datetime import datetime, timedelta

from backend.database_manager import DatabaseManager
from backend.auth_middleware import AuthMiddleware


# ---------------------------------------------------------------------------
# Database fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db(tmp_path):
    """Fresh DatabaseManager backed by a temporary directory."""
    return DatabaseManager(data_dir=str(tmp_path))


@pytest.fixture
def auth(db):
    """AuthMiddleware wired to the temp db."""
    return AuthMiddleware(db)


# ---------------------------------------------------------------------------
# Pre-built data fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_user(db):
    """A registered, active user."""
    return db.create_user("Alice", "alice@test.com", "Password1!")


@pytest.fixture
def sample_admin(db):
    """A registered admin user."""
    return db.create_user("Admin", "admin@test.com", "Password1!", role="admin")


@pytest.fixture
def sample_goal():
    """A minimal goal dict suitable for db.save_goal()."""
    return {
        "id": "goal01",
        "user_id": "user-placeholder",
        "title": "Learn Python",
        "description": "Learn Python basics",
        "status": "pending",
        "progress": 0.0,
        "deadline": (datetime.now() + timedelta(weeks=8)).strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
        "total_weeks": 8,
        "videos_per_week": 2,
        "articles_per_week": 2,
    }


@pytest.fixture
def sample_plan():
    """A minimal learning plan with two weeks of tasks."""
    return {
        "goal": "Learn Python",
        "total_weeks": 2,
        "weekly_breakdown": [
            {
                "week": 1,
                "theme": "Foundations",
                "bloom_level": "remember",
                "focus": "Understand Python basics",
                "learning_objectives": ["Understand variables", "Write a print statement"],
                "practice_exercises": ["Write hello world", "Build a calculator"],
                "spaced_review": [],
                "milestone_project": None,
                "psychological_hook": "You got this!",
                "explanation": "First week of learning.",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            },
            {
                "week": 2,
                "theme": "Control Flow",
                "bloom_level": "understand",
                "focus": "Learn conditionals and loops",
                "learning_objectives": ["Use if/else", "Write a for loop"],
                "practice_exercises": ["FizzBuzz", "Number guessing game"],
                "spaced_review": ["Review variables"],
                "milestone_project": "Mini-project: number game",
                "psychological_hook": "Week 2, keep going!",
                "explanation": "Second week.",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            },
        ],
    }


@pytest.fixture
def goal_with_plan(db, sample_user, sample_goal, sample_plan):
    """A goal that has a generated plan stored in the DB."""
    goal = dict(sample_goal)
    goal["user_id"] = sample_user["user_id"]
    goal["plan"] = sample_plan
    db.save_goal(goal)
    return goal


@pytest.fixture
def user_token(auth, sample_user):
    """A valid JWT token for sample_user."""
    return auth.generate_token(
        sample_user["user_id"],
        sample_user["email"],
        sample_user["role"],
    )


@pytest.fixture
def admin_token(auth, sample_admin):
    """A valid JWT token for sample_admin."""
    return auth.generate_token(
        sample_admin["user_id"],
        sample_admin["email"],
        sample_admin["role"],
    )
