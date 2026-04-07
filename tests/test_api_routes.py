"""
Tests for the main FastAPI app routes (api.py) — HTML pages, chat, progress,
goals, videos, articles, stats, health, and task endpoints.
Uses TestClient with a mocked processing_system.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from datetime import datetime


# ---------------------------------------------------------------------------
# App fixture — import api and override the module-level processing_system
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_processing_system():
    ps = MagicMock()
    ps.running = True
    ps.shared_data = MagicMock()
    ps.shared_data.lock = __import__("threading").Lock()
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
    ps.db_manager.get_user_goals.return_value = []
    return ps


@pytest.fixture
def app_client(mock_processing_system):
    import backend.api as api_module
    # Make start/stop awaitable so the lifespan works with the mock
    mock_processing_system.start = AsyncMock()
    mock_processing_system.stop = AsyncMock()
    # Patch GoalProcessingSystem so the lifespan uses our mock instead of
    # creating a real instance (which would overwrite our mock).
    with patch("backend.api.GoalProcessingSystem", return_value=mock_processing_system):
        # Also patch the module-level db_manager so endpoints that use it directly
        # (tasks, quiz) are testing against the mock.
        original_db = api_module.db_manager
        api_module.db_manager = mock_processing_system.db_manager
        try:
            with TestClient(api_module.app, raise_server_exceptions=False) as client:
                yield client
        finally:
            api_module.db_manager = original_db


# ===========================================================================
# HTML page routes
# ===========================================================================

class TestHtmlRoutes:
    @pytest.mark.parametrize("path", [
        "/", "/index.html", "/home.html", "/login.html", "/register.html",
        "/forgot-password.html", "/reset-password.html",
        "/goals.html", "/videos.html", "/articles.html",
        "/account.html", "/admin.html",
    ])
    def test_html_page_returns_200(self, app_client, path):
        resp = app_client.get(path)
        assert resp.status_code == 200

    def test_html_response_is_html(self, app_client):
        resp = app_client.get("/")
        assert "text/html" in resp.headers.get("content-type", "")


# ===========================================================================
# /api/health
# ===========================================================================

class TestHealthCheck:
    def test_returns_200(self, app_client):
        resp = app_client.get("/api/health")
        assert resp.status_code == 200

    def test_status_healthy(self, app_client):
        data = app_client.get("/api/health").json()
        assert data["status"] == "healthy"

    def test_system_running_true(self, app_client):
        data = app_client.get("/api/health").json()
        assert data["system_running"] is True


# ===========================================================================
# /api/chat
# ===========================================================================

class TestChatEndpoint:
    def test_basic_message_returns_200(self, app_client):
        resp = app_client.post("/api/chat", json={
            "message": "Hello!",
            "user_id": "u1",
        })
        assert resp.status_code == 200

    def test_response_has_chat_response(self, app_client):
        data = app_client.post("/api/chat", json={
            "message": "Hello!", "user_id": "u1",
        }).json()
        assert "chat_response" in data

    def test_goal_created_adds_progress_url(self, app_client, mock_processing_system):
        mock_processing_system.chatbot.send_message = AsyncMock(return_value={
            "chat_response": "Goal created!",
            "new_goal": {"id": "g1", "title": "Learn Python"},
            "goal_detected": True,
            "action_required": "goal_created",
        })
        data = app_client.post("/api/chat", json={
            "message": "I want to learn Python", "user_id": "u1",
        }).json()
        assert "goal_id" in data
        assert "progress_url" in data

    def test_service_not_ready_returns_500(self, app_client, mock_processing_system):
        import backend.api as api_module
        api_module.processing_system = None
        resp = app_client.post("/api/chat", json={"message": "Hi", "user_id": "u1"})
        api_module.processing_system = mock_processing_system
        assert resp.status_code == 500

    def test_missing_message_returns_422(self, app_client):
        resp = app_client.post("/api/chat", json={"user_id": "u1"})
        assert resp.status_code == 422


# ===========================================================================
# /api/goals
# ===========================================================================

class TestGoalsEndpoint:
    def test_returns_200(self, app_client):
        resp = app_client.get("/api/goals?user_id=u1")
        assert resp.status_code == 200

    def test_returns_dict(self, app_client):
        data = app_client.get("/api/goals?user_id=u1").json()
        assert isinstance(data, dict)

    def test_goals_keyed_by_id(self, app_client, mock_processing_system):
        goal = {"id": "g1", "user_id": "u1", "title": "T", "description": "D",
                "status": "pending", "progress": 0.0, "deadline": "2026-12-31",
                "created_at": "2026-01-01", "total_weeks": 8}
        mock_processing_system.chatbot.get_goals.return_value = [goal]
        data = app_client.get("/api/goals?user_id=u1").json()
        assert "g1" in data


# ===========================================================================
# /api/progress/{goal_id}
# ===========================================================================

class TestProgressEndpoint:
    def test_goal_not_found_returns_not_found(self, app_client):
        data = app_client.get("/api/progress/nonexistent").json()
        assert data["status"] == "not_found"

    def test_goal_in_shared_data_returns_status(self, app_client, mock_processing_system):
        from backend.app.shared_data import ProcessingTask, ProcessingStatus, GoalData
        task = MagicMock()
        task.results = {"plan": {"total_weeks": 8}}
        mock_processing_system.shared_data.tasks = {"g1": task}
        data = app_client.get("/api/progress/g1").json()
        assert "status" in data
        assert "progress" in data

    def test_completed_goal_in_db_returns_completed(self, app_client, mock_processing_system):
        mock_processing_system.shared_data.tasks = {}
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1", "plan": {"total_weeks": 8},
            "videos_generated": True, "articles_generated": True,
        }
        data = app_client.get("/api/progress/g1").json()
        assert data["status"] == "completed"

    def test_partially_ready_returns_processing(self, app_client, mock_processing_system):
        mock_processing_system.shared_data.tasks = {}
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1", "plan": {"total_weeks": 8},
            "videos_generated": False, "articles_generated": False,
        }
        data = app_client.get("/api/progress/g1").json()
        assert data["status"] == "processing"


# ===========================================================================
# /api/videos/{goal_id}
# ===========================================================================

class TestVideosEndpoint:
    def test_returns_empty_list_for_no_videos(self, app_client):
        data = app_client.get("/api/videos/g1").json()
        assert data == []

    def test_returns_videos_list(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_videos_by_goal.return_value = [
            {"id": "v1", "title": "Intro to Python", "goal_id": "g1"}
        ]
        data = app_client.get("/api/videos/g1").json()
        assert len(data) == 1
        assert data[0]["title"] == "Intro to Python"


# ===========================================================================
# /api/articles/{goal_id}
# ===========================================================================

class TestArticlesEndpoint:
    def test_returns_empty_list_for_no_articles(self, app_client):
        data = app_client.get("/api/articles/g1").json()
        assert data == []

    def test_returns_articles_list(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_articles_by_goal.return_value = [
            {"id": "a1", "title": "Python Guide", "goal_id": "g1"}
        ]
        data = app_client.get("/api/articles/g1").json()
        assert len(data) == 1


# ===========================================================================
# /api/stats
# ===========================================================================

class TestStatsEndpoint:
    def test_returns_200(self, app_client):
        resp = app_client.get("/api/stats?user_id=u1")
        assert resp.status_code == 200

    def test_has_active_goals(self, app_client):
        data = app_client.get("/api/stats?user_id=u1").json()
        assert "active_goals" in data

    def test_reflects_goal_count(self, app_client, mock_processing_system):
        mock_processing_system.chatbot.get_goals.return_value = [
            {"id": "g1", "status": "pending", "progress": 50},
            {"id": "g2", "status": "completed", "progress": 100},
        ]
        data = app_client.get("/api/stats?user_id=u1").json()
        assert data["active_goals"] == 2


# ===========================================================================
# /api/goals/{goal_id}/tasks
# ===========================================================================

class TestTaskEndpoints:
    def test_get_tasks_goal_not_found_returns_404(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_all_tasks_for_goal.return_value = []
        mock_processing_system.db_manager.get_goal_by_id.return_value = None
        resp = app_client.get("/api/goals/no-such-goal/tasks")
        assert resp.status_code == 404

    def test_get_tasks_no_plan_returns_202(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_all_tasks_for_goal.return_value = []
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1", "title": "T"
        }
        resp = app_client.get("/api/goals/g1/tasks")
        assert resp.status_code == 202

    def test_get_tasks_with_plan_returns_200(self, app_client, mock_processing_system):
        tasks = [
            {"id": "g1_w01_obj_00", "week": 1, "type": "objective",
             "text": "Learn vars", "status": "pending"}
        ]
        mock_processing_system.db_manager.get_all_tasks_for_goal.return_value = tasks
        resp = app_client.get("/api/goals/g1/tasks")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1

    def test_update_task_status_returns_200(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.update_task_status.return_value = {
            "status": "in_progress", "updated_at": datetime.now().isoformat(), "notes": ""
        }
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1", "progress": 10, "task_progress_detail": {}
        }
        resp = app_client.put(
            "/api/goals/g1/tasks/task01",
            json={"status": "in_progress", "notes": ""},
        )
        assert resp.status_code == 200

    def test_update_task_invalid_status_returns_400(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.update_task_status.side_effect = ValueError("Invalid")
        resp = app_client.put(
            "/api/goals/g1/tasks/task01",
            json={"status": "flying", "notes": ""},
        )
        assert resp.status_code == 400

    def test_get_tasks_for_week_returns_200(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_all_tasks_for_goal.return_value = [
            {"id": "t1", "week": 1, "type": "objective", "text": "T", "status": "pending"}
        ]
        resp = app_client.get("/api/goals/g1/tasks/week/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["week"] == 1

    def test_get_task_summary_returns_200(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1", "title": "Learn Python", "total_weeks": 8, "goal_type": "coding"
        }
        mock_processing_system.db_manager.get_all_tasks_for_goal.return_value = []
        resp = app_client.get("/api/goals/g1/tasks/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "plan_health" in data

    def test_get_task_summary_goal_not_found_returns_404(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.get_goal_by_id.return_value = None
        resp = app_client.get("/api/goals/no-such/tasks/summary")
        assert resp.status_code == 404


# ===========================================================================
# Quiz endpoints
# ===========================================================================

class TestQuizEndpoints:
    def test_get_quiz_returns_200(self, app_client, mock_processing_system):
        import asyncio
        mock_processing_system.db_manager.get_or_create_quiz = AsyncMock(return_value={
            "questions": [
                {"question": "Q1", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "A"}
            ],
            "attempts": 0,
            "passed": False,
        })
        mock_processing_system.db_manager.can_take_quiz.return_value = {
            "can_take": True, "reason": None, "next_attempt_at": None
        }
        resp = app_client.get("/api/goals/g1/quiz?user_id=u1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["can_take"] is True
        assert "quiz" in data

    def test_get_quiz_not_found_returns_404(self, app_client, mock_processing_system):
        import asyncio
        mock_processing_system.db_manager.get_or_create_quiz = AsyncMock(return_value=None)
        resp = app_client.get("/api/goals/g1/quiz?user_id=u1")
        assert resp.status_code == 404

    def test_submit_quiz_passes(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.can_take_quiz.return_value = {
            "can_take": True, "reason": None, "next_attempt_at": None
        }
        mock_processing_system.db_manager.submit_quiz_attempt.return_value = {
            "passed": True, "score": 8, "attempts": 1,
            "completed": True, "deleted": True,
        }
        resp = app_client.post("/api/goals/g1/quiz/submit?user_id=u1", json={"answers": {"1": "A", "2": "B"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is True
        assert data["score"] == 8

    def test_submit_quiz_fails_and_blocks_retake(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.can_take_quiz.return_value = {
            "can_take": True, "reason": None, "next_attempt_at": None
        }
        mock_processing_system.db_manager.submit_quiz_attempt.return_value = {
            "passed": False, "score": 4, "attempts": 2,
            "permanently_failed": True, "next_attempt_at": None,
        }
        resp = app_client.post("/api/goals/g1/quiz/submit?user_id=u1", json={"answers": {"1": "A"}})
        assert resp.status_code == 200
        data = resp.json()
        assert data["passed"] is False
        assert data["permanently_failed"] is True

    def test_submit_quiz_when_not_allowed_returns_403(self, app_client, mock_processing_system):
        mock_processing_system.db_manager.can_take_quiz.return_value = {
            "can_take": False, "reason": "Retake not yet available", "next_attempt_at": "2026-01-02T00:00:00"
        }
        resp = app_client.post("/api/goals/g1/quiz/submit?user_id=u1", json={"answers": {"1": "A"}})
        assert resp.status_code == 403
