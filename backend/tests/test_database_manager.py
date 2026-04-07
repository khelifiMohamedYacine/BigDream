"""
test_database_manager.py
========================
Comprehensive unit tests for DatabaseManager.

Covers:
  - User CRUD (create, read, update, delete)
  - Authentication and deactivation
  - Password hashing and verification
  - Password reset token lifecycle
  - Token blacklist
  - Goal persistence (save, fetch, complete)
  - Task status updates and progress recomputation
  - Video and article storage
  - User stats increments and side-effects
  - System stats aggregation
  - Audit log growth and cap
  - Preference updates

All tests use an isolated temp directory — no shared state.
"""
import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path

from backend.database_manager import DatabaseManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_goal(user_id, goal_id="g1", weeks=8):
    deadline = (datetime.now() + timedelta(weeks=weeks)).strftime("%Y-%m-%d")
    return {
        "id": goal_id,
        "user_id": user_id,
        "title": "Learn Python",
        "description": "Python basics",
        "status": "pending",
        "progress": 0.0,
        "deadline": deadline,
        "created_at": datetime.now().isoformat(),
        "total_weeks": weeks,
        "goal_type": "coding",
    }


def _make_plan(weeks=2):
    """Minimal plan with `weeks` weeks, 2 objectives and 2 exercises each."""
    weekly_breakdown = []
    for w in range(1, weeks + 1):
        weekly_breakdown.append({
            "week": w,
            "theme": f"Week {w} Theme",
            "bloom_level": "remember",
            "focus": f"Focus week {w}",
            "learning_objectives": [f"Objective A week {w}", f"Objective B week {w}"],
            "practice_exercises": [f"Exercise 1 week {w}", f"Exercise 2 week {w}"],
            "spaced_review": [],
            "milestone_project": None,
            "psychological_hook": "Go!",
            "explanation": f"Week {w} explanation",
            "videos_needed": 2,
            "articles_needed": 2,
            "status": "pending_content",
        })
    return {"goal": "Learn Python", "total_weeks": weeks, "weekly_breakdown": weekly_breakdown}


# ===========================================================================
# File initialization
# ===========================================================================

class TestInitialization:
    def test_data_dir_is_created(self, tmp_path):
        target = tmp_path / "mydata"
        DatabaseManager(data_dir=str(target))
        assert target.exists()

    def test_all_json_files_created(self, db):
        assert db.users_file.exists()
        assert db.goals_file.exists()
        assert db.tokens_blacklist_file.exists()
        assert db.audit_log_file.exists()
        assert db.user_stats_file.exists()
        assert db.videos_file.exists()
        assert db.articles_file.exists()
        assert db.reset_tokens_file.exists()

    def test_users_file_initialized_as_dict(self, db):
        data = db._read_json(db.users_file)
        assert isinstance(data, dict)
        assert len(data) == 0

    def test_goals_file_initialized_as_list(self, db):
        data = db._read_json(db.goals_file)
        assert isinstance(data, list)
        assert len(data) == 0

    def test_reinitialize_does_not_overwrite_existing(self, tmp_path):
        """Second DatabaseManager on same dir must keep existing data."""
        db1 = DatabaseManager(data_dir=str(tmp_path))
        db1.create_user("Alice", "alice@test.com", "pass")
        db2 = DatabaseManager(data_dir=str(tmp_path))
        users = db2._read_json(db2.users_file)
        assert len(users) == 1


# ===========================================================================
# User creation
# ===========================================================================

class TestCreateUser:
    def test_returns_dict_with_required_fields(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass123")
        for field in ("user_id", "name", "email", "role", "handle",
                      "is_active", "created_at"):
            assert field in user, f"Missing field: {field}"

    def test_password_hash_not_in_sanitized_result(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass123")
        assert "password_hash" not in user

    def test_email_stored_lowercase(self, db):
        user = db.create_user("Alice", "ALICE@TEST.COM", "pass")
        assert user["email"] == "alice@test.com"

    def test_default_role_is_user(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        assert user["role"] == "user"

    def test_admin_role_stored_correctly(self, db):
        user = db.create_user("Admin", "admin@test.com", "pass", role="admin")
        assert user["role"] == "admin"

    def test_user_active_by_default(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        raw = db._read_json(db.users_file)
        assert raw[user["user_id"]]["is_active"] is True

    def test_duplicate_email_raises_value_error(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        with pytest.raises(ValueError, match="already registered"):
            db.create_user("Alice2", "alice@test.com", "pass2")

    def test_duplicate_email_case_insensitive(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        with pytest.raises(ValueError):
            db.create_user("Bob", "ALICE@TEST.COM", "pass")

    def test_two_users_have_different_ids(self, db):
        u1 = db.create_user("Alice", "a@test.com", "pass")
        u2 = db.create_user("Bob", "b@test.com", "pass")
        assert u1["user_id"] != u2["user_id"]

    def test_persisted_to_disk(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        raw = db._read_json(db.users_file)
        assert len(raw) == 1

    def test_stats_record_created_on_user_creation(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        stats = db._read_json(db.user_stats_file)
        assert user["user_id"] in stats

    def test_audit_log_entry_created(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        log = db.get_audit_log()
        actions = [e["action"] for e in log]
        assert "user_created" in actions

    def test_handle_generated(self, db):
        user = db.create_user("Alice Smith", "alice@test.com", "pass")
        raw = db._read_json(db.users_file)
        handle = raw[user["user_id"]]["handle"]
        assert handle  # non-empty


# ===========================================================================
# User retrieval
# ===========================================================================

class TestGetUser:
    def test_get_by_id_returns_user(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        fetched = db.get_user_by_id(user["user_id"])
        assert fetched is not None
        assert fetched["email"] == "alice@test.com"

    def test_get_by_id_missing_returns_none(self, db):
        assert db.get_user_by_id("nonexistent-id") is None

    def test_get_by_email_returns_user(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        fetched = db.get_user_by_email("alice@test.com")
        assert fetched is not None

    def test_get_by_email_case_insensitive(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        fetched = db.get_user_by_email("ALICE@TEST.COM")
        assert fetched is not None

    def test_get_by_email_unknown_returns_none(self, db):
        assert db.get_user_by_email("nobody@test.com") is None

    def test_get_by_id_does_not_include_password_hash(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        fetched = db.get_user_by_id(user["user_id"])
        assert "password_hash" not in fetched

    def test_get_all_users_returns_list(self, db):
        db.create_user("Alice", "a@test.com", "pass")
        db.create_user("Bob", "b@test.com", "pass")
        users = db.get_all_users()
        assert isinstance(users, list)
        assert len(users) == 2

    def test_get_all_users_no_password_hash(self, db):
        db.create_user("Alice", "a@test.com", "pass")
        for u in db.get_all_users():
            assert "password_hash" not in u

    def test_get_all_users_empty_db(self, db):
        assert db.get_all_users() == []


# ===========================================================================
# Authentication
# ===========================================================================

class TestAuthenticateUser:
    def test_valid_credentials_return_user(self, db):
        db.create_user("Alice", "alice@test.com", "Pass123!")
        user = db.authenticate_user("alice@test.com", "Pass123!")
        assert user is not None

    def test_wrong_password_returns_none(self, db):
        db.create_user("Alice", "alice@test.com", "Pass123!")
        assert db.authenticate_user("alice@test.com", "WrongPass") is None

    def test_unknown_email_returns_none(self, db):
        assert db.authenticate_user("nobody@test.com", "pass") is None

    def test_email_case_insensitive(self, db):
        db.create_user("Alice", "alice@test.com", "Pass123!")
        user = db.authenticate_user("ALICE@TEST.COM", "Pass123!")
        assert user is not None

    def test_last_login_updated_on_success(self, db):
        db.create_user("Alice", "alice@test.com", "Pass123!")
        db.authenticate_user("alice@test.com", "Pass123!")
        raw = db._read_json(db.users_file)
        u = next(iter(raw.values()))
        assert u["last_login"] is not None

    def test_deactivated_account_raises_value_error(self, db):
        user = db.create_user("Alice", "alice@test.com", "Pass123!")
        db.deactivate_user(user["user_id"])
        with pytest.raises(ValueError, match="deactivated"):
            db.authenticate_user("alice@test.com", "Pass123!")

    def test_result_has_no_password_hash(self, db):
        db.create_user("Alice", "alice@test.com", "Pass123!")
        user = db.authenticate_user("alice@test.com", "Pass123!")
        assert "password_hash" not in user

    def test_login_creates_audit_log_entry(self, db):
        db.create_user("Alice", "alice@test.com", "Pass123!")
        db.authenticate_user("alice@test.com", "Pass123!")
        log = db.get_audit_log()
        actions = [e["action"] for e in log]
        assert "user_login" in actions


# ===========================================================================
# Password hashing
# ===========================================================================

class TestPasswordHashing:
    def test_hash_differs_from_plaintext(self, db):
        assert db.hash_password("secret") != "secret"

    def test_verify_correct_password(self, db):
        h = db.hash_password("secret")
        assert db.verify_password("secret", h) is True

    def test_verify_wrong_password(self, db):
        h = db.hash_password("secret")
        assert db.verify_password("wrong", h) is False

    def test_bcrypt_salts_are_random(self, db):
        # Same password → different hashes every time (bcrypt random salt)
        h1 = db.hash_password("same_password")
        h2 = db.hash_password("same_password")
        assert h1 != h2

    def test_verify_with_second_hash(self, db):
        """Cross-hash verification must work regardless of salt."""
        h = db.hash_password("my_pass")
        assert db.verify_password("my_pass", h) is True


# ===========================================================================
# Change password
# ===========================================================================

class TestChangePassword:
    def test_correct_old_password_returns_true(self, db):
        user = db.create_user("Alice", "alice@test.com", "OldPass1!")
        assert db.change_password(user["user_id"], "OldPass1!", "NewPass2!") is True

    def test_new_password_authenticates(self, db):
        user = db.create_user("Alice", "alice@test.com", "OldPass1!")
        db.change_password(user["user_id"], "OldPass1!", "NewPass2!")
        assert db.authenticate_user("alice@test.com", "NewPass2!") is not None

    def test_old_password_no_longer_works(self, db):
        user = db.create_user("Alice", "alice@test.com", "OldPass1!")
        db.change_password(user["user_id"], "OldPass1!", "NewPass2!")
        assert db.authenticate_user("alice@test.com", "OldPass1!") is None

    def test_wrong_old_password_raises(self, db):
        user = db.create_user("Alice", "alice@test.com", "OldPass1!")
        with pytest.raises(ValueError, match="incorrect"):
            db.change_password(user["user_id"], "WrongOld", "NewPass2!")

    def test_unknown_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.change_password("bad-id", "old", "new")


# ===========================================================================
# Password reset tokens
# ===========================================================================

class TestPasswordResetTokens:
    def test_create_returns_6_digit_string(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        code = db.create_reset_token("alice@test.com")
        assert code is not None
        assert len(code) == 6
        assert code.isdigit()

    def test_unknown_email_returns_none(self, db):
        assert db.create_reset_token("nobody@test.com") is None

    def test_valid_code_resets_password(self, db):
        db.create_user("Alice", "alice@test.com", "OldPass1!")
        code = db.create_reset_token("alice@test.com")
        assert db.reset_password_with_token(code, "NewPass2!") is True

    def test_new_password_can_authenticate(self, db):
        db.create_user("Alice", "alice@test.com", "OldPass1!")
        code = db.create_reset_token("alice@test.com")
        db.reset_password_with_token(code, "NewPass2!")
        assert db.authenticate_user("alice@test.com", "NewPass2!") is not None

    def test_code_deleted_after_use(self, db):
        db.create_user("Alice", "alice@test.com", "OldPass1!")
        code = db.create_reset_token("alice@test.com")
        db.reset_password_with_token(code, "NewPass2!")
        # Using the same code a second time must fail
        assert db.reset_password_with_token(code, "AnotherPass3!") is False

    def test_invalid_code_returns_false(self, db):
        assert db.reset_password_with_token("000000", "newpass") is False

    def test_expired_token_returns_false(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        code = db.create_reset_token("alice@test.com")
        # Manually expire the token
        tokens = db._read_json(db.reset_tokens_file)
        tokens[code]["expires_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        db._write_json(db.reset_tokens_file, tokens)
        assert db.reset_password_with_token(code, "newpass") is False

    def test_expired_token_deleted_after_check(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        code = db.create_reset_token("alice@test.com")
        tokens = db._read_json(db.reset_tokens_file)
        tokens[code]["expires_at"] = (datetime.now() - timedelta(minutes=1)).isoformat()
        db._write_json(db.reset_tokens_file, tokens)
        db.reset_password_with_token(code, "newpass")
        remaining = db._read_json(db.reset_tokens_file)
        assert code not in remaining


# ===========================================================================
# Token blacklist
# ===========================================================================

class TestTokenBlacklist:
    def test_new_token_not_blacklisted(self, db):
        assert db.is_token_blacklisted("some.jwt.token") is False

    def test_blacklisted_token_is_detected(self, db):
        db.blacklist_token("some.jwt.token")
        assert db.is_token_blacklisted("some.jwt.token") is True

    def test_blacklist_token_twice_no_duplicate(self, db):
        db.blacklist_token("tok")
        db.blacklist_token("tok")
        bl = db._read_json(db.tokens_blacklist_file)
        assert bl.count("tok") == 1

    def test_logout_user_blacklists_token(self, db):
        db.logout_user("my.token.here")
        assert db.is_token_blacklisted("my.token.here") is True

    def test_different_tokens_independent(self, db):
        db.blacklist_token("tok1")
        assert db.is_token_blacklisted("tok2") is False


# ===========================================================================
# Profile update
# ===========================================================================

class TestUpdateUserProfile:
    def test_name_updated(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        updated = db.update_user_profile(user["user_id"], {"name": "Alice Updated"})
        assert updated["name"] == "Alice Updated"

    def test_bio_updated(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        updated = db.update_user_profile(user["user_id"], {"bio": "Python developer"})
        assert updated["bio"] == "Python developer"

    def test_handle_updated(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        updated = db.update_user_profile(user["user_id"], {"handle": "NEW-HANDLE"})
        raw = db._read_json(db.users_file)
        assert raw[user["user_id"]]["handle"] == "NEW-HANDLE"

    def test_unknown_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_user_profile("bad-id", {"name": "X"})

    def test_password_hash_not_overwritten(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_profile(user["user_id"], {"password_hash": "INJECTED"})
        # password_hash must stay as bcrypt hash, not the injected value
        raw = db._read_json(db.users_file)
        assert raw[user["user_id"]]["password_hash"] != "INJECTED"

    def test_updated_at_refreshed(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        raw_before = db._read_json(db.users_file)[user["user_id"]]["updated_at"]
        db.update_user_profile(user["user_id"], {"bio": "new"})
        raw_after = db._read_json(db.users_file)[user["user_id"]]["updated_at"]
        assert raw_after >= raw_before


# ===========================================================================
# Role management
# ===========================================================================

class TestRoleManagement:
    def test_update_role_to_admin(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        updated = db.update_user_role(user["user_id"], "admin")
        assert updated["role"] == "admin"

    def test_update_role_to_user(self, db):
        admin = db.create_user("Admin", "admin@test.com", "pass", role="admin")
        updated = db.update_user_role(admin["user_id"], "user")
        assert updated["role"] == "user"

    def test_update_role_unknown_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_user_role("bad-id", "admin")

    def test_role_change_logged_in_audit(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.update_user_role(user["user_id"], "admin")
        log = db.get_audit_log()
        actions = [e["action"] for e in log]
        assert "role_changed" in actions


# ===========================================================================
# Deactivation / reactivation
# ===========================================================================

class TestDeactivationReactivation:
    def test_deactivate_sets_is_active_false(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.deactivate_user(user["user_id"])
        raw = db._read_json(db.users_file)
        assert raw[user["user_id"]]["is_active"] is False

    def test_reactivate_sets_is_active_true(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.deactivate_user(user["user_id"])
        db.reactivate_user(user["user_id"])
        raw = db._read_json(db.users_file)
        assert raw[user["user_id"]]["is_active"] is True

    def test_deactivate_unknown_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.deactivate_user("bad-id")

    def test_reactivate_unknown_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.reactivate_user("bad-id")


# ===========================================================================
# User deletion
# ===========================================================================

class TestDeleteUser:
    def test_delete_existing_user_returns_true(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        assert db.delete_user(user["user_id"]) is True

    def test_deleted_user_no_longer_retrievable(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        assert db.get_user_by_id(user["user_id"]) is None

    def test_delete_unknown_user_returns_false(self, db):
        assert db.delete_user("nonexistent") is False

    def test_stats_record_also_deleted(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        stats = db._read_json(db.user_stats_file)
        assert user["user_id"] not in stats

    def test_delete_creates_audit_log_entry(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        log = db.get_audit_log()
        actions = [e["action"] for e in log]
        assert "user_deleted" in actions

    def test_can_recreate_with_same_email_after_delete(self, db):
        user = db.create_user("Alice", "alice@test.com", "pass")
        db.delete_user(user["user_id"])
        new_user = db.create_user("Alice2", "alice@test.com", "pass2")
        assert new_user is not None


# ===========================================================================
# Goal persistence
# ===========================================================================

class TestGoalPersistence:
    def test_save_goal_returns_id(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        gid = db.save_goal(goal)
        assert gid == "g1"

    def test_get_goal_by_id(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        db.save_goal(goal)
        fetched = db.get_goal_by_id("g1")
        assert fetched is not None
        assert fetched["id"] == "g1"

    def test_get_goal_by_id_missing_returns_none(self, db):
        assert db.get_goal_by_id("bad-id") is None

    def test_get_user_goals_returns_own_goals(self, db, sample_user, second_user):
        db.save_goal(_make_goal(sample_user["user_id"], "ga"))
        db.save_goal(_make_goal(sample_user["user_id"], "gb"))
        db.save_goal(_make_goal(second_user["user_id"], "gc"))
        goals = db.get_user_goals(sample_user["user_id"])
        assert len(goals) == 2
        for g in goals:
            assert g["user_id"] == sample_user["user_id"]

    def test_get_user_goals_empty(self, db, sample_user):
        assert db.get_user_goals(sample_user["user_id"]) == []

    def test_save_goal_increments_user_stat(self, db, sample_user):
        before = db.get_user_stats(sample_user["user_id"]).get("goals_created", 0)
        db.save_goal(_make_goal(sample_user["user_id"]))
        after = db.get_user_stats(sample_user["user_id"])["goals_created"]
        assert after == before + 1

    def test_mark_goal_complete(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        db.save_goal(goal)
        db.mark_goal_complete(sample_user["user_id"], "g1")
        fetched = db.get_goal_by_id("g1")
        assert fetched["completed"] is True

    def test_mark_goal_complete_sets_completed_at(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        db.save_goal(goal)
        db.mark_goal_complete(sample_user["user_id"], "g1")
        fetched = db.get_goal_by_id("g1")
        assert "completed_at" in fetched

    def test_mark_goal_complete_increments_stat(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        db.save_goal(goal)
        before = db.get_user_stats(sample_user["user_id"]).get("goals_completed", 0)
        db.mark_goal_complete(sample_user["user_id"], "g1")
        after = db.get_user_stats(sample_user["user_id"])["goals_completed"]
        assert after == before + 1

    def test_save_learning_plan(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        db.save_goal(goal)
        plan = _make_plan(weeks=2)
        db.save_learning_plan("g1", plan)
        fetched = db.get_goal_by_id("g1")
        assert fetched["plan"]["total_weeks"] == 2

    def test_plan_generated_at_set(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"])
        db.save_goal(goal)
        db.save_learning_plan("g1", _make_plan())
        fetched = db.get_goal_by_id("g1")
        assert "plan_generated_at" in fetched


# ===========================================================================
# Task management
# ===========================================================================

class TestTaskManagement:
    def _setup_goal_with_plan(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"], goal_id="tg1", weeks=2)
        goal["plan"] = _make_plan(weeks=2)
        db.save_goal(goal)
        return goal

    def test_get_task_completions_empty_for_new_goal(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        completions = db.get_task_completions("tg1")
        assert completions == {}

    def test_update_task_status_valid_transition(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        tasks = db.get_all_tasks_for_goal("tg1")
        task_id = tasks[0]["id"]
        result = db.update_task_status("tg1", task_id, "in_progress")
        assert result["status"] == "in_progress"

    def test_update_task_status_complete(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        tasks = db.get_all_tasks_for_goal("tg1")
        task_id = tasks[0]["id"]
        db.update_task_status("tg1", task_id, "in_progress")
        result = db.update_task_status("tg1", task_id, "completed")
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_invalid_transition_raises_value_error(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        tasks = db.get_all_tasks_for_goal("tg1")
        task_id = tasks[0]["id"]
        # pending → completed is not allowed directly
        with pytest.raises(ValueError):
            db.update_task_status("tg1", task_id, "completed")

    def test_goal_not_found_raises_value_error(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_task_status("bad-goal", "bad-task", "in_progress")

    def test_goal_progress_recomputed_on_content_consumption(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        # Goal progress is now driven by watched videos and read articles
        db.mark_video_watched("tg1", sample_user["user_id"], "https://youtube.com/v1")
        db.mark_article_read("tg1", sample_user["user_id"], "https://example.com/a1")
        goal = db.get_goal_by_id("tg1")
        # 2 weeks => 4 videos + 4 articles = 8 total. 2 consumed => 25.0%
        assert goal["progress"] == 25.0

    def test_get_all_tasks_for_goal_returns_all(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        tasks = db.get_all_tasks_for_goal("tg1")
        # 2 weeks × (2 objectives + 2 exercises) = 8 tasks
        assert len(tasks) == 8

    def test_get_all_tasks_for_missing_goal_returns_empty(self, db):
        assert db.get_all_tasks_for_goal("missing") == []

    def test_get_all_tasks_for_goal_without_plan_returns_empty(self, db, sample_user):
        goal = _make_goal(sample_user["user_id"], goal_id="noplan")
        db.save_goal(goal)
        assert db.get_all_tasks_for_goal("noplan") == []

    def test_completion_persisted_after_re_extraction(self, db, sample_user):
        self._setup_goal_with_plan(db, sample_user)
        tasks = db.get_all_tasks_for_goal("tg1")
        task_id = tasks[0]["id"]
        db.update_task_status("tg1", task_id, "in_progress")
        db.update_task_status("tg1", task_id, "completed")
        # Re-fetch; completion must still be there
        tasks2 = db.get_all_tasks_for_goal("tg1")
        t = next(t for t in tasks2 if t["id"] == task_id)
        assert t["status"] == "completed"


# ===========================================================================
# Video and article storage
# ===========================================================================

class TestVideoAndArticleStorage:
    def test_save_and_retrieve_videos(self, db):
        videos = [{"title": "Python Basics", "url": "https://youtube.com/1"}]
        db.save_youtube_videos_for_goal("goal1", videos)
        result = db.get_videos_by_goal("goal1")
        assert len(result) == 1
        assert result[0]["title"] == "Python Basics"

    def test_saved_at_timestamp_added(self, db):
        db.save_youtube_videos_for_goal("goal1", [{"title": "Vid"}])
        videos = db.get_videos_by_goal("goal1")
        assert "saved_at" in videos[0]

    def test_goal_id_injected_into_video(self, db):
        db.save_youtube_videos_for_goal("goal1", [{"title": "Vid"}])
        videos = db.get_videos_by_goal("goal1")
        assert videos[0]["goal_id"] == "goal1"

    def test_re_saving_replaces_old_videos(self, db):
        db.save_youtube_videos_for_goal("goal1", [{"title": "Old"}])
        db.save_youtube_videos_for_goal("goal1", [{"title": "New1"}, {"title": "New2"}])
        result = db.get_videos_by_goal("goal1")
        assert len(result) == 2
        assert all(v["title"] != "Old" for v in result)

    def test_videos_for_different_goals_isolated(self, db):
        db.save_youtube_videos_for_goal("goal1", [{"title": "A"}])
        db.save_youtube_videos_for_goal("goal2", [{"title": "B"}])
        assert len(db.get_videos_by_goal("goal1")) == 1
        assert len(db.get_videos_by_goal("goal2")) == 1

    def test_get_videos_empty(self, db):
        assert db.get_videos_by_goal("nonexistent") == []

    def test_save_and_retrieve_articles(self, db):
        articles = [{"title": "Python Guide", "url": "https://medium.com/1"}]
        db.save_articles_for_goal("goal1", articles)
        result = db.get_articles_by_goal("goal1")
        assert len(result) == 1
        assert result[0]["title"] == "Python Guide"

    def test_re_saving_replaces_old_articles(self, db):
        db.save_articles_for_goal("goal1", [{"title": "Old"}])
        db.save_articles_for_goal("goal1", [{"title": "New"}])
        result = db.get_articles_by_goal("goal1")
        assert len(result) == 1
        assert result[0]["title"] == "New"

    def test_get_articles_empty(self, db):
        assert db.get_articles_by_goal("nonexistent") == []

    def test_get_all_videos(self, db):
        db.save_youtube_videos_for_goal("g1", [{"title": "A"}])
        db.save_youtube_videos_for_goal("g2", [{"title": "B"}])
        all_vids = db.get_all_videos()
        assert len(all_vids) == 2

    def test_get_all_articles(self, db):
        db.save_articles_for_goal("g1", [{"title": "X"}])
        db.save_articles_for_goal("g2", [{"title": "Y"}])
        all_arts = db.get_all_articles()
        assert len(all_arts) == 2


# ===========================================================================
# User stats
# ===========================================================================

class TestUserStats:
    def test_initial_stats_are_zero(self, db, sample_user):
        stats = db.get_user_stats(sample_user["user_id"])
        assert stats["goals_created"] == 0
        assert stats["goals_completed"] == 0

    def test_increment_goals_created(self, db, sample_user):
        db.update_user_stats(sample_user["user_id"], "goals_created")
        stats = db.get_user_stats(sample_user["user_id"])
        assert stats["goals_created"] == 1

    def test_increment_by_custom_amount(self, db, sample_user):
        db.update_user_stats(sample_user["user_id"], "goals_created", increment=3)
        stats = db.get_user_stats(sample_user["user_id"])
        assert stats["goals_created"] == 3

    def test_increment_goals_completed_affects_reputation(self, db, sample_user):
        before_raw = db._read_json(db.users_file)[sample_user["user_id"]]["reputation"]
        db.update_user_stats(sample_user["user_id"], "goals_completed", 1)
        after_raw = db._read_json(db.users_file)[sample_user["user_id"]]["reputation"]
        assert after_raw > before_raw

    def test_update_stats_for_nonexistent_user_is_noop(self, db):
        """Must not raise; just silently skip."""
        db.update_user_stats("bad-id", "goals_created")  # should not raise

    def test_get_stats_unknown_user_returns_empty(self, db):
        assert db.get_user_stats("bad-id") == {}


# ===========================================================================
# System stats
# ===========================================================================

class TestSystemStats:
    def test_user_counts(self, db):
        db.create_user("Alice", "a@test.com", "pass")
        u2 = db.create_user("Bob", "b@test.com", "pass")
        db.deactivate_user(u2["user_id"])
        stats = db.get_system_stats()
        assert stats["users"]["total"] == 2
        assert stats["users"]["active"] == 1
        assert stats["users"]["inactive"] == 1

    def test_goal_counts(self, db, sample_user):
        db.save_goal(_make_goal(sample_user["user_id"], "g1"))
        db.save_goal(_make_goal(sample_user["user_id"], "g2"))
        db.mark_goal_complete(sample_user["user_id"], "g1")
        stats = db.get_system_stats()
        assert stats["goals"]["total"] == 2
        assert stats["goals"]["completed"] == 1

    def test_content_counts(self, db):
        db.save_youtube_videos_for_goal("g1", [{"title": "v1"}, {"title": "v2"}])
        db.save_articles_for_goal("g1", [{"title": "a1"}])
        stats = db.get_system_stats()
        assert stats["content"]["videos"] == 2
        assert stats["content"]["articles"] == 1

    def test_empty_db_returns_zeros(self, db):
        stats = db.get_system_stats()
        assert stats["users"]["total"] == 0
        assert stats["goals"]["total"] == 0


# ===========================================================================
# Audit log
# ===========================================================================

class TestAuditLog:
    def test_get_audit_log_returns_list(self, db):
        assert isinstance(db.get_audit_log(), list)

    def test_limit_parameter_respected(self, db, sample_user):
        # Create 5 log entries (user_created + login × 4)
        for i in range(4):
            try:
                db.authenticate_user("alice@test.com", "wrong")
            except Exception:
                pass
        log = db.get_audit_log(limit=2)
        assert len(log) <= 2

    def test_audit_log_has_required_fields(self, db):
        db.create_user("Alice", "alice@test.com", "pass")
        entry = db.get_audit_log()[0]
        assert "timestamp" in entry
        assert "user_id" in entry
        assert "action" in entry
        assert "details" in entry

    def test_log_capped_at_1000_entries(self, db, tmp_path):
        """Write 1100 entries manually; only 1000 should be kept."""
        db2 = DatabaseManager(data_dir=str(tmp_path / "cap"))
        log = [{"timestamp": "t", "user_id": "u", "action": "x", "details": {}}
               for _ in range(1100)]
        db2._write_json(db2.audit_log_file, log)
        db2._log_action("u", "trigger", {})
        stored = db2._read_json(db2.audit_log_file)
        assert len(stored) <= 1000


# ===========================================================================
# Preferences
# ===========================================================================

class TestPreferences:
    def test_update_email_notifications(self, db, sample_user):
        updated = db.update_user_preferences(
            sample_user["user_id"], {"email_notifications": False}
        )
        raw = db._read_json(db.users_file)[sample_user["user_id"]]
        assert raw["email_notifications"] is False

    def test_update_multiple_prefs(self, db, sample_user):
        db.update_user_preferences(
            sample_user["user_id"],
            {"weekly_summary": True, "content_updates": False}
        )
        raw = db._read_json(db.users_file)[sample_user["user_id"]]
        assert raw["weekly_summary"] is True
        assert raw["content_updates"] is False

    def test_update_prefs_unknown_user_raises(self, db):
        with pytest.raises(ValueError, match="not found"):
            db.update_user_preferences("bad-id", {"email_notifications": True})

    def test_pref_update_returns_sanitized_user(self, db, sample_user):
        result = db.update_user_preferences(
            sample_user["user_id"], {"email_notifications": True}
        )
        assert "password_hash" not in result
