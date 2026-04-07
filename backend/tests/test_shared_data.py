"""
test_shared_data.py
===================
Unit tests for SharedData — the thread-safe blackboard coordinating
the plan/video/article workers.

Covers:
  - add_task, get_task
  - mark_task_processing
  - update_task (complete with results)
  - get_pending_tasks, get_completed_tasks
  - get_tasks_needing_videos, get_tasks_needing_articles
  - get_user_results
  - Thread-safety (concurrent add + read)
  - ProcessingStatus transitions
  - GoalData dataclass
"""
import threading
import pytest
from datetime import datetime, timedelta

from backend.app.shared_data import (
    SharedData,
    GoalData,
    ProcessingTask,
    ProcessingStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _goal(goal_id="g1", user_id="user1", weeks=8):
    g = GoalData(
        id=goal_id,
        description="Learn Python",
        user_id=user_id,
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        deadline=(datetime.now() + timedelta(weeks=weeks)).strftime("%Y-%m-%d"),
        status="pending",
    )
    g.total_weeks = weeks
    return g


def _full_results():
    return {
        "plan": {"total_weeks": 8, "weekly_breakdown": []},
        "youtube_videos": [{"title": "Python Tutorial"}],
        "articles": [{"title": "Python Guide"}],
    }


# ===========================================================================
# add_task and get_task
# ===========================================================================

class TestAddGetTask:
    def test_add_task_returns_goal_id(self):
        sd = SharedData()
        goal = _goal("g1")
        returned_id = sd.add_task(goal)
        assert returned_id == "g1"

    def test_get_task_after_add(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        task = sd.get_task("g1")
        assert task is not None

    def test_initial_status_is_pending(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        task = sd.get_task("g1")
        assert task.status == ProcessingStatus.PENDING

    def test_initial_results_dict_is_empty(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        task = sd.get_task("g1")
        assert task.results == {}

    def test_get_nonexistent_task_returns_none(self):
        sd = SharedData()
        assert sd.get_task("bad-id") is None

    def test_goal_data_preserved_in_task(self):
        sd = SharedData()
        goal = _goal("g42", user_id="alice")
        sd.add_task(goal)
        task = sd.get_task("g42")
        assert task.goal.id == "g42"
        assert task.goal.user_id == "alice"

    def test_multiple_tasks_stored_independently(self):
        sd = SharedData()
        for i in range(5):
            sd.add_task(_goal(f"g{i}", user_id=f"user{i}"))
        for i in range(5):
            task = sd.get_task(f"g{i}")
            assert task is not None
            assert task.goal.user_id == f"user{i}"

    def test_user_tasks_index_updated(self):
        sd = SharedData()
        sd.add_task(_goal("g1", user_id="u1"))
        assert "u1" in sd.user_tasks
        assert "g1" in sd.user_tasks["u1"]

    def test_multiple_goals_per_user(self):
        sd = SharedData()
        sd.add_task(_goal("ga", user_id="u1"))
        sd.add_task(_goal("gb", user_id="u1"))
        assert len(sd.user_tasks["u1"]) == 2


# ===========================================================================
# mark_task_processing
# ===========================================================================

class TestMarkTaskProcessing:
    def test_status_changes_to_processing(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.mark_task_processing("g1")
        assert sd.get_task("g1").status == ProcessingStatus.PROCESSING

    def test_noop_for_nonexistent_task(self):
        sd = SharedData()
        # Must not raise
        sd.mark_task_processing("bad-id")

    def test_processing_task_not_in_pending(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.mark_task_processing("g1")
        pending = sd.get_pending_tasks()
        assert all(t.goal.id != "g1" for t in pending)


# ===========================================================================
# update_task (complete with results)
# ===========================================================================

class TestUpdateTask:
    def test_status_becomes_completed(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.mark_task_processing("g1")
        sd.update_task("g1", _full_results())
        assert sd.get_task("g1").status == ProcessingStatus.COMPLETED

    def test_results_stored(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.update_task("g1", {"plan": {"total_weeks": 4}})
        task = sd.get_task("g1")
        assert "plan" in task.results
        assert task.results["plan"]["total_weeks"] == 4

    def test_results_merged_on_multiple_updates(self):
        """update_task uses dict.update; earlier keys must be preserved."""
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.update_task("g1", {"plan": {"total_weeks": 4}})
        sd.update_task("g1", {"youtube_videos": [{"title": "Vid"}]})
        task = sd.get_task("g1")
        assert "plan" in task.results
        assert "youtube_videos" in task.results

    def test_noop_for_nonexistent_task(self):
        sd = SharedData()
        # Must not raise
        sd.update_task("bad-id", {"plan": {}})


# ===========================================================================
# get_pending_tasks
# ===========================================================================

class TestGetPendingTasks:
    def test_returns_pending_only(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.add_task(_goal("g2"))
        sd.mark_task_processing("g2")
        pending = sd.get_pending_tasks()
        assert len(pending) == 1
        assert pending[0].goal.id == "g1"

    def test_empty_when_no_pending(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.mark_task_processing("g1")
        assert sd.get_pending_tasks() == []

    def test_empty_when_no_tasks(self):
        sd = SharedData()
        assert sd.get_pending_tasks() == []


# ===========================================================================
# get_completed_tasks
# ===========================================================================

class TestGetCompletedTasks:
    def test_returns_completed_only(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.add_task(_goal("g2"))
        sd.update_task("g1", _full_results())
        completed = sd.get_completed_tasks()
        assert len(completed) == 1
        assert completed[0].goal.id == "g1"

    def test_empty_when_no_completed(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        assert sd.get_completed_tasks() == []


# ===========================================================================
# get_tasks_needing_videos
# ===========================================================================

class TestGetTasksNeedingVideos:
    def test_completed_without_videos_returned(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.update_task("g1", {"plan": {"total_weeks": 4}})  # completed, no videos
        needing = sd.get_tasks_needing_videos()
        assert len(needing) == 1

    def test_completed_with_videos_not_returned(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.update_task("g1", {"plan": {}, "youtube_videos": [{"title": "V"}]})
        assert sd.get_tasks_needing_videos() == []

    def test_pending_task_not_included(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        assert sd.get_tasks_needing_videos() == []

    def test_multiple_goals_only_video_less_returned(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.add_task(_goal("g2"))
        sd.update_task("g1", {"plan": {}, "youtube_videos": [{"title": "V"}]})
        sd.update_task("g2", {"plan": {}})  # no videos
        needing = sd.get_tasks_needing_videos()
        assert len(needing) == 1
        assert needing[0].goal.id == "g2"


# ===========================================================================
# get_tasks_needing_articles
# ===========================================================================

class TestGetTasksNeedingArticles:
    def test_completed_without_articles_returned(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.update_task("g1", {"plan": {}})  # no articles key
        assert len(sd.get_tasks_needing_articles()) == 1

    def test_completed_with_articles_not_returned(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        sd.update_task("g1", {"plan": {}, "articles": [{"title": "A"}]})
        assert sd.get_tasks_needing_articles() == []

    def test_pending_task_not_included(self):
        sd = SharedData()
        sd.add_task(_goal("g1"))
        assert sd.get_tasks_needing_articles() == []


# ===========================================================================
# get_user_results
# ===========================================================================

class TestGetUserResults:
    def test_returns_tasks_for_user(self):
        sd = SharedData()
        sd.add_task(_goal("g1", user_id="alice"))
        results = sd.get_user_results("alice")
        assert "g1" in results

    def test_isolates_users(self):
        sd = SharedData()
        sd.add_task(_goal("g1", user_id="alice"))
        sd.add_task(_goal("g2", user_id="bob"))
        assert "g1" not in sd.get_user_results("bob")
        assert "g2" not in sd.get_user_results("alice")

    def test_unknown_user_returns_empty_dict(self):
        sd = SharedData()
        assert sd.get_user_results("nobody") == {}

    def test_result_includes_status(self):
        sd = SharedData()
        sd.add_task(_goal("g1", user_id="alice"))
        result = sd.get_user_results("alice")["g1"]
        assert "status" in result

    def test_result_includes_goal(self):
        sd = SharedData()
        sd.add_task(_goal("g1", user_id="alice"))
        result = sd.get_user_results("alice")["g1"]
        assert "goal" in result

    def test_completed_goal_has_correct_status_string(self):
        sd = SharedData()
        sd.add_task(_goal("g1", user_id="alice"))
        sd.update_task("g1", _full_results())
        result = sd.get_user_results("alice")["g1"]
        assert result["status"] == "completed"


# ===========================================================================
# Thread safety
# ===========================================================================

class TestThreadSafety:
    def test_concurrent_add_tasks_no_data_loss(self):
        sd = SharedData()
        errors = []

        def add_goals(start, count):
            try:
                for i in range(start, start + count):
                    sd.add_task(_goal(f"g{i}", user_id="u"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_goals, args=(i * 10, 10)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(sd.tasks) == 50

    def test_concurrent_read_write_no_exception(self):
        """Simultaneous reads and writes must not raise RuntimeError."""
        sd = SharedData()
        for i in range(20):
            sd.add_task(_goal(f"g{i}", user_id="u"))

        errors = []

        def writer():
            try:
                for i in range(20):
                    sd.update_task(f"g{i}", {"plan": {}})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(50):
                    sd.get_pending_tasks()
                    sd.get_completed_tasks()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer)] + \
                  [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ===========================================================================
# ProcessingStatus enum
# ===========================================================================

class TestProcessingStatus:
    def test_pending_value(self):
        assert ProcessingStatus.PENDING.value == "pending"

    def test_processing_value(self):
        assert ProcessingStatus.PROCESSING.value == "processing"

    def test_completed_value(self):
        assert ProcessingStatus.COMPLETED.value == "completed"

    def test_failed_value(self):
        assert ProcessingStatus.FAILED.value == "failed"

    def test_distinct_values(self):
        values = [s.value for s in ProcessingStatus]
        assert len(set(values)) == len(values)


# ===========================================================================
# GoalData dataclass
# ===========================================================================

class TestGoalData:
    def test_all_fields_accessible(self):
        g = _goal("g1", user_id="u1", weeks=4)
        assert g.id == "g1"
        assert g.user_id == "u1"
        assert g.total_weeks == 4
        assert g.description == "Learn Python"
        assert g.status == "pending"
        assert g.created_at is not None
        assert g.deadline is not None
