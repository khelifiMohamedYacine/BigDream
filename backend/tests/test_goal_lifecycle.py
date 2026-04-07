"""
test_goal_lifecycle.py
======================
Comprehensive tests for goal lifecycle management:

  1. delete_goal            — single-goal deletion with full cascade
  2. is_goal_expired        — deadline / completion state logic
  3. get_expired_goals      — filtering expired goals
  4. delete_expired_goals   — bulk expiry-based cleanup

Every test verifies the behaviour expected by the system spec:
  • Deleting a goal MUST remove its videos and articles from storage.
  • Videos / articles belonging to OTHER goals MUST NOT be touched.
  • A completed goal is NEVER considered expired.
  • A goal without a deadline is NEVER considered expired.
  • Malformed deadline strings are treated as "no deadline" (not expired).
  • delete_goal with a wrong user_id ownership check must return False and
    leave the goal intact.
  • delete_expired_goals returns an accurate count and leaves future goals
    untouched.
  • All deletions are reflected in the audit log.
"""
import pytest
from datetime import datetime, timedelta

from backend.database_manager import DatabaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _yesterday():
    return (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _tomorrow():
    return (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")


def _in_weeks(n):
    return (datetime.now() + timedelta(weeks=n)).strftime("%Y-%m-%d")


def _weeks_ago(n):
    return (datetime.now() - timedelta(weeks=n)).strftime("%Y-%m-%d")


def _goal(goal_id, user_id, deadline=None, status="pending", completed=False):
    g = {
        "id": goal_id,
        "user_id": user_id,
        "title": f"Goal {goal_id}",
        "description": "Test goal",
        "status": status,
        "progress": 0.0,
        "deadline": deadline or _in_weeks(8),
        "created_at": datetime.now().isoformat(),
        "total_weeks": 8,
        "goal_type": "coding",
    }
    if completed:
        g["completed"] = True
        g["completed_at"] = datetime.now().isoformat()
        g["status"] = "completed"
    return g


def _save_videos(db, goal_id, count=2):
    videos = [{"title": f"Video {i} for {goal_id}", "url": f"https://yt.com/{goal_id}/{i}"}
              for i in range(count)]
    db.save_youtube_videos_for_goal(goal_id, videos)
    return videos


def _save_articles(db, goal_id, count=2):
    articles = [{"title": f"Article {i} for {goal_id}", "url": f"https://medium.com/{goal_id}/{i}"}
                for i in range(count)]
    db.save_articles_for_goal(goal_id, articles)
    return articles


def _make_plan():
    return {
        "goal": "Learn Python",
        "total_weeks": 2,
        "weekly_breakdown": [
            {
                "week": 1,
                "theme": "Foundations",
                "bloom_level": "remember",
                "focus": "Variables",
                "learning_objectives": ["Understand variables", "Use print()"],
                "practice_exercises": ["Hello world", "Calculator"],
                "spaced_review": [],
                "milestone_project": None,
                "psychological_hook": "!",
                "explanation": "Week 1",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            },
            {
                "week": 2,
                "theme": "Control Flow",
                "bloom_level": "understand",
                "focus": "Conditionals",
                "learning_objectives": ["Write if/else", "Use loops"],
                "practice_exercises": ["FizzBuzz", "Number game"],
                "spaced_review": [],
                "milestone_project": None,
                "psychological_hook": "!",
                "explanation": "Week 2",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            },
        ],
    }


# ===========================================================================
# delete_goal — basic contract
# ===========================================================================

class TestDeleteGoal:

    def test_returns_true_for_existing_goal(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"])
        db.save_goal(goal)
        assert db.delete_goal("g1") is True

    def test_returns_false_for_nonexistent_goal(self, db):
        assert db.delete_goal("does-not-exist") is False

    def test_goal_no_longer_retrievable_by_id(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.delete_goal("g1")
        assert db.get_goal_by_id("g1") is None

    def test_goal_absent_from_user_goals_list(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.delete_goal("g1")
        goals = db.get_user_goals(sample_user["user_id"])
        assert all(g["id"] != "g1" for g in goals)

    def test_delete_creates_audit_log_entry(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.delete_goal("g1")
        log = db.get_audit_log()
        assert any(e["action"] == "goal_deleted" for e in log)

    def test_audit_entry_contains_goal_id(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.delete_goal("g1")
        entry = next(e for e in db.get_audit_log() if e["action"] == "goal_deleted")
        assert entry["details"]["goal_id"] == "g1"

    def test_can_delete_multiple_goals_independently(self, db, sample_user):
        for i in range(1, 4):
            db.save_goal(_goal(f"g{i}", sample_user["user_id"]))
        db.delete_goal("g1")
        assert db.get_goal_by_id("g1") is None
        assert db.get_goal_by_id("g2") is not None
        assert db.get_goal_by_id("g3") is not None

    def test_delete_same_goal_twice_returns_false_second_time(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.delete_goal("g1")
        assert db.delete_goal("g1") is False

    def test_delete_goal_from_empty_db_returns_false(self, db):
        assert db.delete_goal("g999") is False


# ===========================================================================
# delete_goal — ownership enforcement
# ===========================================================================

class TestDeleteGoalOwnership:

    def test_correct_owner_can_delete(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        assert db.delete_goal("g1", user_id=sample_user["user_id"]) is True

    def test_wrong_owner_returns_false(self, db, sample_user, second_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        assert db.delete_goal("g1", user_id=second_user["user_id"]) is False

    def test_goal_intact_after_ownership_mismatch(self, db, sample_user, second_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.delete_goal("g1", user_id=second_user["user_id"])
        assert db.get_goal_by_id("g1") is not None

    def test_no_user_id_deletes_regardless_of_owner(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        assert db.delete_goal("g1") is True  # no ownership check

    def test_nonexistent_goal_with_user_id_returns_false(self, db, sample_user):
        assert db.delete_goal("bad-id", user_id=sample_user["user_id"]) is False


# ===========================================================================
# delete_goal — cascade: videos
# ===========================================================================

class TestDeleteGoalCascadeVideos:

    def test_videos_removed_after_delete(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_videos(db, "g1", count=3)
        db.delete_goal("g1")
        assert db.get_videos_by_goal("g1") == []

    def test_other_goals_videos_untouched(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.save_goal(_goal("g2", sample_user["user_id"]))
        _save_videos(db, "g1", count=2)
        _save_videos(db, "g2", count=3)
        db.delete_goal("g1")
        remaining = db.get_videos_by_goal("g2")
        assert len(remaining) == 3

    def test_goal_with_no_videos_deletes_cleanly(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        # no videos saved
        assert db.delete_goal("g1") is True
        assert db.get_videos_by_goal("g1") == []

    def test_videos_count_in_storage_decreases(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.save_goal(_goal("g2", sample_user["user_id"]))
        _save_videos(db, "g1", count=2)
        _save_videos(db, "g2", count=4)
        before = len(db.get_all_videos())  # 6
        db.delete_goal("g1")
        after = len(db.get_all_videos())   # should be 4
        assert after == before - 2

    def test_large_video_set_fully_removed(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_videos(db, "g1", count=20)
        db.delete_goal("g1")
        assert db.get_videos_by_goal("g1") == []

    def test_videos_of_deleted_goal_not_in_get_all(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_videos(db, "g1", count=2)
        db.delete_goal("g1")
        all_vids = db.get_all_videos()
        assert all(v.get("goal_id") != "g1" for v in all_vids)


# ===========================================================================
# delete_goal — cascade: articles
# ===========================================================================

class TestDeleteGoalCascadeArticles:

    def test_articles_removed_after_delete(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_articles(db, "g1", count=3)
        db.delete_goal("g1")
        assert db.get_articles_by_goal("g1") == []

    def test_other_goals_articles_untouched(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.save_goal(_goal("g2", sample_user["user_id"]))
        _save_articles(db, "g1", count=2)
        _save_articles(db, "g2", count=5)
        db.delete_goal("g1")
        remaining = db.get_articles_by_goal("g2")
        assert len(remaining) == 5

    def test_goal_with_no_articles_deletes_cleanly(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        assert db.delete_goal("g1") is True
        assert db.get_articles_by_goal("g1") == []

    def test_articles_count_in_storage_decreases(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.save_goal(_goal("g2", sample_user["user_id"]))
        _save_articles(db, "g1", count=3)
        _save_articles(db, "g2", count=4)
        before = len(db.get_all_articles())
        db.delete_goal("g1")
        after = len(db.get_all_articles())
        assert after == before - 3

    def test_large_article_set_fully_removed(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_articles(db, "g1", count=15)
        db.delete_goal("g1")
        assert db.get_articles_by_goal("g1") == []

    def test_articles_of_deleted_goal_not_in_get_all(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_articles(db, "g1", count=2)
        db.delete_goal("g1")
        all_arts = db.get_all_articles()
        assert all(a.get("goal_id") != "g1" for a in all_arts)


# ===========================================================================
# delete_goal — cascade: both videos AND articles together
# ===========================================================================

class TestDeleteGoalFullCascade:

    def test_both_videos_and_articles_removed(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        _save_videos(db, "g1", count=3)
        _save_articles(db, "g1", count=4)
        db.delete_goal("g1")
        assert db.get_videos_by_goal("g1") == []
        assert db.get_articles_by_goal("g1") == []

    def test_three_goals_only_one_deleted(self, db, sample_user):
        for gid in ("ga", "gb", "gc"):
            db.save_goal(_goal(gid, sample_user["user_id"]))
            _save_videos(db, gid, count=2)
            _save_articles(db, gid, count=2)
        db.delete_goal("gb")
        assert db.get_goal_by_id("gb") is None
        assert db.get_videos_by_goal("gb") == []
        assert db.get_articles_by_goal("gb") == []
        # Others intact
        assert len(db.get_videos_by_goal("ga")) == 2
        assert len(db.get_articles_by_goal("gc")) == 2

    def test_task_completions_inside_goal_gone_after_delete(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"])
        goal["plan"] = _make_plan()
        db.save_goal(goal)
        tasks = db.get_all_tasks_for_goal("g1")
        if tasks:
            db.update_task_status("g1", tasks[0]["id"], "in_progress")
        db.delete_goal("g1")
        assert db.get_goal_by_id("g1") is None
        assert db.get_task_completions("g1") == {}

    def test_system_stats_reflect_deletion(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"]))
        db.save_goal(_goal("g2", sample_user["user_id"]))
        _save_videos(db, "g1", count=2)
        _save_articles(db, "g1", count=2)
        before = db.get_system_stats()
        db.delete_goal("g1")
        after = db.get_system_stats()
        assert after["goals"]["total"] == before["goals"]["total"] - 1
        assert after["content"]["videos"] == before["content"]["videos"] - 2
        assert after["content"]["articles"] == before["content"]["articles"] - 2


# ===========================================================================
# is_goal_expired
# ===========================================================================

class TestIsGoalExpired:

    def test_past_deadline_pending_is_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline=_yesterday())
        assert db.is_goal_expired(goal) is True

    def test_future_deadline_not_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline=_tomorrow())
        assert db.is_goal_expired(goal) is False

    def test_deadline_today_not_expired(self, db, sample_user):
        """Deadline on the current date: not yet past."""
        goal = _goal("g1", sample_user["user_id"], deadline=_today())
        assert db.is_goal_expired(goal) is False

    def test_deadline_weeks_ago_is_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline=_weeks_ago(4))
        assert db.is_goal_expired(goal) is True

    def test_completed_goal_never_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"],
                     deadline=_weeks_ago(2), completed=True)
        assert db.is_goal_expired(goal) is False

    def test_status_completed_never_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"],
                     deadline=_weeks_ago(2), status="completed")
        assert db.is_goal_expired(goal) is False

    def test_no_deadline_never_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"])
        del goal["deadline"]
        assert db.is_goal_expired(goal) is False

    def test_empty_string_deadline_never_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline="")
        assert db.is_goal_expired(goal) is False

    def test_malformed_deadline_never_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline="not-a-date")
        assert db.is_goal_expired(goal) is False

    def test_return_type_is_bool(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"])
        result = db.is_goal_expired(goal)
        assert isinstance(result, bool)

    def test_one_day_past_deadline_is_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline=_yesterday())
        assert db.is_goal_expired(goal) is True

    def test_one_day_future_deadline_not_expired(self, db, sample_user):
        goal = _goal("g1", sample_user["user_id"], deadline=_tomorrow())
        assert db.is_goal_expired(goal) is False

    def test_one_year_ago_deadline_is_expired(self, db, sample_user):
        long_ago = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        goal = _goal("g1", sample_user["user_id"], deadline=long_ago)
        assert db.is_goal_expired(goal) is True


# ===========================================================================
# get_expired_goals
# ===========================================================================

class TestGetExpiredGoals:

    def test_returns_only_expired_goals(self, db, sample_user):
        db.save_goal(_goal("past",   sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("future", sample_user["user_id"], deadline=_tomorrow()))
        expired = db.get_expired_goals()
        assert len(expired) == 1
        assert expired[0]["id"] == "past"

    def test_returns_empty_when_none_expired(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"], deadline=_in_weeks(4)))
        db.save_goal(_goal("g2", sample_user["user_id"], deadline=_in_weeks(8)))
        assert db.get_expired_goals() == []

    def test_returns_empty_on_empty_db(self, db):
        assert db.get_expired_goals() == []

    def test_completed_goal_excluded(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"],
                           deadline=_yesterday(), completed=True))
        assert db.get_expired_goals() == []

    def test_multiple_expired_all_returned(self, db, sample_user):
        for i in range(5):
            db.save_goal(_goal(f"old{i}", sample_user["user_id"],
                               deadline=_weeks_ago(i + 1)))
        expired = db.get_expired_goals()
        assert len(expired) == 5

    def test_filters_by_user_id(self, db, sample_user, second_user):
        db.save_goal(_goal("ga", sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("gb", second_user["user_id"], deadline=_yesterday()))
        expired = db.get_expired_goals(user_id=sample_user["user_id"])
        assert len(expired) == 1
        assert expired[0]["id"] == "ga"

    def test_no_user_id_returns_all_users_expired(self, db, sample_user, second_user):
        db.save_goal(_goal("ga", sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("gb", second_user["user_id"], deadline=_yesterday()))
        expired = db.get_expired_goals()
        assert len(expired) == 2

    def test_unknown_user_returns_empty(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"], deadline=_yesterday()))
        assert db.get_expired_goals(user_id="unknown-user") == []

    def test_mixed_goals_correct_count(self, db, sample_user):
        db.save_goal(_goal("e1", sample_user["user_id"], deadline=_weeks_ago(1)))
        db.save_goal(_goal("e2", sample_user["user_id"], deadline=_weeks_ago(2)))
        db.save_goal(_goal("f1", sample_user["user_id"], deadline=_in_weeks(1)))
        db.save_goal(_goal("f2", sample_user["user_id"], deadline=_in_weeks(2)))
        db.save_goal(_goal("c1", sample_user["user_id"],
                           deadline=_weeks_ago(1), completed=True))
        expired = db.get_expired_goals()
        assert len(expired) == 2
        ids = {g["id"] for g in expired}
        assert ids == {"e1", "e2"}

    def test_result_contains_full_goal_dicts(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"], deadline=_yesterday()))
        expired = db.get_expired_goals()
        assert "id" in expired[0]
        assert "title" in expired[0]
        assert "deadline" in expired[0]


# ===========================================================================
# delete_expired_goals
# ===========================================================================

class TestDeleteExpiredGoals:

    def test_returns_count_of_deleted_goals(self, db, sample_user):
        for i in range(3):
            db.save_goal(_goal(f"old{i}", sample_user["user_id"],
                               deadline=_weeks_ago(i + 1)))
        assert db.delete_expired_goals() == 3

    def test_returns_zero_when_nothing_expired(self, db, sample_user):
        db.save_goal(_goal("g1", sample_user["user_id"], deadline=_in_weeks(4)))
        assert db.delete_expired_goals() == 0

    def test_returns_zero_on_empty_db(self, db):
        assert db.delete_expired_goals() == 0

    def test_expired_goals_gone_from_db(self, db, sample_user):
        db.save_goal(_goal("old", sample_user["user_id"], deadline=_yesterday()))
        db.delete_expired_goals()
        assert db.get_goal_by_id("old") is None

    def test_future_goals_untouched(self, db, sample_user):
        db.save_goal(_goal("old",    sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("future", sample_user["user_id"], deadline=_in_weeks(4)))
        db.delete_expired_goals()
        assert db.get_goal_by_id("future") is not None

    def test_completed_goals_not_deleted(self, db, sample_user):
        db.save_goal(_goal("done", sample_user["user_id"],
                           deadline=_yesterday(), completed=True))
        count = db.delete_expired_goals()
        assert count == 0
        assert db.get_goal_by_id("done") is not None

    def test_cascade_videos_removed_for_expired(self, db, sample_user):
        db.save_goal(_goal("old", sample_user["user_id"], deadline=_yesterday()))
        _save_videos(db, "old", count=3)
        db.delete_expired_goals()
        assert db.get_videos_by_goal("old") == []

    def test_cascade_articles_removed_for_expired(self, db, sample_user):
        db.save_goal(_goal("old", sample_user["user_id"], deadline=_yesterday()))
        _save_articles(db, "old", count=4)
        db.delete_expired_goals()
        assert db.get_articles_by_goal("old") == []

    def test_future_goals_videos_untouched(self, db, sample_user):
        db.save_goal(_goal("old",    sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("future", sample_user["user_id"], deadline=_in_weeks(4)))
        _save_videos(db, "old",    count=2)
        _save_videos(db, "future", count=3)
        db.delete_expired_goals()
        assert len(db.get_videos_by_goal("future")) == 3

    def test_future_goals_articles_untouched(self, db, sample_user):
        db.save_goal(_goal("old",    sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("future", sample_user["user_id"], deadline=_in_weeks(4)))
        _save_articles(db, "old",    count=2)
        _save_articles(db, "future", count=5)
        db.delete_expired_goals()
        assert len(db.get_articles_by_goal("future")) == 5

    def test_user_id_filter_only_deletes_that_users_goals(
        self, db, sample_user, second_user
    ):
        db.save_goal(_goal("ua", sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("ub", second_user["user_id"], deadline=_yesterday()))
        count = db.delete_expired_goals(user_id=sample_user["user_id"])
        assert count == 1
        assert db.get_goal_by_id("ua") is None
        assert db.get_goal_by_id("ub") is not None   # second user's goal intact

    def test_user_id_filter_leaves_other_users_content(
        self, db, sample_user, second_user
    ):
        db.save_goal(_goal("ua", sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("ub", second_user["user_id"], deadline=_yesterday()))
        _save_videos(db, "ua", count=2)
        _save_videos(db, "ub", count=3)
        db.delete_expired_goals(user_id=sample_user["user_id"])
        assert len(db.get_videos_by_goal("ub")) == 3

    def test_idempotent_second_call_returns_zero(self, db, sample_user):
        db.save_goal(_goal("old", sample_user["user_id"], deadline=_yesterday()))
        db.delete_expired_goals()
        assert db.delete_expired_goals() == 0

    def test_get_expired_goals_empty_after_bulk_delete(self, db, sample_user):
        for i in range(4):
            db.save_goal(_goal(f"e{i}", sample_user["user_id"],
                               deadline=_weeks_ago(i + 1)))
        db.delete_expired_goals()
        assert db.get_expired_goals() == []

    def test_all_expired_deletions_logged(self, db, sample_user):
        for i in range(3):
            db.save_goal(_goal(f"e{i}", sample_user["user_id"],
                               deadline=_weeks_ago(i + 1)))
        db.delete_expired_goals()
        log = db.get_audit_log()
        deleted_entries = [e for e in log if e["action"] == "goal_deleted"]
        assert len(deleted_entries) == 3


# ===========================================================================
# Edge cases: goals with plans and task completions
# ===========================================================================

class TestDeleteGoalWithPlanAndTasks:

    def test_goal_with_plan_deleted_cleanly(self, db, sample_user):
        goal = _goal("gp", sample_user["user_id"])
        goal["plan"] = _make_plan()
        db.save_goal(goal)
        assert db.delete_goal("gp") is True
        assert db.get_goal_by_id("gp") is None

    def test_task_completions_not_accessible_after_delete(self, db, sample_user):
        goal = _goal("gp", sample_user["user_id"])
        goal["plan"] = _make_plan()
        db.save_goal(goal)
        tasks = db.get_all_tasks_for_goal("gp")
        if tasks:
            db.update_task_status("gp", tasks[0]["id"], "in_progress")
        db.delete_goal("gp")
        assert db.get_task_completions("gp") == {}

    def test_get_all_tasks_empty_after_delete(self, db, sample_user):
        goal = _goal("gp", sample_user["user_id"])
        goal["plan"] = _make_plan()
        db.save_goal(goal)
        db.delete_goal("gp")
        assert db.get_all_tasks_for_goal("gp") == []

    def test_expired_goal_with_plan_and_content_fully_cleaned(self, db, sample_user):
        goal = _goal("gp", sample_user["user_id"], deadline=_yesterday())
        goal["plan"] = _make_plan()
        db.save_goal(goal)
        _save_videos(db, "gp", count=5)
        _save_articles(db, "gp", count=4)
        db.delete_expired_goals()
        assert db.get_goal_by_id("gp") is None
        assert db.get_videos_by_goal("gp") == []
        assert db.get_articles_by_goal("gp") == []
        assert db.get_all_tasks_for_goal("gp") == []


# ===========================================================================
# Multi-user isolation
# ===========================================================================

class TestMultiUserIsolation:

    def test_deleting_one_users_goal_leaves_other_users_goals(
        self, db, sample_user, second_user
    ):
        db.save_goal(_goal("ga", sample_user["user_id"]))
        db.save_goal(_goal("gb", second_user["user_id"]))
        db.delete_goal("ga")
        assert db.get_goal_by_id("gb") is not None

    def test_expired_bulk_delete_isolated_per_user(
        self, db, sample_user, second_user
    ):
        db.save_goal(_goal("ea", sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("eb", second_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("fa", sample_user["user_id"], deadline=_in_weeks(2)))
        db.delete_expired_goals(user_id=sample_user["user_id"])
        assert db.get_goal_by_id("ea") is None   # deleted
        assert db.get_goal_by_id("eb") is not None  # second user untouched
        assert db.get_goal_by_id("fa") is not None  # future goal untouched

    def test_get_expired_goals_per_user_correct(
        self, db, sample_user, second_user
    ):
        db.save_goal(_goal("ea", sample_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("eb", second_user["user_id"], deadline=_yesterday()))
        db.save_goal(_goal("ec", second_user["user_id"], deadline=_weeks_ago(3)))
        exp_u1 = db.get_expired_goals(user_id=sample_user["user_id"])
        exp_u2 = db.get_expired_goals(user_id=second_user["user_id"])
        assert len(exp_u1) == 1
        assert len(exp_u2) == 2

    def test_two_users_cascade_independent(self, db, sample_user, second_user):
        db.save_goal(_goal("ga", sample_user["user_id"]))
        db.save_goal(_goal("gb", second_user["user_id"]))
        _save_videos(db, "ga", count=2)
        _save_videos(db, "gb", count=3)
        _save_articles(db, "ga", count=1)
        _save_articles(db, "gb", count=4)
        db.delete_goal("ga")
        assert db.get_videos_by_goal("ga") == []
        assert db.get_articles_by_goal("ga") == []
        assert len(db.get_videos_by_goal("gb")) == 3
        assert len(db.get_articles_by_goal("gb")) == 4
