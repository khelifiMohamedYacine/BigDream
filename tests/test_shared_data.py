"""
Tests for SharedData and SmartCache — thread safety, task lifecycle,
cache expiry, query helpers.
"""
import time
import threading
import pytest
from datetime import datetime

from backend.app.shared_data import SharedData, GoalData, ProcessingTask, ProcessingStatus
from backend.app.GoalProcessingSystem import SmartCache


# ---------------------------------------------------------------------------
# GoalData helper
# ---------------------------------------------------------------------------

def make_goal(goal_id="g1", user_id="u1"):
    return GoalData(
        id=goal_id,
        description="Learn Python",
        user_id=user_id,
        created_at=datetime.now().isoformat(),
        deadline="2026-12-31",
        status="pending",
    )


# ===========================================================================
# SmartCache
# ===========================================================================

class TestSmartCache:
    def test_set_and_get(self):
        cache = SmartCache(max_age_seconds=60)
        cache.set("key1", {"data": 42})
        assert cache.get("key1") == {"data": 42}

    def test_get_missing_key_returns_none(self):
        cache = SmartCache()
        assert cache.get("nonexistent") is None

    def test_expired_entry_returns_none(self):
        cache = SmartCache(max_age_seconds=0)  # expires immediately
        cache.set("key", "value")
        time.sleep(0.01)
        assert cache.get("key") is None

    def test_non_expired_entry_returned(self):
        cache = SmartCache(max_age_seconds=60)
        cache.set("key", "value")
        assert cache.get("key") == "value"

    def test_clear_empties_cache(self):
        cache = SmartCache()
        cache.set("a", 1)
        cache.set("b", 2)
        cache.clear()
        assert cache.get("a") is None
        assert cache.get("b") is None

    def test_overwrite_updates_value(self):
        cache = SmartCache()
        cache.set("key", "old")
        cache.set("key", "new")
        assert cache.get("key") == "new"


# ===========================================================================
# SharedData — basic operations
# ===========================================================================

class TestSharedDataBasics:
    def test_add_task_returns_goal_id(self):
        sd = SharedData()
        goal = make_goal("g1")
        returned_id = sd.add_task(goal)
        assert returned_id == "g1"

    def test_get_task_found(self):
        sd = SharedData()
        goal = make_goal("g1")
        sd.add_task(goal)
        task = sd.get_task("g1")
        assert task is not None
        assert task.goal.id == "g1"

    def test_get_task_not_found(self):
        sd = SharedData()
        assert sd.get_task("nonexistent") is None

    def test_new_task_status_is_pending(self):
        sd = SharedData()
        sd.add_task(make_goal("g1"))
        task = sd.get_task("g1")
        assert task.status == ProcessingStatus.PENDING

    def test_update_task_marks_completed(self):
        sd = SharedData()
        sd.add_task(make_goal("g1"))
        sd.update_task("g1", {"plan": {"total_weeks": 8}})
        task = sd.get_task("g1")
        assert task.status == ProcessingStatus.COMPLETED

    def test_update_task_stores_results(self):
        sd = SharedData()
        sd.add_task(make_goal("g1"))
        sd.update_task("g1", {"plan": {"total_weeks": 8}, "videos": []})
        task = sd.get_task("g1")
        assert "plan" in task.results

    def test_mark_task_processing(self):
        sd = SharedData()
        sd.add_task(make_goal("g1"))
        sd.mark_task_processing("g1")
        task = sd.get_task("g1")
        assert task.status == ProcessingStatus.PROCESSING

    def test_mark_task_processing_nonexistent_does_not_raise(self):
        sd = SharedData()
        sd.mark_task_processing("nonexistent")  # should silently do nothing

    def test_user_tasks_tracked(self):
        sd = SharedData()
        sd.add_task(make_goal("g1", "u1"))
        sd.add_task(make_goal("g2", "u1"))
        sd.add_task(make_goal("g3", "u2"))
        assert len(sd.user_tasks["u1"]) == 2
        assert len(sd.user_tasks["u2"]) == 1


# ===========================================================================
# SharedData — query helpers
# ===========================================================================

class TestSharedDataQueries:
    def _setup(self):
        sd = SharedData()
        sd.add_task(make_goal("g1"))
        sd.add_task(make_goal("g2"))
        sd.update_task("g2", {"plan": {"total_weeks": 8}})  # g2 is completed
        return sd

    def test_get_pending_tasks_returns_only_pending(self):
        sd = self._setup()
        pending = sd.get_pending_tasks()
        assert all(t.status == ProcessingStatus.PENDING for t in pending)
        assert len(pending) == 1

    def test_get_completed_tasks_returns_only_completed(self):
        sd = self._setup()
        completed = sd.get_completed_tasks()
        assert all(t.status == ProcessingStatus.COMPLETED for t in completed)
        assert len(completed) == 1

    def test_get_tasks_needing_videos_no_youtube_videos_key(self):
        sd = self._setup()
        needing = sd.get_tasks_needing_videos()
        # g2 is completed but has no youtube_videos key
        assert any(t.goal.id == "g2" for t in needing)

    def test_get_tasks_needing_videos_after_videos_added(self):
        sd = self._setup()
        sd.update_task("g2", {"youtube_videos": [{"id": "v1"}]})
        needing = sd.get_tasks_needing_videos()
        assert not any(t.goal.id == "g2" for t in needing)

    def test_get_tasks_needing_articles_no_articles_key(self):
        sd = self._setup()
        needing = sd.get_tasks_needing_articles()
        assert any(t.goal.id == "g2" for t in needing)

    def test_get_tasks_needing_articles_after_articles_added(self):
        sd = self._setup()
        sd.update_task("g2", {"articles": [{"id": "a1"}]})
        needing = sd.get_tasks_needing_articles()
        assert not any(t.goal.id == "g2" for t in needing)

    def test_get_user_results(self):
        sd = SharedData()
        sd.add_task(make_goal("g1", "u1"))
        sd.update_task("g1", {"plan": {}})
        results = sd.get_user_results("u1")
        assert "g1" in results

    def test_get_user_results_empty_for_unknown_user(self):
        sd = SharedData()
        assert sd.get_user_results("nobody") == {}


# ===========================================================================
# Thread safety
# ===========================================================================

class TestSharedDataThreadSafety:
    def test_concurrent_add_tasks_no_data_corruption(self):
        sd = SharedData()
        errors = []

        def add_goals(start, end):
            for i in range(start, end):
                try:
                    sd.add_task(make_goal(f"g{i}", "u1"))
                except Exception as e:
                    errors.append(e)

        threads = [threading.Thread(target=add_goals, args=(i * 10, (i + 1) * 10))
                   for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # All 50 goals should be in tasks
        assert len(sd.tasks) == 50

    def test_concurrent_reads_and_writes_no_error(self):
        sd = SharedData()
        for i in range(10):
            sd.add_task(make_goal(f"g{i}"))

        errors = []

        def update_tasks():
            for i in range(10):
                try:
                    sd.update_task(f"g{i}", {"plan": {}})
                except Exception as e:
                    errors.append(e)

        def read_tasks():
            for _ in range(50):
                try:
                    sd.get_pending_tasks()
                except Exception as e:
                    errors.append(e)

        threads = ([threading.Thread(target=update_tasks)] +
                   [threading.Thread(target=read_tasks) for _ in range(3)])
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
