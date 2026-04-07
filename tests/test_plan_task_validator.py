"""
Tests for plan_task_validator — pure Python, no mocking required.
Covers: extract_tasks_from_plan, validate_status_transition,
compute_task_progress, get_current_week, get_tasks_for_week,
get_tasks_by_status, get_overdue_tasks, merge_existing_completions,
generate_validation_report.
"""
import pytest
from datetime import datetime

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
    VALID_STATUSES,
    ALLOWED_TRANSITIONS,
    TASK_WEIGHTS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_plan(weeks=2):
    breakdown = []
    for w in range(1, weeks + 1):
        breakdown.append({
            "week": w,
            "theme": f"Week {w} Theme",
            "learning_objectives": [f"Objective W{w}-1", f"Objective W{w}-2"],
            "practice_exercises": [f"Exercise W{w}-1", f"Exercise W{w}-2"],
        })
    return {"weekly_breakdown": breakdown, "total_weeks": weeks}


def make_tasks(week=1, obj_count=2, ex_count=2, status="pending"):
    tasks = []
    for i in range(obj_count):
        tasks.append({
            "id": f"g1_w{week:02d}_obj_{i:02d}",
            "goal_id": "g1",
            "week": week,
            "week_theme": f"Week {week}",
            "type": "objective",
            "text": f"Obj {i}",
            "status": status,
            "completed_at": None,
            "notes": "",
        })
    for i in range(ex_count):
        tasks.append({
            "id": f"g1_w{week:02d}_ex_{i:02d}",
            "goal_id": "g1",
            "week": week,
            "week_theme": f"Week {week}",
            "type": "exercise",
            "text": f"Ex {i}",
            "status": status,
            "completed_at": None,
            "notes": "",
        })
    return tasks


# ===========================================================================
# extract_tasks_from_plan
# ===========================================================================

class TestExtractTasks:
    def test_returns_list(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        assert isinstance(tasks, list)

    def test_correct_number_of_tasks(self):
        plan = make_plan(1)  # 2 objectives + 2 exercises = 4 tasks
        tasks = extract_tasks_from_plan("g1", plan)
        assert len(tasks) == 4

    def test_two_weeks_doubles_task_count(self):
        plan = make_plan(2)
        tasks = extract_tasks_from_plan("g1", plan)
        assert len(tasks) == 8

    def test_task_ids_are_unique(self):
        plan = make_plan(2)
        tasks = extract_tasks_from_plan("g1", plan)
        ids = [t["id"] for t in tasks]
        assert len(ids) == len(set(ids))

    def test_task_id_format_objective(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        obj_tasks = [t for t in tasks if t["type"] == "objective"]
        assert obj_tasks[0]["id"] == "g1_w01_obj_00"

    def test_task_id_format_exercise(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        ex_tasks = [t for t in tasks if t["type"] == "exercise"]
        assert ex_tasks[0]["id"] == "g1_w01_ex_00"

    def test_all_tasks_default_status_is_pending(self):
        plan = make_plan(2)
        tasks = extract_tasks_from_plan("g1", plan)
        assert all(t["status"] == "pending" for t in tasks)

    def test_tasks_have_correct_week_number(self):
        plan = make_plan(2)
        tasks = extract_tasks_from_plan("g1", plan)
        week1 = [t for t in tasks if t["week"] == 1]
        week2 = [t for t in tasks if t["week"] == 2]
        assert len(week1) == 4
        assert len(week2) == 4

    def test_empty_objectives_skipped(self):
        plan = {"weekly_breakdown": [{"week": 1, "theme": "T",
                                       "learning_objectives": ["", "  ", "Valid obj"],
                                       "practice_exercises": []}]}
        tasks = extract_tasks_from_plan("g1", plan)
        obj_tasks = [t for t in tasks if t["type"] == "objective"]
        assert len(obj_tasks) == 1  # only "Valid obj" kept

    def test_empty_plan_returns_empty_list(self):
        tasks = extract_tasks_from_plan("g1", {"weekly_breakdown": []})
        assert tasks == []

    def test_task_has_goal_id(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("goal99", plan)
        assert all(t["goal_id"] == "goal99" for t in tasks)

    def test_task_has_week_theme(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        assert all("week_theme" in t for t in tasks)


# ===========================================================================
# validate_status_transition
# ===========================================================================

class TestValidateStatusTransition:
    @pytest.mark.parametrize("current,new", [
        ("pending", "in_progress"),
        ("pending", "skipped"),
        ("in_progress", "completed"),
        ("in_progress", "pending"),
        ("in_progress", "skipped"),
        ("completed", "in_progress"),
        ("skipped", "pending"),
    ])
    def test_allowed_transitions(self, current, new):
        valid, msg = validate_status_transition(current, new)
        assert valid is True
        assert msg == ""

    @pytest.mark.parametrize("current,new", [
        ("pending", "completed"),     # must go through in_progress
        ("pending", "pending"),       # no self-transition
        ("completed", "pending"),     # cannot go back to pending directly
        ("completed", "skipped"),
        ("skipped", "in_progress"),
        ("skipped", "completed"),
    ])
    def test_forbidden_transitions(self, current, new):
        valid, msg = validate_status_transition(current, new)
        assert valid is False
        assert msg != ""

    def test_invalid_new_status_returns_false(self):
        valid, msg = validate_status_transition("pending", "flying")
        assert valid is False
        assert "flying" in msg

    def test_unknown_current_status_returns_false(self):
        valid, msg = validate_status_transition("unknown_state", "pending")
        assert valid is False

    def test_all_valid_statuses_covered(self):
        assert VALID_STATUSES == {"pending", "in_progress", "completed", "skipped"}


# ===========================================================================
# compute_task_progress
# ===========================================================================

class TestComputeTaskProgress:
    def test_empty_tasks_returns_zeros(self):
        result = compute_task_progress([])
        assert result["total_tasks"] == 0
        assert result["completion_rate"] == 0.0
        assert result["weighted_completion_rate"] == 0.0

    def test_all_pending_zero_completion(self):
        tasks = make_tasks(status="pending")
        result = compute_task_progress(tasks)
        assert result["completion_rate"] == 0.0
        assert result["completed_tasks"] == 0

    def test_all_completed_full_rate(self):
        tasks = make_tasks(status="completed")
        result = compute_task_progress(tasks)
        assert result["completion_rate"] == 1.0
        assert result["weighted_completion_rate"] == 1.0

    def test_half_completed_half_rate(self):
        tasks_a = make_tasks(obj_count=2, ex_count=0, status="completed")
        tasks_b = make_tasks(obj_count=2, ex_count=0, status="pending")
        result = compute_task_progress(tasks_a + tasks_b)
        assert result["completion_rate"] == 0.5

    def test_exercises_have_higher_weight(self):
        # 1 completed exercise vs 1 completed objective — exercise weighs 1.5 vs 1.0
        ex_task = [{"id": "e1", "goal_id": "g1", "week": 1, "week_theme": "W1",
                    "type": "exercise", "text": "Ex", "status": "completed",
                    "completed_at": None, "notes": ""}]
        obj_task = [{"id": "o1", "goal_id": "g1", "week": 1, "week_theme": "W1",
                     "type": "objective", "text": "Ob", "status": "pending",
                     "completed_at": None, "notes": ""}]
        result = compute_task_progress(ex_task + obj_task)
        # Weighted: 1.5 / (1.5 + 1.0) = 0.6
        assert abs(result["weighted_completion_rate"] - 0.6) < 0.01

    def test_returns_by_week_breakdown(self):
        tasks = make_tasks(week=1, status="pending") + make_tasks(week=2, status="completed")
        result = compute_task_progress(tasks)
        assert 1 in result["by_week"]
        assert 2 in result["by_week"]

    def test_counts_in_progress_tasks(self):
        tasks = make_tasks(status="in_progress")
        result = compute_task_progress(tasks)
        assert result["in_progress_tasks"] == len(tasks)

    def test_counts_skipped_tasks(self):
        tasks = make_tasks(status="skipped")
        result = compute_task_progress(tasks)
        assert result["skipped_tasks"] == len(tasks)

    def test_total_tasks_count(self):
        tasks = make_tasks(obj_count=3, ex_count=2)
        result = compute_task_progress(tasks)
        assert result["total_tasks"] == 5

    def test_week_completion_rate_calculated(self):
        tasks = make_tasks(week=1, obj_count=2, ex_count=0, status="completed")
        result = compute_task_progress(tasks)
        assert result["by_week"][1]["completion_rate"] == 1.0


# ===========================================================================
# get_current_week
# ===========================================================================

class TestGetCurrentWeek:
    def test_returns_1_for_empty_tasks(self):
        assert get_current_week([]) == 1

    def test_returns_week_1_when_all_pending(self):
        tasks = make_tasks(week=1) + make_tasks(week=2)
        assert get_current_week(tasks) == 1

    def test_returns_week_2_when_week_1_complete(self):
        tasks = make_tasks(week=1, status="completed") + make_tasks(week=2, status="pending")
        assert get_current_week(tasks) == 2

    def test_returns_last_week_when_all_done(self):
        tasks = make_tasks(week=1, status="completed") + make_tasks(week=2, status="completed")
        assert get_current_week(tasks) == 2

    def test_partial_week_1_completion_stays_in_week_1(self):
        # Only some tasks in week 1 are complete
        tasks = [
            {"id": "t1", "week": 1, "status": "completed", "type": "objective",
             "week_theme": "W1", "text": "T1", "goal_id": "g1", "notes": "", "completed_at": None},
            {"id": "t2", "week": 1, "status": "pending", "type": "objective",
             "week_theme": "W1", "text": "T2", "goal_id": "g1", "notes": "", "completed_at": None},
        ]
        assert get_current_week(tasks) == 1


# ===========================================================================
# get_tasks_for_week
# ===========================================================================

class TestGetTasksForWeek:
    def test_filters_correctly(self):
        tasks = make_tasks(week=1) + make_tasks(week=2)
        week1 = get_tasks_for_week(tasks, 1)
        assert all(t["week"] == 1 for t in week1)
        assert len(week1) == 4

    def test_returns_empty_for_nonexistent_week(self):
        tasks = make_tasks(week=1)
        assert get_tasks_for_week(tasks, 99) == []

    def test_empty_input(self):
        assert get_tasks_for_week([], 1) == []


# ===========================================================================
# get_tasks_by_status
# ===========================================================================

class TestGetTasksByStatus:
    def test_filters_pending(self):
        tasks = make_tasks(status="pending") + make_tasks(status="completed")
        pending = get_tasks_by_status(tasks, "pending")
        assert all(t["status"] == "pending" for t in pending)

    def test_filters_completed(self):
        tasks = make_tasks(status="completed")
        result = get_tasks_by_status(tasks, "completed")
        assert len(result) == len(tasks)

    def test_empty_list(self):
        assert get_tasks_by_status([], "pending") == []


# ===========================================================================
# get_overdue_tasks
# ===========================================================================

class TestGetOverdueTasks:
    def test_past_week_pending_tasks_are_overdue(self):
        tasks = make_tasks(week=1, status="pending")
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == len(tasks)

    def test_completed_past_tasks_not_overdue(self):
        tasks = make_tasks(week=1, status="completed")
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == 0

    def test_skipped_past_tasks_not_overdue(self):
        tasks = make_tasks(week=1, status="skipped")
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == 0

    def test_current_week_tasks_not_overdue(self):
        tasks = make_tasks(week=2, status="pending")
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == 0

    def test_future_week_tasks_not_overdue(self):
        tasks = make_tasks(week=3, status="pending")
        overdue = get_overdue_tasks(tasks, current_week=2)
        assert len(overdue) == 0


# ===========================================================================
# merge_existing_completions
# ===========================================================================

class TestMergeExistingCompletions:
    def test_no_stored_completions_returns_original(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        merged = merge_existing_completions(tasks, {})
        assert all(t["status"] == "pending" for t in merged)

    def test_stored_status_overrides_extracted(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        task_id = tasks[0]["id"]
        stored = {task_id: {"status": "completed", "completed_at": "2026-01-01", "notes": ""}}
        merged = merge_existing_completions(tasks, stored)
        found = next(t for t in merged if t["id"] == task_id)
        assert found["status"] == "completed"

    def test_notes_are_merged(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        task_id = tasks[0]["id"]
        stored = {task_id: {"status": "in_progress", "completed_at": None, "notes": "Good progress"}}
        merged = merge_existing_completions(tasks, stored)
        found = next(t for t in merged if t["id"] == task_id)
        assert found["notes"] == "Good progress"

    def test_unknown_stored_ids_do_not_break(self):
        plan = make_plan(1)
        tasks = extract_tasks_from_plan("g1", plan)
        stored = {"nonexistent-id": {"status": "completed", "completed_at": None, "notes": ""}}
        merged = merge_existing_completions(tasks, stored)
        assert len(merged) == len(tasks)

    def test_returns_all_extracted_tasks(self):
        plan = make_plan(2)
        tasks = extract_tasks_from_plan("g1", plan)
        merged = merge_existing_completions(tasks, {})
        assert len(merged) == len(tasks)


# ===========================================================================
# generate_validation_report
# ===========================================================================

class TestGenerateValidationReport:
    def _make_goal(self):
        return {"id": "g1", "title": "Learn Python", "total_weeks": 2, "goal_type": "coding"}

    def test_returns_dict(self):
        tasks = make_tasks(week=1)
        report = generate_validation_report(self._make_goal(), tasks)
        assert isinstance(report, dict)

    def test_has_required_keys(self):
        tasks = make_tasks(week=1)
        report = generate_validation_report(self._make_goal(), tasks)
        assert "goal_id" in report
        assert "plan_health" in report
        assert "progress" in report
        assert "current_week" in report
        assert "overdue_task_count" in report
        assert "recommendations" in report

    def test_health_excellent_when_all_complete(self):
        tasks = make_tasks(week=1, status="completed") + make_tasks(week=2, status="completed")
        report = generate_validation_report(self._make_goal(), tasks)
        assert report["plan_health"] == "excellent"

    def test_health_at_risk_when_all_pending(self):
        tasks = make_tasks(week=1, status="pending") + make_tasks(week=2, status="pending")
        report = generate_validation_report(self._make_goal(), tasks)
        assert report["plan_health"] == "at_risk"

    def test_overdue_count_zero_when_behind_on_first_week(self):
        # Week 1 pending + week 2 in_progress: current_week = 1 (first incomplete),
        # so no tasks have week < 1 → overdue count is 0.
        tasks = (make_tasks(week=1, status="pending") +
                 make_tasks(week=2, status="in_progress"))
        report = generate_validation_report(self._make_goal(), tasks)
        assert report["overdue_task_count"] == 0
        assert report["current_week"] == 1

    def test_recommendations_populated_when_overdue(self):
        tasks = (make_tasks(week=1, status="pending") +
                 make_tasks(week=2, status="in_progress"))
        report = generate_validation_report(self._make_goal(), tasks)
        assert len(report["recommendations"]) > 0

    def test_generated_at_is_iso_format(self):
        tasks = make_tasks(week=1)
        report = generate_validation_report(self._make_goal(), tasks)
        datetime.fromisoformat(report["generated_at"])  # raises if malformed

    def test_goal_id_matches(self):
        tasks = make_tasks(week=1)
        report = generate_validation_report(self._make_goal(), tasks)
        assert report["goal_id"] == "g1"
