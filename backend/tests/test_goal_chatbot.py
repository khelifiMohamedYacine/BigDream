"""
test_goal_chatbot.py
====================
Tests for pure-Python functions in goal_chatbot.py that do NOT require LLM calls.

Covered:
  is_python_goal(description)   — domain gating
  detect_goal_type(description) — CS sub-type classification
  Content moderation patterns   — blocked vs allowed phrases

No network calls are made in any test.
"""
import pytest
from backend.app.goal_chatbot import is_python_goal, detect_goal_type


# ===========================================================================
# is_python_goal — Python/CS domain gate
# ===========================================================================

class TestIsPythonGoal:
    # --- Accepted: Python-related goals ---
    @pytest.mark.parametrize("description", [
        "learn python for data science",
        "build a django web application",
        "master machine learning with pytorch",
        "understand algorithms and data structures in python",
        "deploy a flask api",
        "learn pandas and numpy for data analysis",
        "build a python automation script",
        "become a python developer in 6 months",
        "write clean python code",
        "learn asyncio and fastapi",
        "I want to learn Python from scratch",
        "get good at python programming",
        "build a web scraper using Python",
        "learn tensorflow for deep learning",
        "understand python oop concepts",
    ])
    def test_python_goal_accepted(self, description):
        assert is_python_goal(description) is True, f"Should accept: {description!r}"

    # --- Rejected: non-Python goals ---
    @pytest.mark.parametrize("description", [
        "get six pack abs in 3 months",
        "learn to speak french fluently",
        "become a better guitarist",
        "start a dropshipping business",
        "lose 10kg in 8 weeks",
        "improve my painting skills",
        "read 52 books this year",
        "learn to cook Italian food",
        "run a marathon this year",
        "grow my Instagram following",
    ])
    def test_non_python_goal_rejected(self, description):
        assert is_python_goal(description) is False, f"Should reject: {description!r}"

    def test_empty_string_rejected(self):
        assert is_python_goal("") is False

    def test_whitespace_only_rejected(self):
        assert is_python_goal("   ") is False

    def test_case_insensitive_python(self):
        assert is_python_goal("LEARN PYTHON TODAY") is True

    def test_case_insensitive_django(self):
        assert is_python_goal("BUILD A DJANGO APP") is True

    def test_partial_match_pandas(self):
        assert is_python_goal("master pandas for analysis") is True

    def test_non_cs_does_not_match_despite_similar_words(self):
        # "program" appears but has no Python keywords
        assert is_python_goal("program my daily routine") is False


# ===========================================================================
# detect_goal_type — CS sub-type classification
# ===========================================================================

class TestDetectGoalType:
    # All valid CS inputs should return "coding"
    @pytest.mark.parametrize("description", [
        "learn python web scraping",
        "master pytorch deep learning",
        "build a react dashboard",
        "understand java spring framework",
        "write sql queries for postgres",
        "set up docker and kubernetes",
        "study penetration testing",
        "solve leetcode hard problems",
        "learn c++ for competitive coding",
        "build a flutter mobile app",
        "get good at python programming",
        "build a django rest API",
    ])
    def test_cs_goals_return_coding(self, description):
        result = detect_goal_type(description)
        assert result == "coding", f"Expected 'coding' for: {description!r}, got {result!r}"

    # Non-CS inputs must NOT return non-CS specific types
    FORBIDDEN_TYPES = {"fitness", "language", "creative", "business", "general"}

    @pytest.mark.parametrize("description", [
        "get fit",
        "learn spanish",
        "start a business",
        "paint watercolors",
    ])
    def test_non_cs_not_in_forbidden_types(self, description):
        result = detect_goal_type(description)
        assert result not in self.FORBIDDEN_TYPES, (
            f"detect_goal_type({description!r}) returned forbidden type {result!r}"
        )

    def test_return_value_is_string(self):
        assert isinstance(detect_goal_type("learn python"), str)

    def test_return_value_non_empty(self):
        assert len(detect_goal_type("learn python")) > 0

    def test_empty_input_does_not_crash(self):
        result = detect_goal_type("")
        assert isinstance(result, str)

    def test_coding_type_for_automation(self):
        assert detect_goal_type("write a python automation script") == "coding"


# ===========================================================================
# Content moderation (pattern testing without LLM)
# ===========================================================================

class TestContentModeration:
    """
    Test the private moderation lists indirectly by verifying that the
    module-level constants are defined and populated correctly.
    """

    def test_hate_terms_list_exists_and_non_empty(self):
        from backend.app.goal_chatbot import _HATE_TERMS
        assert isinstance(_HATE_TERMS, list)
        assert len(_HATE_TERMS) > 0

    def test_abuse_patterns_list_exists_and_non_empty(self):
        from backend.app.goal_chatbot import _ABUSE_PATTERNS
        assert isinstance(_ABUSE_PATTERNS, list)
        assert len(_ABUSE_PATTERNS) > 0

    def test_nsfw_patterns_list_exists_and_non_empty(self):
        from backend.app.goal_chatbot import _NSFW_PATTERNS
        assert isinstance(_NSFW_PATTERNS, list)
        assert len(_NSFW_PATTERNS) > 0

    def test_dangerous_patterns_list_exists_and_non_empty(self):
        from backend.app.goal_chatbot import _DANGEROUS_PATTERNS
        assert isinstance(_DANGEROUS_PATTERNS, list)
        assert len(_DANGEROUS_PATTERNS) > 0

    def test_hate_terms_are_lowercase(self):
        from backend.app.goal_chatbot import _HATE_TERMS
        for term in _HATE_TERMS:
            assert term == term.lower(), f"Hate term not lowercase: {term!r}"

    def test_dangerous_patterns_include_bomb(self):
        from backend.app.goal_chatbot import _DANGEROUS_PATTERNS
        assert any("bomb" in p for p in _DANGEROUS_PATTERNS)

    def test_nsfw_contains_expected_patterns(self):
        from backend.app.goal_chatbot import _NSFW_PATTERNS
        has_explicit = any(
            "how to fuck" in p or "sex" in p or "porn" in p
            for p in _NSFW_PATTERNS
        )
        assert has_explicit

    def test_abuse_patterns_include_kys(self):
        from backend.app.goal_chatbot import _ABUSE_PATTERNS
        assert any("kys" in p for p in _ABUSE_PATTERNS)


# ===========================================================================
# GROQ and CODE_SIGNALS constants
# ===========================================================================

class TestConstants:
    def test_code_signals_are_defined(self):
        from backend.app.goal_chatbot import CODE_SIGNALS
        assert isinstance(CODE_SIGNALS, list)
        assert len(CODE_SIGNALS) > 0

    def test_code_signals_include_backticks(self):
        from backend.app.goal_chatbot import CODE_SIGNALS
        assert "```" in CODE_SIGNALS

    def test_code_signals_include_def(self):
        from backend.app.goal_chatbot import CODE_SIGNALS
        assert "def " in CODE_SIGNALS

    def test_system_prompt_is_string(self):
        from backend.app.goal_chatbot import SYSTEM_PROMPT
        assert isinstance(SYSTEM_PROMPT, str)
        assert len(SYSTEM_PROMPT) > 100

    def test_code_system_prompt_is_string(self):
        from backend.app.goal_chatbot import CODE_SYSTEM_PROMPT
        assert isinstance(CODE_SYSTEM_PROMPT, str)
        assert len(CODE_SYSTEM_PROMPT) > 50

    def test_groq_model_constant(self):
        from backend.app.goal_chatbot import GROQ_MODEL
        assert isinstance(GROQ_MODEL, str)
        assert len(GROQ_MODEL) > 0
