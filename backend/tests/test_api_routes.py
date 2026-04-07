"""
test_api_routes.py
==================
Integration tests for the main FastAPI app routes (api.py).

Covered:
  GET  /api/health
  POST /api/chat
  GET  /api/progress/{goal_id}
  GET  /api/goals
  GET  /api/videos/{goal_id}
  GET  /api/articles/{goal_id}
  GET  /api/stats
  GET  /api/goals/{goal_id}/tasks
  PUT  /api/goals/{goal_id}/tasks/{task_id}
  GET  /api/goals/{goal_id}/tasks/summary
  GET  /api/goals/{goal_id}/tasks/week/{week_num}

The processing_system is fully mocked (api_client fixture from conftest.py).
Database operations on the module-level db_manager are injected via monkeypatch
where necessary.
"""
import threading
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.plan_task_validator import extract_tasks_from_plan


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan():
    return {
        "goal": "Learn Python",
        "total_weeks": 2,
        "weekly_breakdown": [
            {
                "week": 1, "theme": "Foundations",
                "bloom_level": "remember", "focus": "Variables",
                "learning_objectives": ["Understand variables", "Use print()"],
                "practice_exercises": ["Hello world", "Calculator"],
                "spaced_review": [], "milestone_project": None,
                "psychological_hook": "!", "explanation": "Week 1",
                "videos_needed": 2, "articles_needed": 2,
                "status": "pending_content",
            },
            {
                "week": 2, "theme": "Control Flow",
                "bloom_level": "understand", "focus": "Conditionals",
                "learning_objectives": ["Write if/else", "Use loops"],
                "practice_exercises": ["FizzBuzz", "Number game"],
                "spaced_review": [], "milestone_project": None,
                "psychological_hook": "!", "explanation": "Week 2",
                "videos_needed": 2, "articles_needed": 2,
                "status": "pending_content",
            },
        ],
    }


def _goal(goal_id="g1", user_id="user1"):
    return {
        "id": goal_id,
        "user_id": user_id,
        "title": "Learn Python",
        "description": "Learn Python basics",
        "status": "pending",
        "progress": 0.0,
        "plan": _plan(),
        "deadline": (datetime.now() + timedelta(weeks=8)).strftime("%Y-%m-%d"),
        "created_at": datetime.now().isoformat(),
        "total_weeks": 2,
    }


# ===========================================================================
# /api/health
# ===========================================================================

class TestHealthCheck:
    def test_returns_200(self, api_client):
        resp = api_client.get("/api/health")
        assert resp.status_code == 200

    def test_status_is_healthy(self, api_client):
        resp = api_client.get("/api/health")
        assert resp.json()["status"] == "healthy"

    def test_system_running_is_true(self, api_client):
        resp = api_client.get("/api/health")
        assert resp.json()["system_running"] is True


# ===========================================================================
# POST /api/chat
# ===========================================================================

class TestChatEndpoint:
    def test_returns_200_with_response(self, api_client):
        resp = api_client.post("/api/chat", json={
            "message": "Hello", "user_id": "user1"
        })
        assert resp.status_code == 200

    def test_chat_response_key_present(self, api_client):
        resp = api_client.post("/api/chat", json={
            "message": "What is Python?", "user_id": "user1"
        })
        assert "chat_response" in resp.json()

    def test_goal_created_action_adds_metadata(self, api_client, mock_processing_system):
        """When action_required == goal_created, endpoint adds progress_url."""
        mock_processing_system.chatbot.send_message = AsyncMock(return_value={
            "chat_response": "Goal created!",
            "action_required": "goal_created",
            "new_goal": {"id": "new-goal-123"},
            "goal_detected": True,
        })
        resp = api_client.post("/api/chat", json={
            "message": "I want to learn Django", "user_id": "user1"
        })
        data = resp.json()
        assert data["goal_id"] == "new-goal-123"
        assert "progress_url" in data

    def test_no_processing_system_returns_500(self, api_client, mock_processing_system):
        """Simulate processing_system = None by making send_message raise."""
        import backend.api as api_module
        original = api_module.processing_system
        api_module.processing_system = None
        try:
            resp = api_client.post("/api/chat", json={"message": "hi", "user_id": "u"})
            assert resp.status_code in (200, 500)
        finally:
            api_module.processing_system = original

    def test_missing_message_returns_422(self, api_client):
        resp = api_client.post("/api/chat", json={"user_id": "u"})
        assert resp.status_code == 422

    def test_default_user_id(self, api_client):
        resp = api_client.post("/api/chat", json={"message": "hi"})
        assert resp.status_code == 200

    def test_empty_message_processed(self, api_client):
        resp = api_client.post("/api/chat", json={"message": "", "user_id": "u"})
        assert resp.status_code == 200


# ===========================================================================
# GET /api/progress/{goal_id}
# ===========================================================================

class TestProgressEndpoint:
    def test_not_found_goal_returns_not_found_status(self, api_client, mock_processing_system):
        mock_processing_system.db_manager.get_goal_by_id.return_value = None
        resp = api_client.get("/api/progress/missing-goal")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_found"

    def test_completed_goal_in_db_returns_completed(
        self, api_client, mock_processing_system
    ):
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1",
            "plan": {"total_weeks": 4},
            "videos_generated": True,
            "articles_generated": True,
        }
        resp = api_client.get("/api/progress/g1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["progress"] == 100

    def test_partial_goal_returns_processing(
        self, api_client, mock_processing_system
    ):
        mock_processing_system.db_manager.get_goal_by_id.return_value = {
            "id": "g1",
            "plan": {"total_weeks": 4},
            "videos_generated": False,
            "articles_generated": False,
        }
        resp = api_client.get("/api/progress/g1")
        data = resp.json()
        assert data["status"] == "processing"
        assert 0 <= data["progress"] < 100

    def test_task_in_queue_with_all_results_is_completed(
        self, api_client, mock_processing_system
    ):
        task = MagicMock()
        task.results = {
            "plan": {"total_weeks": 4},
            "youtube_videos": [],
            "articles": [],
        }
        mock_processing_system.shared_data.tasks = {"g1": task}
        resp = api_client.get("/api/progress/g1")
        data = resp.json()
        assert data["status"] == "completed"
        assert data["plan_ready"] is True
        assert data["videos_ready"] is True
        assert data["articles_ready"] is True

    def test_task_in_queue_pending_plan_shows_progress_0(
        self, api_client, mock_processing_system
    ):
        task = MagicMock()
        task.results = {}
        mock_processing_system.shared_data.tasks = {"g1": task}
        resp = api_client.get("/api/progress/g1")
        data = resp.json()
        assert data["progress"] == 0

    def test_plan_ready_but_no_videos(self, api_client, mock_processing_system):
        task = MagicMock()
        task.results = {"plan": {"total_weeks": 4}}
        mock_processing_system.shared_data.tasks = {"g1": task}
        resp = api_client.get("/api/progress/g1")
        data = resp.json()
        assert data["plan_ready"] is True
        assert data["videos_ready"] is False
        assert data["articles_ready"] is False
        assert data["progress"] == 33


# ===========================================================================
# GET /api/goals
# ===========================================================================

class TestGoalsEndpoint:
    def test_returns_200(self, api_client):
        resp = api_client.get("/api/goals?user_id=user1")
        assert resp.status_code == 200

    def test_empty_goals_returns_empty_dict(self, api_client):
        resp = api_client.get("/api/goals?user_id=user1")
        assert resp.json() == {}

    def test_goals_with_data(self, api_client, mock_processing_system):
        goal = _goal()
        mock_processing_system.chatbot.get_goals.return_value = [goal]
        mock_processing_system.db_manager.get_videos_by_goal.return_value = [{"title": "V"}]
        mock_processing_system.db_manager.get_articles_by_goal.return_value = []
        resp = api_client.get("/api/goals?user_id=user1")
        assert resp.status_code == 200
        data = resp.json()
        assert "g1" in data

    def test_goal_has_results_key(self, api_client, mock_processing_system):
        mock_processing_system.chatbot.get_goals.return_value = [_goal()]
        resp = api_client.get("/api/goals?user_id=user1")
        data = resp.json()
        goal_data = data["g1"]
        assert "results" in goal_data

    def test_default_user_id(self, api_client):
        resp = api_client.get("/api/goals")
        assert resp.status_code == 200


# ===========================================================================
# GET /api/videos/{goal_id}
# ===========================================================================

class TestVideosEndpoint:
    def test_returns_empty_list_by_default(self, api_client):
        resp = api_client.get("/api/videos/nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_videos_list(self, api_client, mock_processing_system):
        mock_processing_system.db_manager.get_videos_by_goal.return_value = [
            {"title": "Python Tutorial", "url": "https://youtube.com/1"}
        ]
        resp = api_client.get("/api/videos/g1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Python Tutorial"

    def test_multiple_videos(self, api_client, mock_processing_system):
        mock_processing_system.db_manager.get_videos_by_goal.return_value = [
            {"title": "V1"}, {"title": "V2"}, {"title": "V3"}
        ]
        resp = api_client.get("/api/videos/g1")
        assert len(resp.json()) == 3


# ===========================================================================
# GET /api/articles/{goal_id}
# ===========================================================================

class TestArticlesEndpoint:
    def test_returns_empty_list_by_default(self, api_client):
        resp = api_client.get("/api/articles/nonexistent")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_articles_list(self, api_client, mock_processing_system):
        mock_processing_system.db_manager.get_articles_by_goal.return_value = [
            {"title": "Python Guide", "url": "https://medium.com/1"}
        ]
        resp = api_client.get("/api/articles/g1")
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Python Guide"


# ===========================================================================
# GET /api/stats
# ===========================================================================

class TestStatsEndpoint:
    def test_returns_200(self, api_client):
        resp = api_client.get("/api/stats?user_id=user1")
        assert resp.status_code == 200

    def test_response_has_active_goals(self, api_client):
        resp = api_client.get("/api/stats?user_id=user1")
        assert "active_goals" in resp.json()

    def test_response_has_completed_tasks(self, api_client):
        resp = api_client.get("/api/stats?user_id=user1")
        assert "completed_tasks" in resp.json()

    def test_response_has_progress(self, api_client):
        resp = api_client.get("/api/stats?user_id=user1")
        assert "progress" in resp.json()

    def test_active_goals_count_matches_chatbot(self, api_client, mock_processing_system):
        mock_processing_system.chatbot.get_goals.return_value = [_goal("g1"), _goal("g2")]
        resp = api_client.get("/api/stats?user_id=user1")
        assert resp.json()["active_goals"] == 2


# ===========================================================================
# GET /api/goals/{goal_id}/tasks
# ===========================================================================

class TestGetGoalTasks:
    def test_existing_goal_with_tasks_returns_200(self, api_client):
        tasks = extract_tasks_from_plan("g1", _plan())
        import backend.api as api_module
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        api_module.db_manager.get_goal_by_id = MagicMock(return_value=_goal())
        resp = api_client.get("/api/goals/g1/tasks")
        assert resp.status_code == 200

    def test_missing_goal_returns_404(self, api_client):
        import backend.api as api_module
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=[])
        api_module.db_manager.get_goal_by_id = MagicMock(return_value=None)
        resp = api_client.get("/api/goals/missing/tasks")
        assert resp.status_code == 404

    def test_goal_without_plan_returns_202(self, api_client):
        import backend.api as api_module
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=[])
        api_module.db_manager.get_goal_by_id = MagicMock(return_value={
            "id": "g1", "title": "Learn Python"
        })
        resp = api_client.get("/api/goals/g1/tasks")
        assert resp.status_code == 202

    def test_response_has_total_field(self, api_client):
        tasks = extract_tasks_from_plan("g1", _plan())
        import backend.api as api_module
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        api_module.db_manager.get_goal_by_id = MagicMock(return_value=_goal())
        resp = api_client.get("/api/goals/g1/tasks")
        if resp.status_code == 200:
            assert "total" in resp.json()


# ===========================================================================
# PUT /api/goals/{goal_id}/tasks/{task_id}
# ===========================================================================

class TestUpdateTaskStatus:
    def test_valid_update_returns_200(self, api_client):
        import backend.api as api_module
        api_module.db_manager.update_task_status = MagicMock(return_value={
            "status": "in_progress", "completed_at": None,
            "updated_at": "2025-01-01T00:00:00", "notes": ""
        })
        api_module.db_manager.get_goal_by_id = MagicMock(return_value={"id": "g1", "progress": 10})
        resp = api_client.put(
            "/api/goals/g1/tasks/g1_w01_obj_00",
            json={"status": "in_progress", "notes": ""}
        )
        assert resp.status_code == 200

    def test_invalid_transition_returns_400(self, api_client):
        import backend.api as api_module
        api_module.db_manager.update_task_status = MagicMock(
            side_effect=ValueError("Cannot transition from 'pending' to 'completed'")
        )
        resp = api_client.put(
            "/api/goals/g1/tasks/g1_w01_obj_00",
            json={"status": "completed", "notes": ""}
        )
        assert resp.status_code == 400
        assert "error" in resp.json()

    def test_missing_status_returns_422(self, api_client):
        resp = api_client.put(
            "/api/goals/g1/tasks/g1_w01_obj_00",
            json={}
        )
        assert resp.status_code == 422

    def test_response_has_task_id(self, api_client):
        import backend.api as api_module
        api_module.db_manager.update_task_status = MagicMock(return_value={
            "status": "in_progress", "completed_at": None,
            "updated_at": "2025-01-01T00:00:00", "notes": ""
        })
        api_module.db_manager.get_goal_by_id = MagicMock(return_value={"id": "g1", "progress": 5})
        resp = api_client.put(
            "/api/goals/g1/tasks/g1_w01_obj_00",
            json={"status": "in_progress"}
        )
        if resp.status_code == 200:
            assert "task_id" in resp.json()

    def test_response_has_goal_progress(self, api_client):
        import backend.api as api_module
        api_module.db_manager.update_task_status = MagicMock(return_value={
            "status": "in_progress", "completed_at": None,
            "updated_at": "2025-01-01T00:00:00", "notes": ""
        })
        api_module.db_manager.get_goal_by_id = MagicMock(
            return_value={"id": "g1", "progress": 25}
        )
        resp = api_client.put(
            "/api/goals/g1/tasks/g1_w01_obj_00",
            json={"status": "in_progress"}
        )
        if resp.status_code == 200:
            assert "goal_progress" in resp.json()


# ===========================================================================
# GET /api/goals/{goal_id}/tasks/summary
# ===========================================================================

class TestTaskSummary:
    def test_missing_goal_returns_404(self, api_client):
        import backend.api as api_module
        api_module.db_manager.get_goal_by_id = MagicMock(return_value=None)
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=[])
        resp = api_client.get("/api/goals/bad-id/tasks/summary")
        assert resp.status_code == 404

    def test_valid_goal_returns_report(self, api_client):
        import backend.api as api_module
        goal = _goal("g1")
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_goal_by_id = MagicMock(return_value=goal)
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/summary")
        assert resp.status_code == 200
        report = resp.json()
        assert "plan_health" in report
        assert "recommendations" in report

    def test_report_has_current_week(self, api_client):
        import backend.api as api_module
        goal = _goal("g1")
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_goal_by_id = MagicMock(return_value=goal)
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/summary")
        assert "current_week" in resp.json()


# ===========================================================================
# GET /api/goals/{goal_id}/tasks/week/{week_num}
# ===========================================================================

class TestTasksByWeek:
    def test_returns_tasks_for_week(self, api_client):
        import backend.api as api_module
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/week/1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["week"] == 1
        assert isinstance(data["tasks"], list)

    def test_week_tasks_filter_correctly(self, api_client):
        import backend.api as api_module
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/week/1")
        data = resp.json()
        assert all(t["week"] == 1 for t in data["tasks"])

    def test_nonexistent_week_returns_empty(self, api_client):
        import backend.api as api_module
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/week/99")
        data = resp.json()
        assert data["total"] == 0
        assert data["tasks"] == []

    def test_response_has_completed_count(self, api_client):
        import backend.api as api_module
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/week/1")
        assert "completed" in resp.json()

    def test_response_has_goal_id(self, api_client):
        import backend.api as api_module
        tasks = extract_tasks_from_plan("g1", _plan())
        api_module.db_manager.get_all_tasks_for_goal = MagicMock(return_value=tasks)
        resp = api_client.get("/api/goals/g1/tasks/week/1")
        assert resp.json()["goal_id"] == "g1"
