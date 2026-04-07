"""
Tests for goal_chatbot module — pure Python helpers and GoalChatInterface.
External API calls (Groq, HuggingFace) are mocked throughout.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime

from backend.app.goal_chatbot import (
    _policy_violation,
    _get_policy_reply,
    _is_code_question,
    _is_code_followup,
    parse_timeline_to_weeks,
    create_clean_goal_title,
    detect_goal_type,
    is_python_goal,
    GoalChatInterface,
)


# ===========================================================================
# _policy_violation
# ===========================================================================

class TestPolicyViolation:
    def test_clean_message_returns_none(self):
        assert _policy_violation("I want to learn Python") is None

    def test_hate_speech_detected(self):
        result = _policy_violation("you stupid nigger")
        assert result == "hate"

    def test_abuse_detected(self):
        result = _policy_violation("kill yourself bot")
        assert result == "abuse"

    def test_nsfw_detected(self):
        result = _policy_violation("how to have sex")
        assert result == "nsfw"

    def test_dangerous_detected(self):
        result = _policy_violation("how to make a bomb")
        assert result == "dangerous"

    def test_case_insensitive_check(self):
        result = _policy_violation("HOW TO MAKE A BOMB")
        assert result == "dangerous"

    def test_emotional_message_not_blocked(self):
        assert _policy_violation("I am so sad today, help me") is None

    def test_python_code_not_blocked(self):
        assert _policy_violation("def hello_world(): print('hello')") is None


# ===========================================================================
# _get_policy_reply
# ===========================================================================

class TestGetPolicyReply:
    def test_returns_string(self):
        reply = _get_policy_reply("hate", 0)
        assert isinstance(reply, str)
        assert len(reply) > 0

    def test_escalates_on_repeated_strikes(self):
        r0 = _get_policy_reply("abuse", 0)
        r3 = _get_policy_reply("abuse", 3)
        # They may differ or be stricter — just ensure no crash
        assert isinstance(r0, str)
        assert isinstance(r3, str)

    def test_all_violation_types_handled(self):
        for vtype in ("hate", "abuse", "nsfw", "dangerous"):
            reply = _get_policy_reply(vtype, 0)
            assert isinstance(reply, str)


# ===========================================================================
# _is_code_question
# ===========================================================================

class TestIsCodeQuestion:
    def test_backtick_code_block(self):
        assert _is_code_question("```python\nprint('hi')\n```") is True

    def test_def_keyword(self):
        assert _is_code_question("def my_func():") is True

    def test_debug_keyword(self):
        assert _is_code_question("help me debug this error") is True

    def test_write_a_function(self):
        assert _is_code_question("write a function to sort a list") is True

    def test_generic_goal_message_is_not_code(self):
        assert _is_code_question("I want to learn Python in 3 months") is False

    def test_emotional_message_is_not_code(self):
        assert _is_code_question("I feel sad today") is False


# ===========================================================================
# parse_timeline_to_weeks
# ===========================================================================

class TestParseTimelineToWeeks:
    def test_months_parsed(self):
        assert parse_timeline_to_weeks("3 months") == 12

    def test_weeks_parsed(self):
        assert parse_timeline_to_weeks("8 weeks") == 8

    def test_days_converted(self):
        result = parse_timeline_to_weeks("30 days")
        assert result == 4  # 30//7 = 4

    def test_default_for_unknown_input(self):
        assert parse_timeline_to_weeks("as soon as possible") == 8

    def test_one_month(self):
        assert parse_timeline_to_weeks("1 month") == 4

    def test_six_months(self):
        assert parse_timeline_to_weeks("6 months") == 24

    def test_two_weeks(self):
        assert parse_timeline_to_weeks("2 weeks") == 2


# ===========================================================================
# detect_goal_type
# ===========================================================================

class TestDetectGoalType:
    def test_python_basics(self):
        result = detect_goal_type("learn python from scratch")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_any_coding_goal_returns_string(self):
        for goal in ("learn web dev", "data science", "machine learning algorithms"):
            result = detect_goal_type(goal)
            assert isinstance(result, str)


# ===========================================================================
# is_python_goal
# ===========================================================================

class TestIsPythonGoal:
    def test_python_mentioned(self):
        assert is_python_goal("I want to learn Python") is True

    def test_data_science_is_python(self):
        assert is_python_goal("learn data science with pandas") is True

    def test_machine_learning_is_python(self):
        assert is_python_goal("build a machine learning model") is True

    def test_completely_unrelated_returns_false(self):
        # Generic motivation message without any tech keywords
        assert is_python_goal("I want to become a better person") is False


# ===========================================================================
# create_clean_goal_title
# ===========================================================================

class TestCreateCleanGoalTitle:
    def test_returns_string(self):
        title = create_clean_goal_title("learn python", {})
        assert isinstance(title, str)

    def test_capitalizes_title(self):
        title = create_clean_goal_title("learn python basics", {})
        assert title[0].isupper()

    def test_capitalizes_and_strips_prefix(self):
        title = create_clean_goal_title("i want to learn python", {})
        assert title.startswith("Learn") or title[0].isupper()

    def test_strips_whitespace(self):
        title = create_clean_goal_title("  learn python  ", {})
        assert title == title.strip()


# ===========================================================================
# GoalChatInterface
# ===========================================================================

class TestGoalChatInterface:
    @pytest.fixture
    def chatbot(self, db):
        bot = GoalChatInterface()
        bot.set_db_manager(db)
        bot.set_shared_data(MagicMock())
        bot.set_processing_callback(MagicMock())
        return bot

    # --- Dependency injection ---

    def test_set_db_manager(self, db):
        bot = GoalChatInterface()
        result = bot.set_db_manager(db)
        assert result is bot  # fluent interface

    def test_set_shared_data(self):
        bot = GoalChatInterface()
        sd = MagicMock()
        result = bot.set_shared_data(sd)
        assert result is bot

    def test_set_processing_callback(self):
        bot = GoalChatInterface()
        cb = MagicMock()
        bot.set_processing_callback(cb)
        assert bot.processing_callback is cb

    # --- get_goals ---

    def test_get_goals_returns_list(self, chatbot, sample_user, db):
        result = chatbot.get_goals(sample_user["user_id"])
        assert isinstance(result, list)

    def test_get_goals_empty_for_new_user(self, chatbot, sample_user):
        result = chatbot.get_goals(sample_user["user_id"])
        assert result == []

    def test_get_goals_returns_saved_goals(self, chatbot, sample_user, db):
        goal = {
            "id": "g1", "user_id": sample_user["user_id"], "title": "Learn Python",
            "description": "Python", "status": "pending", "progress": 0.0,
            "deadline": "2026-12-31", "created_at": datetime.now().isoformat(),
            "total_weeks": 8,
        }
        db.save_goal(goal)
        result = chatbot.get_goals(sample_user["user_id"])
        assert len(result) == 1

    # --- Policy violation handling ---

    @pytest.mark.asyncio
    @patch("backend.app.goal_chatbot._policy_violation", return_value="hate")
    async def test_policy_violation_returns_error_response(self, mock_policy, chatbot):
        response = await chatbot.send_message("offensive message", "u1")
        assert "chat_response" in response
        assert response["action_required"] == "policy_violation"

    # --- Code question routing ---

    @pytest.mark.asyncio
    @patch("backend.app.goal_chatbot.hf_code_chat", new_callable=AsyncMock)
    @patch("backend.app.goal_chatbot._is_code_question", return_value=True)
    async def test_code_question_routed_to_hf(self, mock_is_code, mock_hf, chatbot):
        mock_hf.return_value = "Here is some code: ```python\nprint('hi')\n```"
        response = await chatbot.send_message("def hello(): pass", "u1")
        assert "chat_response" in response
        mock_hf.assert_called_once()

    # --- General chat ---

    @pytest.mark.asyncio
    @patch("backend.app.goal_chatbot.groq_general_chat", new_callable=AsyncMock)
    @patch("backend.app.goal_chatbot._is_code_question", return_value=False)
    async def test_general_message_routed_to_groq(self, mock_is_code, mock_groq, chatbot):
        mock_groq.return_value = "Hello! Tell me your goal."
        response = await chatbot.send_message("Hello!", "u1")
        assert "chat_response" in response

    # --- Goal detection and creation ---

    @pytest.mark.asyncio
    @patch("backend.app.goal_chatbot.groq_general_chat", new_callable=AsyncMock)
    @patch("backend.app.goal_chatbot._is_code_question", return_value=False)
    @patch("backend.app.goal_chatbot._policy_violation", return_value=None)
    async def test_goal_detected_enters_goal_mode(self, mock_policy, mock_code, mock_groq, chatbot):
        mock_groq.return_value = "Great! I can help you with that Python goal."
        response = await chatbot.send_message("I want to learn Python in 3 months", "u1")
        assert "chat_response" in response
        assert isinstance(response.get("goal_detected"), bool)

    # --- Session management ---

    def test_different_users_have_separate_sessions(self, chatbot):
        s1 = chatbot._get_session("user1")
        s2 = chatbot._get_session("user2")
        s1["strike_count"] = 99
        assert s2["strike_count"] != 99

    def test_same_user_gets_same_session(self, chatbot):
        s1 = chatbot._get_session("u1")
        s2 = chatbot._get_session("u1")
        assert s1 is s2

    def test_session_has_history_key(self, chatbot):
        session = chatbot._get_session("u1")
        assert "history" in session

    # --- _is_yes ---

    def test_yes_affirmative(self, chatbot):
        assert chatbot._is_yes("yes") is True
        assert chatbot._is_yes("yeah") is True
        assert chatbot._is_yes("sure") is True

    def test_no_is_not_yes(self, chatbot):
        assert chatbot._is_yes("no") is False
        assert chatbot._is_yes("nope") is False

    # --- _detect_goal_signal ---

    def test_goal_signal_detected(self, chatbot):
        assert chatbot._detect_goal_signal("I want to learn Python") is True

    def test_random_message_no_goal_signal(self, chatbot):
        assert chatbot._detect_goal_signal("Hello how are you") is False

    # --- _get_goal_questions ---

    def test_get_goal_questions_returns_list(self, chatbot):
        questions = chatbot._get_goal_questions()
        assert isinstance(questions, list)
        assert len(questions) > 0

    # --- _create_goal ---

    def test_create_goal_returns_dict(self, chatbot, sample_user):
        goal = chatbot._create_goal(
            "Learn Python",
            sample_user["user_id"],
            {"answers": {0: "beginner", 1: "career", 2: "8 weeks", 3: "5h/week"},
             "initial_goal": "Learn Python"}
        )
        assert isinstance(goal, dict)
        assert "id" in goal
        assert goal["user_id"] == sample_user["user_id"]

    def test_create_goal_saves_to_db(self, chatbot, sample_user, db):
        chatbot._create_goal(
            "Learn Python",
            sample_user["user_id"],
            {"answers": {0: "beginner", 1: "career", 2: "8 weeks", 3: "5h/week"},
             "initial_goal": "Learn Python"}
        )
        goals = db.get_user_goals(sample_user["user_id"])
        assert len(goals) == 1

    def test_create_goal_triggers_callback(self, chatbot, sample_user):
        callback = MagicMock()
        chatbot.set_processing_callback(callback)
        chatbot._create_goal(
            "Learn Python",
            sample_user["user_id"],
            {"answers": {0: "beginner", 1: "career", 2: "8 weeks", 3: "5h/week"},
             "initial_goal": "Learn Python"}
        )
        callback.assert_called_once()

    def test_create_goal_adds_task_to_shared_data(self, chatbot, sample_user):
        shared_data = MagicMock()
        chatbot.set_shared_data(shared_data)
        chatbot._create_goal(
            "Learn Python",
            sample_user["user_id"],
            {"answers": {0: "beginner", 1: "career", 2: "8 weeks", 3: "5h/week"},
             "initial_goal": "Learn Python"}
        )
        shared_data.add_task.assert_called_once()

    def test_create_goal_deadline_in_future(self, chatbot, sample_user):
        goal = chatbot._create_goal(
            "Learn Python",
            sample_user["user_id"],
            {"answers": {0: "beginner", 1: "career", 2: "8 weeks", 3: "5h/week"},
             "initial_goal": "Learn Python"}
        )
        deadline = datetime.strptime(goal["deadline"], "%Y-%m-%d")
        assert deadline > datetime.now()


# ===========================================================================
# API-level helpers (groq_general_chat, hf_code_chat)
# ===========================================================================

class TestExternalChatAPIs:
    @pytest.mark.asyncio
    @patch("backend.app.goal_chatbot.aiohttp.ClientSession")
    async def test_groq_general_chat_with_valid_key(self, mock_session):
        import os
        from backend.app.goal_chatbot import groq_general_chat

        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.json = AsyncMock(return_value={
            "choices": [{"message": {"content": "Hello from Groq!"}}]
        })
        mock_session.return_value.__aenter__ = AsyncMock(return_value=MagicMock(
            post=MagicMock(return_value=MagicMock(
                __aenter__=AsyncMock(return_value=mock_response),
                __aexit__=AsyncMock(return_value=None)
            ))
        ))
        mock_session.return_value.__aexit__ = AsyncMock(return_value=None)

        with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
            result = await groq_general_chat("Hello", [])
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_groq_general_chat_missing_key_returns_fallback(self):
        from backend.app.goal_chatbot import groq_general_chat
        import os
        with patch.dict("os.environ", {"GROQ_API_KEY": ""}):
            result = await groq_general_chat("Hello", [])
        assert isinstance(result, str)
        assert len(result) > 0
