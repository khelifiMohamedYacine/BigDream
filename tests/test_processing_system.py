"""
Tests for GoalProcessingSystem — worker lifecycle, caching,
plan/video/article task dispatch, error logging.
"""
import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.GoalProcessingSystem import GoalProcessingSystem, SmartCache
from backend.app.shared_data import GoalData, ProcessingStatus
from datetime import datetime


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_goal(goal_id="g1"):
    g = GoalData(
        id=goal_id,
        description="Learn Python",
        user_id="u1",
        created_at=datetime.now().isoformat(),
        deadline="2026-12-31",
        status="pending",
    )
    g.total_weeks = 8
    g.timeline = "8 weeks"
    g.why_important = "Career"
    g.skill_level = "beginner"
    g.hours_per_week = "5h/week"
    g.success_metric = "Build a project"
    g.goal_type = "python_basics"
    return g


# ===========================================================================
# GoalProcessingSystem lifecycle
# ===========================================================================

class TestGoalProcessingSystemLifecycle:
    @pytest.mark.asyncio
    async def test_start_sets_running_true(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            await gps.start()
            assert gps.running is True
            await gps.stop()

    @pytest.mark.asyncio
    async def test_stop_sets_running_false(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            await gps.start()
            await gps.stop()
            assert gps.running is False

    @pytest.mark.asyncio
    async def test_start_creates_three_worker_tasks(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            await gps.start()
            assert len(gps.worker_tasks) == 3
            await gps.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_all_worker_tasks(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            await gps.start()
            tasks_before = list(gps.worker_tasks)
            await gps.stop()
            for t in tasks_before:
                assert t.cancelled() or t.done()


# ===========================================================================
# _generate_plan_for_task
# ===========================================================================

class TestGeneratePlanForTask:
    @pytest.mark.asyncio
    async def test_plan_stored_in_shared_data(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            task = gps.shared_data.get_task("g1")

            mock_plan = {"weekly_breakdown": [], "total_weeks": 8}
            gps.plan_generator.generate_plan = AsyncMock(return_value=mock_plan)

            await gps._generate_plan_for_task("g1", task)

            updated = gps.shared_data.get_task("g1")
            assert "plan" in updated.results

    @pytest.mark.asyncio
    async def test_cache_used_on_second_call(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            task = gps.shared_data.get_task("g1")

            mock_plan = {"weekly_breakdown": [], "total_weeks": 8}
            gps.plan_generator.generate_plan = AsyncMock(return_value=mock_plan)

            await gps._generate_plan_for_task("g1", task)
            await gps._generate_plan_for_task("g1", task)

            # generate_plan should only be called once due to caching
            assert gps.plan_generator.generate_plan.call_count == 1

    @pytest.mark.asyncio
    async def test_exception_is_logged_not_raised(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            task = gps.shared_data.get_task("g1")
            gps.plan_generator.generate_plan = AsyncMock(side_effect=RuntimeError("API down"))

            # Should not raise
            await gps._generate_plan_for_task("g1", task)


# ===========================================================================
# _find_videos_for_task
# ===========================================================================

class TestFindVideosForTask:
    @pytest.mark.asyncio
    async def test_videos_stored_in_shared_data(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            # Simulate plan already done
            gps.shared_data.update_task("g1", {"plan": {"total_weeks": 8}})
            task = gps.shared_data.get_task("g1")

            mock_videos = [{"id": "v1", "title": "Intro to Python"}]
            gps.youtube_searcher.find_videos_for_goal = AsyncMock(return_value=mock_videos)

            await gps._find_videos_for_task("g1", task)

            updated = gps.shared_data.get_task("g1")
            assert "youtube_videos" in updated.results
            assert updated.results["youtube_videos"] == mock_videos

    @pytest.mark.asyncio
    async def test_exception_logged_not_raised(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            gps.shared_data.update_task("g1", {"plan": {"total_weeks": 8}})
            task = gps.shared_data.get_task("g1")
            gps.youtube_searcher.find_videos_for_goal = AsyncMock(
                side_effect=RuntimeError("Invidious down")
            )
            await gps._find_videos_for_task("g1", task)  # should not raise


# ===========================================================================
# _find_articles_for_task
# ===========================================================================

class TestFindArticlesForTask:
    @pytest.mark.asyncio
    async def test_articles_stored_in_shared_data(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            gps.shared_data.update_task("g1", {"plan": {"total_weeks": 8}})
            task = gps.shared_data.get_task("g1")

            mock_articles = {"articles": [{"id": "a1", "title": "Python guide"}]}
            gps.article_searcher.find_articles_for_goal = AsyncMock(return_value=mock_articles)

            await gps._find_articles_for_task("g1", task)

            updated = gps.shared_data.get_task("g1")
            assert "articles" in updated.results
            assert updated.results["articles"] == mock_articles["articles"]

    @pytest.mark.asyncio
    async def test_exception_logged_not_raised(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = make_goal("g1")
            gps.shared_data.add_task(goal)
            gps.shared_data.update_task("g1", {"plan": {"total_weeks": 8}})
            task = gps.shared_data.get_task("g1")
            gps.article_searcher.find_articles_for_goal = AsyncMock(
                side_effect=RuntimeError("Reddit down")
            )
            await gps._find_articles_for_task("g1", task)  # should not raise


# ===========================================================================
# get_user_goals
# ===========================================================================

class TestGetUserGoals:
    def test_returns_dict(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            gps.chatbot.get_goals = MagicMock(return_value=[])
            result = gps.get_user_goals("u1")
            assert isinstance(result, dict)

    def test_caches_result(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            gps.chatbot.get_goals = MagicMock(return_value=[])
            gps.get_user_goals("u1")
            gps.get_user_goals("u1")
            # Second call should use cache — get_goals called only once
            assert gps.chatbot.get_goals.call_count == 1

    def test_goal_with_videos_included(self, tmp_path):
        with patch("backend.app.GoalProcessingSystem.DatabaseManager"):
            gps = GoalProcessingSystem()
            goal = {"id": "g1", "user_id": "u1", "title": "T", "description": "D",
                    "status": "pending", "progress": 0.0, "deadline": "2026-12-31",
                    "created_at": "2026-01-01", "total_weeks": 8}
            gps.chatbot.get_goals = MagicMock(return_value=[goal])
            gps.db_manager.get_videos_by_goal = MagicMock(return_value=[{"id": "v1"}])
            gps.db_manager.get_articles_by_goal = MagicMock(return_value=[])
            result = gps.get_user_goals("u1")
            assert "g1" in result
            assert result["g1"]["results"]["videos_generated"] is True
