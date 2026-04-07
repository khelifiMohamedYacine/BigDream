"""
Tests for PlanGenerator — all methods including Groq API calls (mocked).
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.app.plan_generator import PlanGenerator
from backend.app.shared_data import GoalData
from datetime import datetime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_goal(goal_id="g1", description="Learn Python", weeks=8):
    g = GoalData(
        id=goal_id,
        description=description,
        user_id="u1",
        created_at=datetime.now().isoformat(),
        deadline="2026-12-31",
        status="pending",
    )
    g.total_weeks = weeks
    g.timeline = f"{weeks} weeks"
    g.why_important = "Career growth"
    g.skill_level = "beginner"
    g.hours_per_week = "5h/week"
    g.success_metric = "Build a project"
    g.goal_type = "python_basics"
    return g


@pytest.fixture
def generator():
    sd = MagicMock()
    gen = PlanGenerator(sd)
    gen.set_db_manager(MagicMock())
    gen.groq_api_key = "test-key"
    return gen


# ===========================================================================
# _extract_core_goal
# ===========================================================================

class TestExtractCoreGoal:
    def test_splits_on_pipe(self, generator):
        result = generator._extract_core_goal("Learn Python | 8 weeks | beginner")
        assert result == "Learn Python"

    def test_no_pipe_returns_original(self, generator):
        result = generator._extract_core_goal("Learn Python basics")
        assert result == "Learn Python basics"

    def test_max_120_chars(self, generator):
        long = "A" * 200
        result = generator._extract_core_goal(long)
        assert len(result) <= 120


# ===========================================================================
# _quick_understanding
# ===========================================================================

class TestQuickUnderstanding:
    @pytest.mark.parametrize("goal,expected_type", [
        ("build a machine learning model", "ml_ai"),
        ("build a flask web app", "web_dev"),
        ("pandas data analysis", "data_science"),
        ("implement sorting algorithms", "algorithms"),
        ("object oriented programming", "python_oop"),
        ("automate tasks with scripts", "automation"),
        ("learn python from scratch", "python_basics"),
    ])
    def test_goal_type_detection(self, generator, goal, expected_type):
        result = generator._quick_understanding(goal)
        assert result["goal_type"] == expected_type

    def test_returns_required_keys(self, generator):
        result = generator._quick_understanding("learn python")
        assert "clean_title" in result
        assert "goal_type" in result
        assert "key_focus" in result
        assert "learner_level" in result
        assert "core_skills" in result

    def test_clean_title_is_capitalized(self, generator):
        result = generator._quick_understanding("learn python")
        assert result["clean_title"][0].isupper()

    def test_core_skills_is_list(self, generator):
        result = generator._quick_understanding("learn python")
        assert isinstance(result["core_skills"], list)


# ===========================================================================
# _bloom_schedule
# ===========================================================================

class TestBloomSchedule:
    def test_returns_string(self, generator):
        result = generator._bloom_schedule(8)
        assert isinstance(result, str)

    def test_contains_all_week_numbers(self, generator):
        result = generator._bloom_schedule(4)
        for w in range(1, 5):
            assert f"week {w}" in result

    def test_first_week_remember_level(self, generator):
        result = generator._bloom_schedule(8)
        assert "remember" in result

    def test_last_week_create_level(self, generator):
        result = generator._bloom_schedule(8)
        assert "create" in result


# ===========================================================================
# _parse_json_curriculum
# ===========================================================================

class TestParseJsonCurriculum:
    def test_valid_json_array_parsed(self, generator):
        raw = json.dumps([
            {
                "week": 1, "theme": "Basics", "bloom_level": "remember",
                "focus": "Variables", "learning_objectives": ["Obj1"],
                "practice_exercises": ["Ex1"], "spaced_review": [],
                "milestone_project": None,
                "psychological_hook": "Keep going!",
                "explanation": "Week 1",
            }
        ])
        result = generator._parse_json_curriculum(raw, 1, "python_basics", "Learn Python")
        assert len(result) == 1
        assert result[0]["week"] == 1

    def test_invalid_json_returns_empty(self, generator):
        result = generator._parse_json_curriculum("not json", 1, "python_basics", "Learn Python")
        assert result == []

    def test_no_array_found_returns_empty(self, generator):
        result = generator._parse_json_curriculum('{"key": "value"}', 1, "python_basics", "test")
        assert result == []

    def test_week_objects_have_required_keys(self, generator):
        raw = json.dumps([
            {
                "week": 1, "theme": "T", "bloom_level": "remember", "focus": "F",
                "learning_objectives": ["o"], "practice_exercises": ["e"],
                "spaced_review": [], "milestone_project": None,
                "psychological_hook": "!",  "explanation": "E",
            }
        ])
        result = generator._parse_json_curriculum(raw, 1, "python_basics", "test")
        week = result[0]
        assert "week" in week
        assert "theme" in week
        assert "learning_objectives" in week
        assert "practice_exercises" in week
        assert "status" in week

    def test_pads_to_requested_weeks(self, generator):
        raw = json.dumps([
            {"week": 1, "theme": "T", "bloom_level": "remember", "focus": "F",
             "learning_objectives": ["o"], "practice_exercises": ["e"],
             "spaced_review": [], "milestone_project": None,
             "psychological_hook": "!", "explanation": "E"}
        ])
        result = generator._parse_json_curriculum(raw, 3, "python_basics", "test")
        assert len(result) == 3


# ===========================================================================
# Fallback curricula (pure Python, no API)
# ===========================================================================

class TestFallbackCurricula:
    @pytest.mark.parametrize("method,goal_type", [
        ("_basics_curriculum", "python_basics"),
        ("_oop_curriculum", "python_oop"),
        ("_data_science_curriculum", "data_science"),
        ("_web_dev_curriculum", "web_dev"),
        ("_algorithms_curriculum", "algorithms"),
    ])
    def test_returns_list(self, generator, method, goal_type):
        result = getattr(generator, method)("test goal", 4)
        assert isinstance(result, list)

    def test_basics_returns_weeks(self, generator):
        result = generator._basics_curriculum("Learn Python", 4)
        assert all("week" in w for w in result)

    def test_psychology_fallback_selects_correct_curriculum(self, generator):
        result = generator._psychology_fallback("ml_ai", "ML goal", 2)
        assert isinstance(result, list)

    def test_make_week_returns_dict(self, generator):
        w = generator._make_week(1, "Theme", "remember", "Focus",
                                  ["obj"], ["ex"], ["review"], None, "hook")
        assert w["week"] == 1
        assert w["theme"] == "Theme"
        assert "learning_objectives" in w
        assert "practice_exercises" in w


# ===========================================================================
# _understand_goal (with mocked Groq)
# ===========================================================================

class TestUnderstandGoal:
    @pytest.mark.asyncio
    async def test_valid_groq_response_parsed(self, generator):
        groq_json = json.dumps({
            "clean_title": "Python Programming",
            "goal_type": "python_basics",
            "key_focus": "Python fundamentals",
            "learner_level": "beginner",
            "core_skills": ["variables", "loops"],
        })
        generator._groq_generate = AsyncMock(return_value=groq_json)
        result = await generator._understand_goal("learn python")
        assert result["goal_type"] == "python_basics"
        assert result["clean_title"] == "Python Programming"

    @pytest.mark.asyncio
    async def test_groq_failure_falls_back(self, generator):
        generator._groq_generate = AsyncMock(return_value="")
        result = await generator._understand_goal("learn python")
        assert "goal_type" in result
        assert "clean_title" in result

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back(self, generator):
        generator._groq_generate = AsyncMock(return_value="{invalid json")
        result = await generator._understand_goal("learn python")
        assert "goal_type" in result


# ===========================================================================
# _generate_curriculum (with mocked Groq)
# ===========================================================================

class TestGenerateCurriculum:
    @pytest.mark.asyncio
    async def test_returns_list_of_weeks(self, generator):
        understanding = {
            "goal_type": "python_basics", "key_focus": "Python",
            "learner_level": "beginner", "core_skills": ["variables"],
        }
        generator._groq_generate = AsyncMock(return_value="")
        result = await generator._generate_curriculum(understanding, 4)
        assert isinstance(result, list)
        assert len(result) == 4

    @pytest.mark.asyncio
    async def test_each_week_has_theme(self, generator):
        understanding = {
            "goal_type": "python_basics", "key_focus": "Python",
            "learner_level": "beginner", "core_skills": [],
        }
        generator._groq_generate = AsyncMock(return_value="")
        result = await generator._generate_curriculum(understanding, 2)
        assert all("theme" in w for w in result)


# ===========================================================================
# generate_plan (full integration with mocked Groq + DB)
# ===========================================================================

class TestGeneratePlan:
    @pytest.mark.asyncio
    async def test_generate_plan_returns_dict(self, generator):
        generator._groq_generate = AsyncMock(return_value="")
        plan = await generator.generate_plan(make_goal())
        assert isinstance(plan, dict)

    @pytest.mark.asyncio
    async def test_generate_plan_has_weekly_breakdown(self, generator):
        generator._groq_generate = AsyncMock(return_value="")
        plan = await generator.generate_plan(make_goal(weeks=4))
        assert "weekly_breakdown" in plan
        assert len(plan["weekly_breakdown"]) == 4

    @pytest.mark.asyncio
    async def test_generate_plan_saves_to_db(self, generator):
        generator._groq_generate = AsyncMock(return_value="")
        await generator.generate_plan(make_goal())
        generator.db_manager.save_learning_plan.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_plan_has_philosophy(self, generator):
        generator._groq_generate = AsyncMock(return_value="")
        plan = await generator.generate_plan(make_goal())
        assert "learning_philosophy" in plan

    @pytest.mark.asyncio
    async def test_generate_plan_has_core_principles(self, generator):
        generator._groq_generate = AsyncMock(return_value="")
        plan = await generator.generate_plan(make_goal())
        assert "core_principles" in plan
        assert isinstance(plan["core_principles"], list)

    @pytest.mark.asyncio
    async def test_generate_plan_with_groq_response(self, generator):
        curriculum = json.dumps([
            {
                "week": 1, "theme": "Variables", "bloom_level": "remember",
                "focus": "Learn variables", "learning_objectives": ["Understand variables"],
                "practice_exercises": ["Write a counter"], "spaced_review": [],
                "milestone_project": None, "psychological_hook": "You got this!",
                "explanation": "Week 1",
            }
        ])
        understanding = json.dumps({
            "clean_title": "Python Basics",
            "goal_type": "python_basics",
            "key_focus": "Python fundamentals",
            "learner_level": "beginner",
            "core_skills": ["variables", "loops"],
        })
        generator._groq_generate = AsyncMock(side_effect=[understanding, curriculum])
        plan = await generator.generate_plan(make_goal(weeks=1))
        assert plan["weekly_breakdown"][0]["theme"] == "Variables"
