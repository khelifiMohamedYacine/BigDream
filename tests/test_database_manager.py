"""
Tests for DatabaseManager — every method, every edge case.
Covers: user CRUD, authentication, password hashing/reset, token blacklist,
goal/plan/task management, video/article storage, audit log, system stats.
"""
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from backend.database_manager import DatabaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_goal(user_id="u1", goal_id="g1", deadline_offset_days=60):
    deadline = (datetime.now() + timedelta(days=deadline_offset_days)).strftime("%Y-%m-%d")
    return {
        "id": goal_id,
        "user_id": user_id,
        "title": "Learn Python",
        "description": "Python basics",
        "status": "pending",
        "progress": 0.0,
        "deadline": deadline,
        "created_at": datetime.now().isoformat(),
        "total_weeks": 8,
    }


def _make_plan():
    return {
        "goal": "Learn Python",
        "total_weeks": 1,
        "weekly_breakdown": [
            {
                "week": 1,
                "theme": "Basics",
                "bloom_level": "remember",
                "focus": "Learn variables",
                "learning_objectives": ["Understand variables", "Use print()"],
                "practice_exercises": ["Hello world", "Number game"],
                "spaced_review": [],
                "milestone_project": None,
                "psychological_hook": "Let's go!",
                "explanation": "Week 1",
                "videos_needed": 2,
                "articles_needed": 2,
                "status": "pending_content",
            }
        ],
    }


# ===========================================================================
# User creation
# ===========================================================================

class TestCreateUser:
    def test_returns_sanitized_dict(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass123")
        assert isinstance(user, dict)
        assert "password_hash" not in user

    def test_stores_name_email_role(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass123")
        assert user["name"] == "Alice"
        assert user["email"] == "alice@test.com"
        assert user["role"] == "user"

    def test_admin_role_is_stored(self, db):
        user = db.create_user("Admin", "admin@test.com", "pass", role="admin")
        assert user["role"] == "admin"

    def test_user_is_active_by_default(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        stored = db._read_json(db.users_file)
        assert stored[user["user_id"]]["is_active"] is True

    def test_duplicate_email_raises_value_error(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        with pytest.raises(ValueError, match="already registered"):
            db.create_user("Alice2", "alice@test.com", "pass2")

    def test_duplicate_email_case_insensitive(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        with pytest.raises(ValueError):
            db.create_user("Alice2", "ALICE@TEST.COM", "pass2")

    def test_persists_to_users_file(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        raw = db._read_json(db.users_file)
        assert len(raw) == 1

    def test_initializes_stats_record(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        stats = db._read_json(db.user_stats_file)
        assert len(stats) == 1

    def test_user_has_unique_id(self, db):
        u1 = db.create_user("Alice", "a@test.com", "pass")
        u2 = db.create_user("Bob", "b@test.com", "pass")
        assert u1["user_id"] != u2["user_id"]

    def test_handle_generated_from_name(self, db):
        user = db.create_user("Alice Smith", "alice@test.com", "pass")
        assert "user_id" in user
        # handle is generated internally; just verify it exists in raw data
        raw = db._read_json(db.users_file)
        assert raw[user["user_id"]]["handle"] != ""


# ===========================================================================
# Authentication
# ===========================================================================

class TestAuthenticateUser:
    def test_correct_credentials_returns_user(self, db):
        db.create_user("Alice", "alice@test.com", "pass123")
        user = db.authenticate_user("alice@test.com", "pass123")
        assert user is not None
        assert user["email"] == "alice@test.com"

    def test_wrong_password_returns_none(self, db):
        db.create_user("Alice", "alice@test.com", "pass123")
        assert db.authenticate_user("alice@test.com", "wrong") is None

    def test_unknown_email_returns_none(self, db):
        assert db.authenticate_user("nobody@test.com", "pass") is None

    def test_case_insensitive_email(self, db):
        db.create_user("Alice", "alice@test.com", "pass123")
        user = db.authenticate_user("ALICE@TEST.COM", "pass123")
        assert user is not None

    def test_updates_last_login(self, db):
        db.create_user("Alice", "alice@test.com", "pass123")
        db.authenticate_user("alice@test.com", "pass123")
        raw = db._read_json(db.users_file)
        u = list(raw.values())[0]
        assert u["last_login"] is not None

    def test_deactivated_account_raises(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass123")
        db.deactivate_user(user["user_id"])
        with pytest.raises(ValueError, match="deactivated"):
            db.authenticate_user("alice@test.com", "pass123")

    def test_result_does_not_contain_password_hash(self, db):
        db.create_user("Alice", "alice@test.com", "pass123")
        user = db.authenticate_user("alice@test.com", "pass123")
        assert "password_hash" not in user


# ===========================================================================
# Password hashing
# ===========================================================================

class TestPasswordHashing:
    def test_hashed_is_not_plaintext(self, db):
        assert db.hash_password("secret") != "secret"

    def test_verify_correct_password(self, db):
        h = db.hash_password("secret")
        assert db.verify_password("secret", h) is True

    def test_verify_wrong_password(self, db):
        h = db.hash_password("secret")
        assert db.verify_password("wrong", h) is False

    def test_same_password_different_hashes(self, db):
        # bcrypt salts are random
        h1 = db.hash_password("same")
        h2 = db.hash_password("same")
        assert h1 != h2


# ===========================================================================
# Password reset
# ===========================================================================

class TestPasswordReset:
    def test_create_reset_token_returns_6_digit_code(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        code = db.create_reset_token("alice@test.com")
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()

    def test_create_reset_token_unknown_email_returns_none(self, db):
        assert db.create_reset_token("nobody@test.com") is None

    def test_reset_password_with_valid_token_returns_true(self, db):
        db.create_user("Alice", "alice@test.com", "old")
        code = db.create_reset_token("alice@test.com")
        assert db.reset_password_with_token(code, "newpass123") is True

    def test_reset_password_actually_changes_password(self, db):
        db.create_user("Alice", "alice@test.com", "old")
        code = db.create_reset_token("alice@test.com")
        db.reset_password_with_token(code, "newpass123")
        user = db.authenticate_user("alice@test.com", "newpass123")
        assert user is not None

    def test_old_password_no_longer_works_after_reset(self, db):
        db.create_user("Alice", "alice@test.com", "old")
        code = db.create_reset_token("alice@test.com")
        db.reset_password_with_token(code, "newpass123")
        assert db.authenticate_user("alice@test.com", "old") is None

    def test_invalid_code_returns_false(self, db):
        assert db.reset_password_with_token("000000", "newpass") is False

    def test_expired_token_returns_false(self, db):
        db.create_user("Alice", "alice@test.com", "old")
        code = db.create_reset_token("alice@test.com")
        tokens = db._read_json(db.reset_tokens_file)
        tokens[code]["expires_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        db._write_json(db.reset_tokens_file, tokens)
        assert db.reset_password_with_token(code, "newpass") is False

    def test_token_deleted_after_successful_reset(self, db):
        db.create_user("Alice", "alice@test.com", "old")
        code = db.create_reset_token("alice@test.com")
        db.reset_password_with_token(code, "newpass123")
        tokens = db._read_json(db.reset_tokens_file)
        assert code not in tokens

    def test_expired_token_deleted_from_store(self, db):
        db.create_user("Alice", "alice@test.com", "old")
        code = db.create_reset_token("alice@test.com")
        tokens = db._read_json(db.reset_tokens_file)
        tokens[code]["expires_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        db._write_json(db.reset_tokens_file, tokens)
        db.reset_password_with_token(code, "newpass")
        tokens = db._read_json(db.reset_tokens_file)
        assert code not in tokens


# ===========================================================================
# Token blacklist
# ===========================================================================

class TestTokenBlacklist:
    def test_fresh_token_not_blacklisted(self, db):
        assert db.is_token_blacklisted("tok123") is False

    def test_blacklisted_token_is_detected(self, db):
        db.blacklist_token("tok123")
        assert db.is_token_blacklisted("tok123") is True

    def test_blacklist_twice_no_duplicate(self, db):
        db.blacklist_token("tok123")
        db.blacklist_token("tok123")
        bl = db._read_json(db.tokens_blacklist_file)
        assert bl.count("tok123") == 1

    def test_other_tokens_not_affected(self, db):
        db.blacklist_token("tokA")
        assert db.is_token_blacklisted("tokB") is False

    def test_logout_user_blacklists_token(self, db):
        db.logout_user("mytoken")
        assert db.is_token_blacklisted("mytoken") is True


# ===========================================================================
# User retrieval and updates
# ===========================================================================

class TestUserRetrieval:
    def test_get_user_by_id(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        found = db.get_user_by_id(user["user_id"])
        assert found["user_id"] == user["user_id"]

    def test_get_user_by_id_nonexistent(self, db):
        assert db.get_user_by_id("no-such-id") is None

    def test_get_user_by_id_no_password_hash(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        found = db.get_user_by_id(user["user_id"])
        assert "password_hash" not in found

    def test_get_user_by_email(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        found = db.get_user_by_email("alice@test.com")
        assert found is not None

    def test_get_user_by_email_case_insensitive(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        found = db.get_user_by_email("ALICE@TEST.COM")
        assert found is not None

    def test_get_user_by_email_nonexistent(self, db):
        assert db.get_user_by_email("nobody@test.com") is None

    def test_get_all_users_returns_list(self, db):
        db.create_user("Alice", "a@test.com", "pass")
        db.create_user("Bob", "b@test.com", "pass")
        users = db.get_all_users()
        assert len(users) == 2

    def test_get_all_users_empty_db(self, db):
        assert db.get_all_users() == []


class TestUserUpdates:
    def test_update_profile_bio(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_profile(user["user_id"], {"bio": "Python dev"})
        found = db.get_user_by_id(user["user_id"])
        assert found["bio"] == "Python dev"

    def test_update_profile_name(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_profile(user["user_id"], {"name": "Alice Updated"})
        found = db.get_user_by_id(user["user_id"])
        assert found["name"] == "Alice Updated"

    def test_update_profile_disallowed_fields_ignored(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_profile(user["user_id"], {"role": "admin", "email": "evil@test.com"})
        found = db.get_user_by_id(user["user_id"])
        assert found["role"] == "user"

    def test_update_profile_nonexistent_user_raises(self, db):
        with pytest.raises(ValueError):
            db.update_user_profile("no-such-id", {"bio": "x"})

    def test_change_password_correct_old(self, db):
        user = db.create_user("Alice", "alice@test.com", "old")
        db.change_password(user["user_id"], "old", "newpass123")
        assert db.authenticate_user("alice@test.com", "newpass123") is not None

    def test_change_password_wrong_old_raises(self, db):
        user = db.create_user("Alice", "alice@test.com", "old")
        with pytest.raises(ValueError, match="incorrect"):
            db.change_password(user["user_id"], "wrong", "new")

    def test_update_user_role_to_admin(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_role(user["user_id"], "admin")
        found = db.get_user_by_id(user["user_id"])
        assert found["role"] == "admin"

    def test_update_user_preferences(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_preferences(user["user_id"], {"email_notifications": False})
        raw = db._read_json(db.users_file)
        # Preferences are stored directly on the user object (not nested)
        assert raw[user["user_id"]].get("email_notifications") is False


# ===========================================================================
# Account lifecycle: deactivate / reactivate / delete
# ===========================================================================

class TestAccountLifecycle:
    def test_deactivate_prevents_login(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.deactivate_user(user["user_id"])
        with pytest.raises(ValueError, match="deactivated"):
            db.authenticate_user("alice@test.com", "pass")

    def test_reactivate_allows_login(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.deactivate_user(user["user_id"])
        db.reactivate_user(user["user_id"])
        assert db.authenticate_user("alice@test.com", "pass") is not None

    def test_delete_user_removes_record(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        assert db.get_user_by_id(user["user_id"]) is None

    def test_delete_user_returns_true(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        assert db.delete_user(user["user_id"]) is True

    def test_delete_nonexistent_user_returns_false(self, db):
        assert db.delete_user("no-such-id") is False

    def test_delete_user_removes_from_users_file(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        raw = db._read_json(db.users_file)
        assert user["user_id"] not in raw

    def test_deleted_account_cannot_login(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        result = db.authenticate_user("alice@test.com", "pass")
        assert result is None


# ===========================================================================
# Goal management
# ===========================================================================

class TestGoalManagement:
    def test_save_goal_persists(self, db):
        goal = _make_goal()
        db.save_goal(goal)
        raw = db._read_json(db.goals_file)
        assert len(raw) == 1

    def test_get_goal_by_id_found(self, db):
        db.save_goal(_make_goal())
        found = db.get_goal_by_id("g1")
        assert found is not None
        assert found["id"] == "g1"

    def test_get_goal_by_id_not_found(self, db):
        assert db.get_goal_by_id("nonexistent") is None

    def test_get_user_goals_filters_by_user(self, db):
        db.save_goal(_make_goal("user1", "g1"))
        db.save_goal(_make_goal("user2", "g2"))
        db.save_goal(_make_goal("user1", "g3"))
        result = db.get_user_goals("user1")
        assert len(result) == 2
        assert all(g["user_id"] == "user1" for g in result)

    def test_get_user_goals_empty(self, db):
        assert db.get_user_goals("nobody") == []

    def test_save_learning_plan_links_to_goal(self, db):
        db.save_goal(_make_goal())
        plan = _make_plan()
        db.save_learning_plan("g1", plan)
        goal = db.get_goal_by_id("g1")
        assert goal["plan"] == plan

    def test_mark_goal_complete_sets_flag(self, db):
        db.save_goal(_make_goal("u1", "g1"))
        db.mark_goal_complete("u1", "g1")
        goal = db.get_goal_by_id("g1")
        assert goal["completed"] is True

    def test_mark_goal_complete_sets_completed_at(self, db):
        db.save_goal(_make_goal("u1", "g1"))
        db.mark_goal_complete("u1", "g1")
        goal = db.get_goal_by_id("g1")
        assert goal.get("completed_at") is not None

    def test_goal_with_past_deadline_still_exists(self, db):
        """Goals are NOT auto-deleted by the database layer — business logic owns that."""
        goal = _make_goal(deadline_offset_days=-10)  # past deadline
        db.save_goal(goal)
        assert db.get_goal_by_id("g1") is not None


# ===========================================================================
# Task management
# ===========================================================================

class TestTaskManagement:
    def _setup_goal_with_plan(self, db, user_id="u1", goal_id="g1"):
        goal = _make_goal(user_id, goal_id)
        goal["plan"] = _make_plan()
        db.save_goal(goal)
        return goal

    def test_get_all_tasks_returns_tasks_when_plan_exists(self, db):
        self._setup_goal_with_plan(db)
        tasks = db.get_all_tasks_for_goal("g1")
        assert len(tasks) > 0

    def test_get_all_tasks_empty_when_no_plan(self, db):
        db.save_goal(_make_goal())
        assert db.get_all_tasks_for_goal("g1") == []

    def test_get_all_tasks_empty_for_nonexistent_goal(self, db):
        assert db.get_all_tasks_for_goal("no-such-goal") == []

    def test_tasks_have_required_fields(self, db):
        self._setup_goal_with_plan(db)
        tasks = db.get_all_tasks_for_goal("g1")
        for t in tasks:
            assert "id" in t
            assert "week" in t
            assert "type" in t
            assert "status" in t

    def test_task_default_status_is_pending(self, db):
        self._setup_goal_with_plan(db)
        tasks = db.get_all_tasks_for_goal("g1")
        assert all(t["status"] == "pending" for t in tasks)

    def test_update_task_status_pending_to_in_progress(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        result = db.update_task_status("g1", task_id, "in_progress")
        assert result["status"] == "in_progress"

    def test_update_task_status_in_progress_to_completed(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        db.update_task_status("g1", task_id, "in_progress")
        result = db.update_task_status("g1", task_id, "completed")
        assert result["status"] == "completed"

    def test_update_task_status_invalid_transition_raises(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        # pending → completed is not allowed directly
        with pytest.raises(ValueError):
            db.update_task_status("g1", task_id, "completed")

    def test_update_task_status_invalid_status_raises(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        with pytest.raises(ValueError):
            db.update_task_status("g1", task_id, "flying")

    def test_update_task_status_nonexistent_goal_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_task_status("no-goal", "t1", "in_progress")

    def test_completing_all_tasks_marks_goal_completed(self, db):
        self._setup_goal_with_plan(db)
        tasks = db.get_all_tasks_for_goal("g1")
        for t in tasks:
            db.update_task_status("g1", t["id"], "in_progress")
            db.update_task_status("g1", t["id"], "completed")
        goal = db.get_goal_by_id("g1")
        assert goal["status"] == "completed"

    def test_task_progress_recomputed_after_update(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        db.update_task_status("g1", task_id, "in_progress")
        db.update_task_status("g1", task_id, "completed")
        goal = db.get_goal_by_id("g1")
        assert goal["progress"] > 0

    def test_update_task_stores_notes(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        result = db.update_task_status("g1", task_id, "in_progress", notes="Working on it")
        assert result["notes"] == "Working on it"

    def test_completed_task_has_completed_at(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        db.update_task_status("g1", task_id, "in_progress")
        result = db.update_task_status("g1", task_id, "completed")
        assert result["completed_at"] is not None

    def test_get_task_completions_returns_dict(self, db):
        self._setup_goal_with_plan(db)
        completions = db.get_task_completions("g1")
        assert isinstance(completions, dict)

    def test_get_task_completions_nonexistent_goal(self, db):
        assert db.get_task_completions("no-such") == {}

    def test_skipping_task_is_allowed_from_pending(self, db):
        self._setup_goal_with_plan(db)
        task_id = db.get_all_tasks_for_goal("g1")[0]["id"]
        result = db.update_task_status("g1", task_id, "skipped")
        assert result["status"] == "skipped"


# ===========================================================================
# Videos and articles
# ===========================================================================

class TestVideosAndArticles:
    def test_save_and_get_videos(self, db):
        vids = [{"id": "v1", "title": "Intro", "url": "http://yt.com/v1"}]
        db.save_youtube_videos_for_goal("g1", vids)
        result = db.get_videos_by_goal("g1")
        assert len(result) == 1
        assert result[0]["title"] == "Intro"

    def test_video_gets_goal_id_stamped(self, db):
        db.save_youtube_videos_for_goal("g1", [{"id": "v1"}])
        result = db.get_videos_by_goal("g1")
        assert result[0]["goal_id"] == "g1"

    def test_get_videos_empty_for_unknown_goal(self, db):
        assert db.get_videos_by_goal("unknown") == []

    def test_saving_videos_replaces_old_ones(self, db):
        db.save_youtube_videos_for_goal("g1", [{"id": "v1"}])
        db.save_youtube_videos_for_goal("g1", [{"id": "v2"}, {"id": "v3"}])
        result = db.get_videos_by_goal("g1")
        assert len(result) == 2
        ids = [v["id"] for v in result]
        assert "v1" not in ids

    def test_get_all_videos(self, db):
        db.save_youtube_videos_for_goal("g1", [{"id": "v1"}])
        db.save_youtube_videos_for_goal("g2", [{"id": "v2"}])
        assert len(db.get_all_videos()) == 2

    def test_save_and_get_articles(self, db):
        arts = [{"id": "a1", "title": "Python Guide", "url": "http://dev.to/a1"}]
        db.save_articles_for_goal("g1", arts)
        result = db.get_articles_by_goal("g1")
        assert len(result) == 1
        assert result[0]["title"] == "Python Guide"

    def test_article_gets_goal_id_stamped(self, db):
        db.save_articles_for_goal("g1", [{"id": "a1"}])
        result = db.get_articles_by_goal("g1")
        assert result[0]["goal_id"] == "g1"

    def test_get_articles_empty_for_unknown_goal(self, db):
        assert db.get_articles_by_goal("unknown") == []

    def test_saving_articles_replaces_old_ones(self, db):
        db.save_articles_for_goal("g1", [{"id": "a1"}])
        db.save_articles_for_goal("g1", [{"id": "a2"}])
        result = db.get_articles_by_goal("g1")
        assert len(result) == 1
        assert result[0]["id"] == "a2"

    def test_get_all_articles(self, db):
        db.save_articles_for_goal("g1", [{"id": "a1"}])
        db.save_articles_for_goal("g2", [{"id": "a2"}])
        assert len(db.get_all_articles()) == 2


# ===========================================================================
# User statistics
# ===========================================================================

class TestUserStats:
    def test_get_user_stats_returns_dict(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        stats = db.get_user_stats(user["user_id"])
        assert isinstance(stats, dict)

    def test_get_user_stats_nonexistent_user(self, db):
        stats = db.get_user_stats("no-such-id")
        assert stats == {} or isinstance(stats, dict)

    def test_update_user_stats_increments(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_stats(user["user_id"], "goals_completed")
        stats = db.get_user_stats(user["user_id"])
        assert stats.get("goals_completed", 0) >= 1


# ===========================================================================
# Audit log and system stats
# ===========================================================================

class TestAuditAndSystemStats:
    def test_audit_log_populated_on_user_create(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        log = db.get_audit_log()
        assert len(log) > 0

    def test_audit_log_has_action_field(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        log = db.get_audit_log()
        assert "action" in log[0]

    def test_audit_log_respects_limit(self, db):
        for i in range(5):
            db.create_user(f"User{i}", f"u{i}@test.com", "pass")
        log = db.get_audit_log(limit=2)
        assert len(log) <= 2

    def test_get_system_stats_has_total_users(self, db):
        db.create_user("Alice", "a@test.com", "pass")
        stats = db.get_system_stats()
        assert stats["users"]["total"] == 1

    def test_get_system_stats_has_total_goals(self, db):
        db.save_goal(_make_goal())
        stats = db.get_system_stats()
        assert stats["goals"]["total"] >= 1


# ===========================================================================
# File-level resilience
# ===========================================================================

class TestFileResilience:
    def test_read_corrupt_list_file_returns_empty_list(self, db):
        with open(db.goals_file, "w") as f:
            f.write("{bad json")
        result = db._read_json(db.goals_file)
        assert result == []

    def test_read_corrupt_dict_file_returns_empty_dict(self, db):
        with open(db.users_file, "w") as f:
            f.write("not json at all")
        result = db._read_json(db.users_file)
        assert result == {}


# ===========================================================================
# Quiz management
# ===========================================================================

class TestQuizManagement:
    def test_save_goal_quiz_includes_attempts_and_failed(self, db):
        goal = _make_goal()
        db.save_goal(goal)
        questions = [{"question": "Q1", "options": {"A": "a"}, "correct": "A"}]
        db.save_goal_quiz("g1", "u1", questions)
        quiz = db.get_goal_quiz("g1", "u1")
        assert quiz["questions"] == questions
        assert quiz["attempts"] == 0
        assert quiz["permanently_failed"] is False
        assert quiz["next_attempt_at"] is None

    def test_can_take_quiz_progress_incomplete(self, db):
        goal = _make_goal()
        db.save_goal(goal)
        db.save_goal_quiz("g1", "u1", [])
        result = db.can_take_quiz("g1", "u1")
        assert result["can_take"] is False
        assert result["reason"] == "Progress not complete"

    def test_can_take_quiz_after_pass(self, db):
        goal = _make_goal()
        goal["progress"] = 100.0
        db.save_goal(goal)
        db.save_goal_quiz("g1", "u1", [])
        quiz = db.get_goal_quiz("g1", "u1")
        quiz["passed"] = True
        goals = db._read_json(db.goals_file)
        for g in goals:
            if g["id"] == "g1":
                g["quiz"] = quiz
        db._write_json(db.goals_file, goals)
        result = db.can_take_quiz("g1", "u1")
        assert result["can_take"] is False
        assert result["reason"] == "Quiz already passed"

    def test_can_take_quiz_when_permanently_failed(self, db):
        goal = _make_goal()
        goal["progress"] = 100.0
        db.save_goal(goal)
        db.save_goal_quiz("g1", "u1", [])
        quiz = db.get_goal_quiz("g1", "u1")
        quiz["permanently_failed"] = True
        goals = db._read_json(db.goals_file)
        for g in goals:
            if g["id"] == "g1":
                g["quiz"] = quiz
        db._write_json(db.goals_file, goals)
        result = db.can_take_quiz("g1", "u1")
        assert result["can_take"] is False
        assert result["reason"] == "Quiz permanently failed"

    def test_submit_quiz_attempt_passes_and_completes_goal(self, db):
        goal = _make_goal()
        goal["progress"] = 100.0
        db.save_goal(goal)
        questions = [
            {"question": "Q1", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "A"},
            {"question": "Q2", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "B"},
        ]
        db.save_goal_quiz("g1", "u1", questions)
        result = db.submit_quiz_attempt("g1", "u1", {1: "A", 2: "B"})
        assert result["passed"] is True
        assert result["score"] == 2
        assert result["completed"] is True
        assert result["deleted"] is True

    def test_submit_quiz_attempt_fails_allows_retake_tomorrow(self, db):
        goal = _make_goal()
        goal["progress"] = 100.0
        db.save_goal(goal)
        questions = [
            {"question": "Q1", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "A"},
        ]
        db.save_goal_quiz("g1", "u1", questions)
        result = db.submit_quiz_attempt("g1", "u1", {1: "B"})
        assert result["passed"] is False
        assert result["score"] == 0
        assert result["attempts"] == 1
        assert result["permanently_failed"] is False
        assert result["next_attempt_at"] is not None

    def test_submit_quiz_attempt_second_fail_permanently_fails(self, db):
        goal = _make_goal()
        goal["progress"] = 100.0
        db.save_goal(goal)
        questions = [
            {"question": "Q1", "options": {"A": "a", "B": "b", "C": "c", "D": "d"}, "correct": "A"},
        ]
        db.save_goal_quiz("g1", "u1", questions)
        # first fail
        db.submit_quiz_attempt("g1", "u1", {1: "B"})
        # second fail (pretend retake window passed by resetting next_attempt_at)
        quiz = db.get_goal_quiz("g1", "u1")
        quiz["next_attempt_at"] = (datetime.now() - timedelta(hours=1)).isoformat()
        goals = db._read_json(db.goals_file)
        for g in goals:
            if g["id"] == "g1":
                g["quiz"] = quiz
        db._write_json(db.goals_file, goals)
        result = db.submit_quiz_attempt("g1", "u1", {1: "B"})
        assert result["passed"] is False
        assert result["attempts"] == 2
        assert result["permanently_failed"] is True
        assert result["next_attempt_at"] is None
