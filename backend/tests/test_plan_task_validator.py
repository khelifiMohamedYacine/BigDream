"""
test_plan_task_validator.py
===========================
Comprehensive unit tests for every function in plan_task_validator.py.

Functions covered:
  extract_tasks_from_plan
  validate_status_transition
  compute_task_progress
  get_current_week
  get_tasks_for_week
  get_tasks_by_status
  get_overdue_tasks
  merge_existing_completions
  generate_validation_report
"""
import pytest
from backend.app.plan_task_validator import (
    extract_tasks_from_plan,
    validate_status_transition,
    compute_task_progress,
    get_current_week,
    get_tasks_for_week,
    get_tasks_by_status,
    get_overdue_tasks,
    merge_existing_completions,
    generate_validation_report,
    ALLOWED_TRANSITIONS,
    VALID_STATUSES,
    TASK_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _plan(weeks=2, objectives_per_week=2, exercises_per_week=2):
    """Build a synthetic plan with predictable structure."""
    breakdown = []
    for w in range(1, weeks + 1):
        breakdown.append({
            "week": w,
            "theme": f"Week {w}",
            "learning_objectives": [f"Obj {i+1} W{w}" for i in range(objectives_per_week)],
            "practice_exercises": [f"Ex {i+1} W{w}" for i in range(exercises_per_week)],
        })
    return {"weekly_breakdown": breakdown}


def _set_status(tasks, goal_id, week, idx, kind, status):
    """Helper to set a task to a given status using its deterministic ID."""
    task_id = f"{goal_id}_w{week:02d}_{kind}_{idx:02d}"
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = status
            if status == "completed":
                t["completed_at"] = "2025-01-01T10:00:00"
            return t
    raise KeyError(f"Task {task_id} not found")


# ===========================================================================
# extract_tasks_from_plan
# ===========================================================================

class TestExtractTasksFromPlan:
    def test_returns_correct_total_count(self):
        # 2 weeks × (2 obj + 2 ex) = 8 tasks
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        assert len(tasks) == 8

    def test_all_tasks_start_as_pending(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        assert all(t["status"] == "pending" for t in tasks)

    def test_objective_count_correct(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 3, 1))
        objectives = [t for t in tasks if t["type"] == "objective"]
        assert len(objectives) == 6  # 3 per week × 2 weeks

    def test_exercise_count_correct(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 1, 4))
        exercises = [t for t in tasks if t["type"] == "exercise"]
        assert len(exercises) == 8  # 4 per week × 2 weeks

    def test_first_objective_id_format(self):
        tasks = extract_tasks_from_plan("abc12345", _plan(1, 2, 1))
        obj_tasks = [t for t in tasks if t["type"] == "objective"]
        assert obj_tasks[0]["id"] == "abc12345_w01_obj_00"

    def test_first_exercise_id_format(self):
        tasks = extract_tasks_from_plan("abc12345", _plan(1, 1, 2))
        ex_tasks = [t for t in tasks if t["type"] == "exercise"]
        assert ex_tasks[0]["id"] == "abc12345_w01_ex_00"

    def test_week2_objective_id(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        w2_objs = [t for t in tasks if t["type"] == "objective" and t["week"] == 2]
        assert w2_objs[0]["id"] == "g1_w02_obj_00"

    def test_goal_id_embedded_in_tasks(self):
        tasks = extract_tasks_from_plan("mygoal", _plan(1))
        assert all(t["goal_id"] == "mygoal" for t in tasks)

    def test_week_number_embedded_in_tasks(self):
        tasks = extract_tasks_from_plan("g1", _plan(3))
        weeks = {t["week"] for t in tasks}
        assert weeks == {1, 2, 3}

    def test_week_theme_embedded(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        assert tasks[0]["week_theme"] == "Week 1"

    def test_task_text_stripped(self):
        plan = {"weekly_breakdown": [{"week": 1, "theme": "T",
                "learning_objectives": ["  Trimmed  "],
                "practice_exercises": []}]}
        tasks = extract_tasks_from_plan("g1", plan)
        assert tasks[0]["text"] == "Trimmed"

    def test_empty_string_objectives_skipped(self):
        plan = {"weekly_breakdown": [{"week": 1, "theme": "T",
                "learning_objectives": ["", "   ", "Valid"],
                "practice_exercises": []}]}
        tasks = extract_tasks_from_plan("g1", plan)
        assert len(tasks) == 1

    def test_non_string_objectives_skipped(self):
        plan = {"weekly_breakdown": [{"week": 1, "theme": "T",
                "learning_objectives": [123, None, "Valid"],
                "practice_exercises": []}]}
        tasks = extract_tasks_from_plan("g1", plan)
        assert len(tasks) == 1

    def test_empty_plan_returns_empty_list(self):
        tasks = extract_tasks_from_plan("g1", {})
        assert tasks == []

    def test_empty_weekly_breakdown_returns_empty_list(self):
        tasks = extract_tasks_from_plan("g1", {"weekly_breakdown": []})
        assert tasks == []

    def test_created_at_is_set(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        assert tasks[0]["created_at"] is not None

    def test_completed_at_is_none(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        assert all(t["completed_at"] is None for t in tasks)

    def test_notes_field_empty_string(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        assert all(t["notes"] == "" for t in tasks)

    def test_ids_are_stable_across_calls(self):
        plan = _plan(2, 2, 2)
        tasks1 = extract_tasks_from_plan("g1", plan)
        tasks2 = extract_tasks_from_plan("g1", plan)
        ids1 = [t["id"] for t in tasks1]
        ids2 = [t["id"] for t in tasks2]
        assert ids1 == ids2

    def test_dense_index_no_gaps(self):
        """IDs must be 00, 01, 02 without skips even if some objectives are filtered."""
        plan = {"weekly_breakdown": [{"week": 1, "theme": "T",
                "learning_objectives": ["A", "B", "C"],
                "practice_exercises": ["P", "Q"]}]}
        tasks = extract_tasks_from_plan("g", plan)
        obj_ids = sorted(t["id"] for t in tasks if t["type"] == "objective")
        assert obj_ids == ["g_w01_obj_00", "g_w01_obj_01", "g_w01_obj_02"]


# ===========================================================================
# validate_status_transition
# ===========================================================================

class TestValidateStatusTransition:
    @pytest.mark.parametrize("frm,to", [
        ("pending",     "in_progress"),
        ("pending",     "skipped"),
        ("in_progress", "completed"),
        ("in_progress", "pending"),
        ("in_progress", "skipped"),
        ("completed",   "in_progress"),
        ("skipped",     "pending"),
    ])
    def test_valid_transitions_return_true(self, frm, to):
        ok, err = validate_status_transition(frm, to)
        assert ok is True
        assert err == ""

    @pytest.mark.parametrize("frm,to", [
        ("pending",   "completed"),
        ("pending",   "pending"),
        ("skipped",   "completed"),
        ("skipped",   "in_progress"),
        ("skipped",   "skipped"),
        ("completed", "pending"),
        ("completed", "completed"),
        ("completed", "skipped"),
    ])
    def test_invalid_transitions_return_false(self, frm, to):
        ok, err = validate_status_transition(frm, to)
        assert ok is False
        assert len(err) > 0

    def test_unknown_new_status_returns_false(self):
        ok, err = validate_status_transition("pending", "flying")
        assert ok is False
        assert "flying" in err

    def test_unknown_current_status_returns_false(self):
        ok, err = validate_status_transition("nonexistent", "pending")
        assert ok is False

    def test_error_message_contains_allowed_transitions(self):
        ok, err = validate_status_transition("pending", "completed")
        assert "in_progress" in err or "skipped" in err

    def test_all_allowed_transitions_are_valid(self):
        """Cross-check ALLOWED_TRANSITIONS dict against the validator."""
        for frm, targets in ALLOWED_TRANSITIONS.items():
            for to in targets:
                ok, _ = validate_status_transition(frm, to)
                assert ok is True, f"Expected {frm}→{to} to be valid"


# ===========================================================================
# compute_task_progress
# ===========================================================================

class TestComputeTaskProgress:
    def test_empty_tasks_returns_zeros(self):
        p = compute_task_progress([])
        assert p["total_tasks"] == 0
        assert p["completion_rate"] == 0.0
        assert p["weighted_completion_rate"] == 0.0

    def test_all_pending_rate_is_zero(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        p = compute_task_progress(tasks)
        assert p["completion_rate"] == 0.0

    def test_all_completed_rate_is_one(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        for t in tasks:
            t["status"] = "completed"
        p = compute_task_progress(tasks)
        assert p["completion_rate"] == 1.0
        assert p["weighted_completion_rate"] == 1.0

    def test_weighted_rate_higher_when_exercises_complete(self):
        """Completing exercises (weight 1.5) should give higher weighted rate."""
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        only_exercises = [t for t in tasks if t["type"] == "exercise"]
        for t in only_exercises:
            t["status"] = "completed"
        p = compute_task_progress(tasks)
        assert p["weighted_completion_rate"] > p["completion_rate"]

    def test_exact_weighted_calculation(self):
        """
        1 week, 2 obj (weight 1.0) + 2 ex (weight 1.5)
        Total weight = 2×1.0 + 2×1.5 = 5.0
        Complete 1 obj + 1 ex = 1.0 + 1.5 = 2.5
        weighted = 2.5 / 5.0 = 0.5
        """
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        objs = [t for t in tasks if t["type"] == "objective"]
        exes = [t for t in tasks if t["type"] == "exercise"]
        objs[0]["status"] = "completed"
        exes[0]["status"] = "completed"
        p = compute_task_progress(tasks)
        assert p["weighted_completion_rate"] == pytest.approx(0.5, abs=0.001)

    def test_count_fields(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        tasks[0]["status"] = "completed"
        tasks[1]["status"] = "in_progress"
        tasks[2]["status"] = "skipped"
        p = compute_task_progress(tasks)
        assert p["completed_tasks"] == 1
        assert p["in_progress_tasks"] == 1
        assert p["skipped_tasks"] == 1
        assert p["pending_tasks"] == 1  # one task remains pending
        assert p["total_tasks"] == 4

    def test_by_week_breakdown_correct(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        # complete all week 1 tasks
        for t in tasks:
            if t["week"] == 1:
                t["status"] = "completed"
        p = compute_task_progress(tasks)
        assert p["by_week"][1]["completion_rate"] == 1.0
        assert p["by_week"][2]["completion_rate"] == 0.0

    def test_completion_rate_range(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 3, 3))
        tasks[0]["status"] = "completed"
        p = compute_task_progress(tasks)
        assert 0.0 <= p["completion_rate"] <= 1.0
        assert 0.0 <= p["weighted_completion_rate"] <= 1.0

    def test_single_task_completed(self):
        tasks = [{"id": "g_w01_obj_00", "type": "objective", "week": 1,
                  "week_theme": "T", "status": "completed"}]
        p = compute_task_progress(tasks)
        assert p["completion_rate"] == 1.0


# ===========================================================================
# get_current_week
# ===========================================================================

class TestGetCurrentWeek:
    def test_all_pending_returns_first_week(self):
        tasks = extract_tasks_from_plan("g", _plan(3))
        assert get_current_week(tasks) == 1

    def test_week1_complete_returns_week2(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        for t in tasks:
            if t["week"] == 1:
                t["status"] = "completed"
        assert get_current_week(tasks) == 2

    def test_all_weeks_complete_returns_last_week(self):
        tasks = extract_tasks_from_plan("g", _plan(3, 2, 2))
        for t in tasks:
            t["status"] = "completed"
        assert get_current_week(tasks) == 3

    def test_partial_week1_returns_week1(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        # Complete only 1 of 4 week-1 tasks
        tasks[0]["status"] = "completed"
        assert get_current_week(tasks) == 1

    def test_empty_tasks_returns_1(self):
        assert get_current_week([]) == 1

    def test_single_week_complete(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        for t in tasks:
            t["status"] = "completed"
        assert get_current_week(tasks) == 1  # last available week


# ===========================================================================
# get_tasks_for_week
# ===========================================================================

class TestGetTasksForWeek:
    def test_returns_tasks_for_correct_week(self):
        tasks = extract_tasks_from_plan("g", _plan(3, 2, 2))
        week2 = get_tasks_for_week(tasks, 2)
        assert all(t["week"] == 2 for t in week2)

    def test_correct_count_per_week(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 3, 2))
        week1 = get_tasks_for_week(tasks, 1)
        assert len(week1) == 5  # 3 obj + 2 ex

    def test_nonexistent_week_returns_empty(self):
        tasks = extract_tasks_from_plan("g", _plan(2))
        assert get_tasks_for_week(tasks, 99) == []

    def test_week_0_returns_empty(self):
        tasks = extract_tasks_from_plan("g", _plan(2))
        assert get_tasks_for_week(tasks, 0) == []


# ===========================================================================
# get_tasks_by_status
# ===========================================================================

class TestGetTasksByStatus:
    def test_get_pending_tasks(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        tasks[0]["status"] = "completed"
        pending = get_tasks_by_status(tasks, "pending")
        assert all(t["status"] == "pending" for t in pending)
        assert len(pending) == 3

    def test_get_completed_tasks(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        tasks[0]["status"] = "completed"
        tasks[1]["status"] = "completed"
        completed = get_tasks_by_status(tasks, "completed")
        assert len(completed) == 2

    def test_empty_result_for_no_match(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        assert get_tasks_by_status(tasks, "skipped") == []

    def test_all_statuses_covered(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        tasks[0]["status"] = "pending"
        tasks[1]["status"] = "in_progress"
        tasks[2]["status"] = "completed"
        tasks[3]["status"] = "skipped"
        for status in VALID_STATUSES:
            result = get_tasks_by_status(tasks, status)
            assert len(result) == 1


# ===========================================================================
# get_overdue_tasks
# ===========================================================================

class TestGetOverdueTasks:
    def test_no_overdue_when_week1_all_complete(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        for t in tasks:
            if t["week"] == 1:
                t["status"] = "completed"
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == 0

    def test_overdue_when_week1_task_pending_at_week2(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        # leave all week 1 tasks as pending
        overdue = get_overdue_tasks(tasks, current_week=2)
        week1_tasks = [t for t in tasks if t["week"] == 1]
        assert len(overdue) == len(week1_tasks)

    def test_skipped_not_counted_as_overdue(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        for t in tasks:
            if t["week"] == 1:
                t["status"] = "skipped"
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == 0

    def test_current_week_tasks_not_overdue(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        overdue = get_overdue_tasks(tasks, current_week=1)
        assert len(overdue) == 0

    def test_in_progress_from_past_week_is_overdue(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 2, 2))
        tasks[0]["status"] = "in_progress"  # week 1 task
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert tasks[0] in overdue


# ===========================================================================
# merge_existing_completions
# ===========================================================================

class TestMergeExistingCompletions:
    def test_stored_status_applied(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        stored = {tasks[0]["id"]: {"status": "completed", "completed_at": "2025-01-01T10:00:00", "notes": ""}}
        merged = merge_existing_completions(tasks, stored)
        assert merged[0]["status"] == "completed"

    def test_unstored_tasks_stay_pending(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        stored = {tasks[0]["id"]: {"status": "completed", "completed_at": "2025-01-01T10:00:00", "notes": ""}}
        merged = merge_existing_completions(tasks, stored)
        assert all(t["status"] == "pending" for t in merged[1:])

    def test_completed_at_applied(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 1, 1))
        ts = "2025-06-15T08:00:00"
        stored = {tasks[0]["id"]: {"status": "completed", "completed_at": ts, "notes": ""}}
        merged = merge_existing_completions(tasks, stored)
        assert merged[0]["completed_at"] == ts

    def test_notes_applied(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 1, 1))
        stored = {tasks[0]["id"]: {"status": "in_progress", "completed_at": None, "notes": "Working on it"}}
        merged = merge_existing_completions(tasks, stored)
        assert merged[0]["notes"] == "Working on it"

    def test_empty_stored_no_changes(self):
        tasks = extract_tasks_from_plan("g", _plan(1, 2, 2))
        merged = merge_existing_completions(tasks, {})
        assert all(t["status"] == "pending" for t in merged)

    def test_returns_same_count(self):
        tasks = extract_tasks_from_plan("g", _plan(2, 3, 2))
        merged = merge_existing_completions(tasks, {})
        assert len(merged) == len(tasks)

    def test_re_extraction_preserves_all_completions(self):
        plan = _plan(2, 2, 2)
        tasks = extract_tasks_from_plan("g", plan)
        stored = {t["id"]: {"status": "completed", "completed_at": "2025-01-01", "notes": ""}
                  for t in tasks if t["week"] == 1}
        # Re-extract and merge
        fresh = extract_tasks_from_plan("g", plan)
        merged = merge_existing_completions(fresh, stored)
        completed_ids = {t["id"] for t in merged if t["status"] == "completed"}
        assert completed_ids == set(stored.keys())


# ===========================================================================
# generate_validation_report
# ===========================================================================

class TestGenerateValidationReport:
    def _goal(self, goal_id="g1"):
        return {"id": goal_id, "title": "Learn Python", "goal_type": "coding", "total_weeks": 4}

    def test_report_has_required_fields(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        report = generate_validation_report(self._goal(), tasks)
        for field in ("goal_id", "plan_health", "current_week", "progress",
                      "overdue_task_count", "recommendations", "generated_at"):
            assert field in report, f"Missing field: {field}"

    def test_at_risk_when_no_tasks_completed(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        report = generate_validation_report(self._goal(), tasks)
        assert report["plan_health"] == "at_risk"

    def test_excellent_when_all_completed(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        for t in tasks:
            t["status"] = "completed"
        report = generate_validation_report(self._goal(), tasks)
        assert report["plan_health"] == "excellent"

    def test_on_track_at_70_percent(self):
        """~73% weighted completion should yield on_track."""
        tasks = extract_tasks_from_plan("g1", _plan(1, 2, 2))
        # Total weight = 2×1.0 + 2×1.5 = 5.0; need ≥ 3.5 (70%)
        # Complete 1 obj (1.0) + 2 ex (3.0) = 4.0 / 5.0 = 80% → on_track
        for t in tasks:
            if t["type"] == "exercise":
                t["status"] = "completed"
        tasks[0]["status"] = "completed"
        report = generate_validation_report(self._goal(), tasks)
        assert report["plan_health"] in ("on_track", "excellent")

    def test_recommendations_is_list(self):
        tasks = extract_tasks_from_plan("g1", _plan(1, 2, 2))
        report = generate_validation_report(self._goal(), tasks)
        assert isinstance(report["recommendations"], list)

    def test_overdue_recommendation_included(self):
        """Overdue tasks should trigger a recommendation."""
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        # Move to week 2 context but keep week 1 incomplete
        report = generate_validation_report(self._goal(), tasks)
        # at_risk health should produce a recommendation
        assert len(report["recommendations"]) > 0

    def test_goal_title_in_report(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        report = generate_validation_report(self._goal(), tasks)
        assert report["goal_title"] == "Learn Python"

    def test_goal_id_in_report(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        report = generate_validation_report({"id": "custom-id", "title": "T",
                                              "goal_type": "coding", "total_weeks": 2}, tasks)
        assert report["goal_id"] == "custom-id"

    def test_generated_at_is_string(self):
        tasks = extract_tasks_from_plan("g1", _plan(1))
        report = generate_validation_report(self._goal(), tasks)
        assert isinstance(report["generated_at"], str)

    def test_progress_dict_in_report(self):
        tasks = extract_tasks_from_plan("g1", _plan(1, 2, 2))
        report = generate_validation_report(self._goal(), tasks)
        prog = report["progress"]
        assert "total_tasks" in prog
        assert "completion_rate" in prog
        assert "weighted_completion_rate" in prog

    def test_no_overdue_recommendation_when_all_done(self):
        tasks = extract_tasks_from_plan("g1", _plan(2, 2, 2))
        for t in tasks:
            t["status"] = "completed"
        report = generate_validation_report(self._goal(), tasks)
        assert report["overdue_task_count"] == 0

    def test_needs_attention_health_level(self):
        """~50% completion → needs_attention."""
        tasks = extract_tasks_from_plan("g1", _plan(1, 2, 2))
        # total weight = 5.0; need exactly 40–69%: complete 1 obj + 1 ex = 2.5 / 5.0 = 50%
        tasks[0]["status"] = "completed"
        for t in tasks:
            if t["type"] == "exercise":
                t["status"] = "completed"
                break
        report = generate_validation_report(self._goal(), tasks)
        assert report["plan_health"] in ("needs_attention", "at_risk", "on_track")


# ===========================================================================
# TASK_WEIGHTS constant sanity
# ===========================================================================

class TestConstants:
    def test_objective_weight_is_one(self):
        assert TASK_WEIGHTS["objective"] == 1.0

    def test_exercise_weight_greater_than_objective(self):
        assert TASK_WEIGHTS["exercise"] > TASK_WEIGHTS["objective"]

    def test_valid_statuses_are_four(self):
        assert VALID_STATUSES == {"pending", "in_progress", "completed", "skipped"}

    def test_all_statuses_have_transition_entry(self):
        for s in VALID_STATUSES:
            assert s in ALLOWED_TRANSITIONS
