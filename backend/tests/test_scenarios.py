"""
test_scenarios.py
=================
Scenario-based test suite for BigDream CS Learning Assistant.

Covers the four main system concerns:
  S1 — CS Domain Restriction (agent_rules enforcement)
  S2 — Goal Type Detection (CS sub-classification)
  S3 — Plan Task Validation (state machine + progress)
  S4 — Multi-Agent Pipeline (worker coordination logic)

Run with:  python -m pytest backend/tests/test_scenarios.py -v
Or:        python backend/tests/test_scenarios.py
"""

import sys
import os
import json
import asyncio
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
_results = []


def assert_eq(label, got, expected):
    ok = got == expected
    tag = PASS if ok else FAIL
    print(f"  [{tag}] {label}")
    if not ok:
        print(f"         expected: {expected!r}")
        print(f"         got:      {got!r}")
    _results.append((label, ok))
    return ok


def assert_true(label, condition):
    tag = PASS if condition else FAIL
    print(f"  [{tag}] {label}")
    _results.append((label, bool(condition)))
    return bool(condition)


def assert_false(label, condition):
    return assert_true(label, not condition)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 1 — CS Domain Restriction
# ─────────────────────────────────────────────────────────────────────────────

def test_s1_python_domain_restriction():
    """
    Verify that is_python_goal() correctly accepts Python goals and rejects
    non-Python goals, enforcing the agent_rules.json restrictions.
    """
    print("\nS1 — Python Domain Restriction")
    print("─" * 50)

    from backend.app.goal_chatbot import is_python_goal

    # Should ACCEPT (Python goals)
    python_goals = [
        ("learn python for data science", True),
        ("build a django web application", True),
        ("master machine learning with pytorch", True),
        ("understand algorithms and data structures in python", True),
        ("deploy a flask api", True),
        ("learn pandas and numpy for data analysis", True),
        ("build a python automation script", True),
        ("become a python developer in 6 months", True),
        ("write clean python code", True),
        ("learn asyncio and fastapi", True),
    ]

    # Should REJECT (non-Python goals)
    non_python_goals = [
        ("get six pack abs in 3 months", False),
        ("learn to speak french fluently", False),
        ("become a better guitarist", False),
        ("start a dropshipping business", False),
        ("lose 10kg in 8 weeks", False),
        ("improve my painting skills", False),
        ("read 52 books this year", False),
    ]

    print("  Python Goals (should be accepted):")
    for desc, expected in python_goals:
        assert_eq(f'  is_python_goal("{desc[:45]}")', is_python_goal(desc), expected)

    print("  Non-Python Goals (should be rejected):")
    for desc, expected in non_python_goals:
        assert_eq(f'  is_python_goal("{desc[:45]}")', is_python_goal(desc), expected)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 2 — Goal Type Classification
# ─────────────────────────────────────────────────────────────────────────────

def test_s2_goal_type_detection():
    """
    Verify that detect_goal_type() returns the correct CS sub-type
    for various programming goal descriptions.
    """
    print("\nS2 — CS Goal Sub-Type Classification")
    print("─" * 50)

    from backend.app.goal_chatbot import detect_goal_type

    # All expected types must now be CS-specific (not 'fitness', 'language', etc.)
    cases = [
        ("learn python web scraping",        "coding"),
        ("master pytorch deep learning",      "coding"),
        ("build a react dashboard",           "coding"),
        ("understand java spring framework",  "coding"),
        ("write sql queries for postgres",    "coding"),
        ("set up docker and kubernetes",      "coding"),
        ("study penetration testing",         "coding"),
        ("solve leetcode hard problems",      "coding"),
        ("learn c++ for competitive coding",  "coding"),
        ("build a flutter mobile app",        "coding"),
    ]

    non_cs_inputs = ["get fit", "learn spanish", "start a business"]

    print("  CS sub-type classification:")
    for desc, expected in cases:
        result = detect_goal_type(desc)
        assert_eq(f'  detect_goal_type("{desc[:40]}")', result, expected)

    print("  Non-CS inputs must not leak non-CS types:")
    forbidden = {"fitness", "language", "creative", "business", "general"}
    for desc in non_cs_inputs:
        result = detect_goal_type(desc)
        assert_true(
            f'  detect_goal_type("{desc}") not in forbidden types',
            result not in forbidden
        )


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 3 — Plan Task Validation State Machine
# ─────────────────────────────────────────────────────────────────────────────

def test_s3_task_state_machine():
    """
    Test the plan task validation state machine including:
      - Task extraction from a plan
      - Valid and invalid status transitions
      - Progress computation
      - Weighted progress (exercises > objectives)
      - Validation report generation
    """
    print("\nS3 — Plan Task Validation State Machine")
    print("─" * 50)

    from backend.app.plan_task_validator import (
        extract_tasks_from_plan,
        validate_status_transition,
        compute_task_progress,
        get_current_week,
        get_overdue_tasks,
        generate_validation_report,
        merge_existing_completions,
    )

    # ── 3a. Task extraction ──────────────────────────────────────────────────
    print("  3a. Task extraction:")
    plan = {
        "weekly_breakdown": [
            {
                "week": 1, "theme": "Python Basics",
                "learning_objectives": ["Understand variables", "Write functions", "Use lists"],
                "practice_exercises": ["Build a calculator", "Solve 5 challenges"]
            },
            {
                "week": 2, "theme": "OOP in Python",
                "learning_objectives": ["Define classes", "Use inheritance"],
                "practice_exercises": ["Build a bank account class", "Refactor project with OOP"]
            },
        ]
    }

    tasks = extract_tasks_from_plan("goal_abc", plan)
    assert_eq("  Total tasks extracted", len(tasks), 9)  # 3+2 obj + 2+2 ex = 9

    obj_tasks = [t for t in tasks if t["type"] == "objective"]
    ex_tasks  = [t for t in tasks if t["type"] == "exercise"]
    assert_eq("  Objective tasks", len(obj_tasks), 5)
    assert_eq("  Exercise tasks",  len(ex_tasks),  4)

    # Check stable IDs
    assert_eq("  First task ID", tasks[0]["id"], "goal_abc_w01_obj_00")
    assert_eq("  First exercise ID", ex_tasks[0]["id"], "goal_abc_w01_ex_00")
    assert_eq("  All tasks start pending",
              all(t["status"] == "pending" for t in tasks), True)

    # ── 3b. Valid transitions ────────────────────────────────────────────────
    print("  3b. Valid transitions:")
    valid_transitions = [
        ("pending",     "in_progress"),
        ("pending",     "skipped"),
        ("in_progress", "completed"),
        ("in_progress", "pending"),
        ("in_progress", "skipped"),
        ("completed",   "in_progress"),   # allow un-completing
        ("skipped",     "pending"),
    ]
    for frm, to in valid_transitions:
        ok, err = validate_status_transition(frm, to)
        assert_true(f'  {frm} → {to} is VALID', ok)

    # ── 3c. Invalid transitions ──────────────────────────────────────────────
    print("  3c. Invalid transitions (must be rejected):")
    invalid_transitions = [
        ("pending",   "completed"),   # must go through in_progress first
        ("skipped",   "completed"),
        ("completed", "pending"),
        ("completed", "skipped"),
        ("pending",   "nonexistent"),
    ]
    for frm, to in invalid_transitions:
        ok, err = validate_status_transition(frm, to)
        assert_false(f'  {frm} → {to} is INVALID', ok)
        assert_true(f'  Error message present', len(err) > 0)

    # ── 3d. Progress computation ─────────────────────────────────────────────
    print("  3d. Progress computation:")
    test_tasks = extract_tasks_from_plan("goal_test", plan)

    # Mark 2 objectives as complete, 1 exercise as complete
    test_tasks[0]["status"] = "completed"   # obj (weight 1.0)
    test_tasks[1]["status"] = "completed"   # obj (weight 1.0)
    test_tasks[3]["status"] = "completed"   # ex  (weight 1.5)

    progress = compute_task_progress(test_tasks)
    assert_eq("  Total tasks",     progress["total_tasks"],     9)
    assert_eq("  Completed tasks", progress["completed_tasks"], 3)

    # Weighted: 1.0+1.0+1.5 / (5×1.0 + 4×1.5) = 3.5 / 11.0 = 0.3182
    expected_weighted = round(3.5 / 11.0, 4)
    assert_eq("  Weighted completion rate",
              progress["weighted_completion_rate"], expected_weighted)

    assert_true("  Weighted > simple completion rate",
                progress["weighted_completion_rate"] > 0)

    # ── 3e. Current week detection ───────────────────────────────────────────
    print("  3e. Current week detection:")
    current = get_current_week(test_tasks)
    assert_eq("  Current week is 1 (incomplete tasks in week 1)", current, 1)

    # Complete ALL week 1 tasks
    for t in test_tasks:
        if t["week"] == 1:
            t["status"] = "completed"
    current_after = get_current_week(test_tasks)
    assert_eq("  After completing week 1, current week = 2", current_after, 2)

    # ── 3f. Overdue detection ────────────────────────────────────────────────
    print("  3f. Overdue task detection:")
    overdue = get_overdue_tasks(test_tasks, current_week=2)
    # Week 1 is all completed, so 0 overdue
    assert_eq("  No overdue tasks after completing week 1", len(overdue), 0)

    # Reset a week-1 task to pending to simulate overdue
    test_tasks[0]["status"] = "pending"
    overdue2 = get_overdue_tasks(test_tasks, current_week=2)
    assert_eq("  1 overdue task when week 1 task is pending", len(overdue2), 1)

    # ── 3g. Completion merge (persistence) ──────────────────────────────────
    print("  3g. Completion data merge (persistence):")
    stored = {
        "goal_abc_w01_obj_00": {"status": "completed", "completed_at": "2025-10-01T10:00:00"},
        "goal_abc_w01_ex_00":  {"status": "in_progress", "completed_at": None},
    }
    fresh = extract_tasks_from_plan("goal_abc", plan)
    merged = merge_existing_completions(fresh, stored)

    merged_map = {t["id"]: t for t in merged}
    assert_eq("  Merged task 0 has status=completed",
              merged_map["goal_abc_w01_obj_00"]["status"], "completed")
    assert_eq("  Merged task ex_00 has status=in_progress",
              merged_map["goal_abc_w01_ex_00"]["status"], "in_progress")
    assert_eq("  Unmentioned task stays pending",
              merged_map["goal_abc_w01_obj_01"]["status"], "pending")

    # ── 3h. Validation report ────────────────────────────────────────────────
    print("  3h. Validation report generation:")
    goal_mock = {"id": "goal_abc", "title": "Learn Python", "goal_type": "coding", "total_weeks": 2}
    fresh_tasks = extract_tasks_from_plan("goal_abc", plan)
    report = generate_validation_report(goal_mock, fresh_tasks)

    assert_eq("  Report has goal_id",    report["goal_id"],    "goal_abc")
    assert_eq("  Report has plan_health", "plan_health" in report, True)
    assert_eq("  Report has current_week", "current_week" in report, True)
    assert_eq("  Report has recommendations", isinstance(report["recommendations"], list), True)
    assert_eq("  Empty plan has at_risk health", report["plan_health"], "at_risk")


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 4 — Multi-Agent Worker Coordination
# ─────────────────────────────────────────────────────────────────────────────

def test_s4_multiagent_coordination():
    """
    Test the SharedData blackboard coordination logic — verifying that
    workers pick up tasks in the correct order and workers do not process
    tasks out of sequence.
    """
    print("\nS4 — Multi-Agent Worker Coordination (SharedData)")
    print("─" * 50)

    from backend.app.shared_data import SharedData, GoalData, ProcessingStatus

    sd = SharedData()

    # ── 4a. Task creation ────────────────────────────────────────────────────
    print("  4a. Task creation and initial state:")
    goal = GoalData(
        id="g001",
        description="Learn Python for data science",
        user_id="user1",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        deadline=(datetime.now() + timedelta(weeks=8)).strftime("%Y-%m-%d"),
        status="pending"
    )
    goal.total_weeks = 8
    sd.add_task(goal)

    task = sd.get_task("g001")
    assert_true("  Task created in SharedData", task is not None)
    assert_eq("  Initial status is PENDING",
              task.status, ProcessingStatus.PENDING)
    assert_eq("  Results dict is empty", task.results, {})

    # ── 4b. Plan worker picks up task ────────────────────────────────────────
    print("  4b. Plan worker picks pending tasks:")
    pending = sd.get_pending_tasks()
    assert_eq("  1 pending task found", len(pending), 1)
    assert_eq("  Pending task ID matches", pending[0].goal.id, "g001")

    # ── 4c. Simulate plan generation ────────────────────────────────────────
    print("  4c. After plan generation, video/article workers activate:")
    sd.mark_task_processing("g001")
    assert_eq("  Status changed to PROCESSING",
              sd.get_task("g001").status, ProcessingStatus.PROCESSING)

    # Simulate plan result added
    with sd.lock:
        sd.tasks["g001"].results["plan"] = {"total_weeks": 8, "weekly_breakdown": []}

    # Video worker should now find this task
    tasks_needing_videos = sd.get_tasks_needing_videos()
    assert_eq("  Video worker finds 1 task needing videos",
              len(tasks_needing_videos), 1)

    # Article worker should also find it
    tasks_needing_articles = sd.get_tasks_needing_articles()
    assert_eq("  Article worker finds 1 task needing articles",
              len(tasks_needing_articles), 1)

    # ── 4d. Completed task not re-processed ──────────────────────────────────
    print("  4d. Completed tasks not re-processed:")
    with sd.lock:
        sd.tasks["g001"].results["youtube_videos"] = [{"title": "Python Tutorial"}]
        sd.tasks["g001"].results["articles"] = [{"title": "Python Guide"}]

    sd.update_task("g001", {"plan": {}, "youtube_videos": [], "articles": []})

    pending_after = sd.get_pending_tasks()
    assert_eq("  No more pending tasks", len(pending_after), 0)

    still_needs_videos = sd.get_tasks_needing_videos()
    assert_eq("  No tasks need videos after completion", len(still_needs_videos), 0)

    # ── 4e. Multiple concurrent goals ────────────────────────────────────────
    print("  4e. Multiple goals handled independently:")
    goal2 = GoalData(
        id="g002",
        description="Build a React portfolio site",
        user_id="user2",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        deadline=(datetime.now() + timedelta(weeks=6)).strftime("%Y-%m-%d"),
        status="pending"
    )
    goal2.total_weeks = 6
    sd.add_task(goal2)

    goal3 = GoalData(
        id="g003",
        description="Study machine learning fundamentals",
        user_id="user1",
        created_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        deadline=(datetime.now() + timedelta(weeks=12)).strftime("%Y-%m-%d"),
        status="pending"
    )
    goal3.total_weeks = 12
    sd.add_task(goal3)

    new_pending = sd.get_pending_tasks()
    assert_eq("  2 new pending tasks found", len(new_pending), 2)

    # User results isolation
    user1_results = sd.get_user_results("user1")
    user2_results = sd.get_user_results("user2")
    assert_eq("  user1 has 2 goals (g001 completed + g003 pending)",
              len(user1_results), 2)
    assert_eq("  user2 has 1 goal",
              len(user2_results), 1)

    # ── 4f. Cache key independence ───────────────────────────────────────────
    print("  4f. SmartCache TTL:")
    from backend.app.GoalProcessingSystem import SmartCache
    import time

    cache = SmartCache(max_age_seconds=1)
    cache.set("key1", "value1")
    assert_eq("  Cache hit before expiry",   cache.get("key1"), "value1")
    time.sleep(1.1)
    assert_eq("  Cache miss after TTL",      cache.get("key1"), None)


# ─────────────────────────────────────────────────────────────────────────────
# SCENARIO 5 — Agent Restriction JSON Integrity
# ─────────────────────────────────────────────────────────────────────────────

def test_s5_restriction_config():
    """Verify the agent_rules.json is valid JSON and contains required keys."""
    print("\nS5 — Agent Restriction Configuration Integrity")
    print("─" * 50)

    rules_path = os.path.join(
        os.path.dirname(__file__), "..", "restrictions", "agent_rules.json"
    )
    assert_true("  restrictions/agent_rules.json exists", os.path.exists(rules_path))

    with open(rules_path, "r", encoding="utf-8") as f:
        rules = json.load(f)

    required_keys = [
        "allowed_domains", "prohibited_domains", "response_guidelines",
        "goal_validation", "curriculum_restrictions"
    ]
    for key in required_keys:
        assert_true(f"  Key '{key}' present", key in rules)

    cs_keywords = rules["goal_validation"]["cs_signal_keywords"]
    assert_true("  CS signal keywords list not empty", len(cs_keywords) > 20)
    assert_true("  'python' in cs_signal_keywords", "python" in cs_keywords)
    assert_true("  'javascript' in cs_signal_keywords", "javascript" in cs_keywords)

    prohibited = rules["prohibited_domains"]["topics"]
    assert_true("  'fitness' in prohibited topics", "fitness" in prohibited)
    assert_true("  'language learning' or synonym in prohibited",
                any("language" in t for t in prohibited))

    allowed_types = rules["curriculum_restrictions"]["allowed_types"]
    rejected_types = rules["curriculum_restrictions"]["rejected_types"]
    assert_true("  'coding' allowed", "coding" in allowed_types)
    assert_true("  'fitness' rejected in curriculum", "fitness" in rejected_types)
    assert_true("  'language' rejected in curriculum", "language" in rejected_types)

    print("  Pedagogical rules:")
    rules_list = rules["response_guidelines"]["rules"]
    assert_true("  At least 5 pedagogical rules defined", len(rules_list) >= 5)


# ─────────────────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────────────────

def run_all():
    print("=" * 60)
    print("  BIGDREAM — SCENARIO TEST SUITE")
    print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    test_s1_cs_domain_restriction()
    test_s2_goal_type_detection()
    test_s3_task_state_machine()
    test_s4_multiagent_coordination()
    test_s5_restriction_config()

    total = len(_results)
    passed = sum(1 for _, ok in _results if ok)
    failed = total - passed

    print("\n" + "=" * 60)
    print(f"  RESULTS: {passed}/{total} passed", end="")
    if failed:
        print(f"  ({failed} FAILED)")
        print("\n  Failed tests:")
        for name, ok in _results:
            if not ok:
                print(f"    - {name}")
    else:
        print("  — ALL PASSED")
    print("=" * 60)
    return failed == 0


if __name__ == "__main__":
    success = run_all()
    sys.exit(0 if success else 1)
