"""Tests for ask_user tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from hooty.tools.ask_user_tools import (
    NO_RESPONSE,
    AskUserTools,
    _ChecklistParseResult,
    _ask_user_prompt,
    _do_prompt,
    _format_checklist_answers,
    _format_multi_answers,
    _parse_checklist,
    _parse_choices,
    _parse_multi_questions,
)
from hooty.ui import MultiQuestion


# ---------------------------------------------------------------------------
# _parse_choices
# ---------------------------------------------------------------------------

class TestParseChoices:
    def test_comma_separated(self) -> None:
        assert _parse_choices("pytest, unittest, nose2") == ["pytest", "unittest", "nose2"]

    def test_newline_separated(self) -> None:
        assert _parse_choices("pytest\nunittest\nnose2") == ["pytest", "unittest", "nose2"]

    def test_empty_items_stripped(self) -> None:
        assert _parse_choices("a,,b, ,c") == ["a", "b", "c"]

    def test_single_item(self) -> None:
        assert _parse_choices("only") == ["only"]


# ---------------------------------------------------------------------------
# _do_prompt — tests using mocked UI selectors
# ---------------------------------------------------------------------------

class TestDoPrompt:
    """Test the prompt logic with mocked number_select / text_input."""

    def test_free_text(self) -> None:
        with patch("hooty.tools.ask_user_tools.text_input", return_value="snake_case"):
            assert _do_prompt("Naming convention?", None) == "snake_case"

    def test_choice_by_index(self) -> None:
        choices = ["pytest", "unittest", "nose2"]
        with patch("hooty.tools.ask_user_tools.number_select", return_value=0):
            assert _do_prompt("Framework?", choices) == "pytest"

    def test_choice_last_index(self) -> None:
        choices = ["pytest", "unittest", "nose2"]
        with patch("hooty.tools.ask_user_tools.number_select", return_value=2):
            assert _do_prompt("Framework?", choices) == "nose2"

    def test_choice_cancel_returns_no_response(self) -> None:
        choices = ["pytest", "unittest"]
        with patch("hooty.tools.ask_user_tools.number_select", return_value=None):
            assert _do_prompt("Framework?", choices) == NO_RESPONSE

    def test_empty_text_returns_no_response(self) -> None:
        with patch("hooty.tools.ask_user_tools.text_input", return_value=None):
            assert _do_prompt("Question?", None) == NO_RESPONSE

    def test_empty_string_returns_no_response(self) -> None:
        with patch("hooty.tools.ask_user_tools.text_input", return_value=""):
            assert _do_prompt("Question?", None) == NO_RESPONSE

    def test_choice_other_returns_text(self) -> None:
        choices = ["pytest", "unittest"]
        with patch("hooty.tools.ask_user_tools.number_select", return_value="my framework"):
            assert _do_prompt("Framework?", choices) == "my framework"


# ---------------------------------------------------------------------------
# _ask_user_prompt — Live pause/resume behaviour
# ---------------------------------------------------------------------------

class TestAskUserPrompt:
    """Verify that the Live instance is properly paused and resumed."""

    def test_live_stop_and_start(self) -> None:
        mock_live = MagicMock()
        with (
            patch("hooty.tools.ask_user_tools._active_live", [mock_live]),
            patch("hooty.tools.ask_user_tools._do_prompt", return_value="answer"),
        ):
            result = _ask_user_prompt("Q?", None)

        assert result == "answer"
        mock_live.stop.assert_called_once()
        mock_live.start.assert_called_once()

    def test_live_resumed_on_exception(self) -> None:
        mock_live = MagicMock()
        with (
            patch("hooty.tools.ask_user_tools._active_live", [mock_live]),
            patch("hooty.tools.ask_user_tools._do_prompt", side_effect=KeyboardInterrupt),
        ):
            with pytest.raises(KeyboardInterrupt):
                _ask_user_prompt("Q?", None)

        mock_live.stop.assert_called_once()
        mock_live.start.assert_called_once()

    def test_no_live(self) -> None:
        with (
            patch("hooty.tools.ask_user_tools._active_live", [None]),
            patch("hooty.tools.ask_user_tools._do_prompt", return_value="ok"),
        ):
            assert _ask_user_prompt("Q?", None) == "ok"


# ---------------------------------------------------------------------------
# AskUserTools — Toolkit integration
# ---------------------------------------------------------------------------

class TestAskUserToolkit:
    def test_toolkit_name(self) -> None:
        toolkit = AskUserTools()
        assert toolkit.name == "ask_user_tools"

    def test_has_instructions(self) -> None:
        toolkit = AskUserTools()
        assert toolkit.instructions is not None
        assert "ask_user" in toolkit.instructions

    def test_function_registered(self) -> None:
        toolkit = AskUserTools()
        func_names = [f.name for f in toolkit.functions.values()]
        assert "ask_user" in func_names

    def test_ask_user_delegates(self) -> None:
        toolkit = AskUserTools()
        with patch("hooty.tools.ask_user_tools._ask_user_prompt", return_value="yes") as mock_prompt:
            result = toolkit.ask_user("Continue?", None)

        assert result == "yes"
        mock_prompt.assert_called_once_with("Continue?", None)

    def test_ask_user_with_choices(self) -> None:
        toolkit = AskUserTools()
        with patch("hooty.tools.ask_user_tools._ask_user_prompt", return_value="pytest") as mock_prompt:
            result = toolkit.ask_user("Framework?", "pytest,unittest")

        assert result == "pytest"
        mock_prompt.assert_called_once_with("Framework?", ["pytest", "unittest"])


# ---------------------------------------------------------------------------
# _parse_multi_questions
# ---------------------------------------------------------------------------

class TestParseMultiQuestions:
    def test_basic_multi_q(self) -> None:
        text = (
            "Please answer:\n\n"
            "**Q1. Which CLI library?**\n"
            "1. argparse\n"
            "2. typer\n\n"
            "**Q2. Include tests?**\n"
            "1. Yes\n"
            "2. No\n"
        )
        result = _parse_multi_questions(text)
        assert result is not None
        assert len(result) == 2
        assert result[0].choices == ["argparse", "typer"]
        assert result[1].choices == ["Yes", "No"]
        assert result[0].intro == "Please answer:"

    def test_heading_style_q(self) -> None:
        text = (
            "## Q1 Library choice\n"
            "1. Flask\n"
            "2. FastAPI\n\n"
            "## Q2 Database\n"
            "1. PostgreSQL\n"
            "2. SQLite\n"
        )
        result = _parse_multi_questions(text)
        assert result is not None
        assert len(result) == 2

    def test_no_choices(self) -> None:
        text = (
            "**Q1. Name your module**\n\n"
            "**Q2. Pick a color**\n"
        )
        result = _parse_multi_questions(text)
        assert result is not None
        assert len(result) == 2
        assert result[0].choices == []
        assert result[1].choices == []

    def test_single_q_returns_result(self) -> None:
        text = "**Q1. Only one question**\n1. Option A\n2. Option B\n"
        result = _parse_multi_questions(text)
        assert result is not None
        assert len(result) == 1
        assert result[0].choices == ["Option A", "Option B"]

    def test_no_q_pattern_returns_none(self) -> None:
        text = "Just a simple question with no Q1/Q2 pattern."
        assert _parse_multi_questions(text) is None

    def test_plain_q_format(self) -> None:
        text = (
            "Q1. First question\n"
            "1. A\n"
            "2. B\n\n"
            "Q2. Second question\n"
            "1. C\n"
            "2. D\n"
        )
        result = _parse_multi_questions(text)
        assert result is not None
        assert len(result) == 2

    def test_three_questions(self) -> None:
        text = (
            "**Q1. A?**\n1. X\n"
            "**Q2. B?**\n1. Y\n"
            "**Q3. C?**\n1. Z\n"
        )
        result = _parse_multi_questions(text)
        assert result is not None
        assert len(result) == 3


# ---------------------------------------------------------------------------
# _parse_checklist
# ---------------------------------------------------------------------------

class TestParseChecklist:
    def test_basic_checklist(self) -> None:
        text = (
            "Enable the following features?\n\n"
            "- [ ] Unit tests\n"
            "- [x] Linting\n"
            "- [ ] CI/CD\n"
        )
        result = _parse_checklist(text)
        assert result is not None
        assert result.items == ["Unit tests", "Linting", "CI/CD"]
        assert result.defaults == [False, True, False]
        assert "Enable" in result.subtitle

    def test_all_unchecked(self) -> None:
        text = "- [ ] A\n- [ ] B\n"
        result = _parse_checklist(text)
        assert result is not None
        assert result.defaults == [False, False]

    def test_single_item_returns_none(self) -> None:
        text = "- [ ] Only one item\n"
        assert _parse_checklist(text) is None

    def test_no_checklist_returns_none(self) -> None:
        text = "Just a plain question."
        assert _parse_checklist(text) is None

    def test_star_bullet(self) -> None:
        text = "* [ ] Alpha\n* [x] Beta\n"
        result = _parse_checklist(text)
        assert result is not None
        assert result.items == ["Alpha", "Beta"]

    def test_uppercase_x(self) -> None:
        text = "- [X] Checked\n- [ ] Unchecked\n"
        result = _parse_checklist(text)
        assert result is not None
        assert result.defaults == [True, False]


# ---------------------------------------------------------------------------
# _format_multi_answers
# ---------------------------------------------------------------------------

class TestFormatMultiAnswers:
    def test_basic_format(self) -> None:
        questions = [
            MultiQuestion(title="**Q1. CLI?**", choices=["argparse", "typer"]),
            MultiQuestion(title="**Q2. Tests?**", choices=["Yes", "No"]),
        ]
        answers = ["typer", "Yes"]
        result = _format_multi_answers(questions, answers)
        assert "Q1. CLI?" in result
        assert "typer" in result
        assert "Q2. Tests?" in result
        assert "Yes" in result

    def test_with_comment(self) -> None:
        questions = [
            MultiQuestion(title="Q1. A?", choices=["X"]),
        ]
        answers = ["X", "Comment: extra info"]
        result = _format_multi_answers(questions, answers)
        assert "Comment: extra info" in result

    def test_missing_answer(self) -> None:
        questions = [
            MultiQuestion(title="Q1. A?", choices=["X"]),
            MultiQuestion(title="Q2. B?", choices=["Y"]),
        ]
        answers = ["X"]  # Only one answer for two questions
        result = _format_multi_answers(questions, answers)
        assert "(no answer)" in result


# ---------------------------------------------------------------------------
# _format_checklist_answers
# ---------------------------------------------------------------------------

class TestFormatChecklistAnswers:
    def test_basic_format(self) -> None:
        cl = _ChecklistParseResult(
            subtitle="Enable features?",
            items=["Tests", "Lint", "CI"],
            defaults=[False, False, False],
        )
        result = _format_checklist_answers(cl, [True, False, True], "")
        assert "- Tests: Yes" in result
        assert "- Lint: No" in result
        assert "- CI: Yes" in result

    def test_with_comment(self) -> None:
        cl = _ChecklistParseResult(
            subtitle="",
            items=["A", "B"],
            defaults=[False, False],
        )
        result = _format_checklist_answers(cl, [True, True], "looks good")
        assert "Comment: looks good" in result

    def test_no_comment(self) -> None:
        cl = _ChecklistParseResult(
            subtitle="",
            items=["A"],
            defaults=[False],
        )
        result = _format_checklist_answers(cl, [False], "")
        assert "Comment" not in result


# ---------------------------------------------------------------------------
# _do_prompt — multi-Q and checklist integration
# ---------------------------------------------------------------------------

class TestDoPromptMultiQ:
    """Test that _do_prompt dispatches to wizard for multi-Q patterns."""

    def test_multi_q_dispatches_to_wizard(self) -> None:
        question = (
            "**Q1. CLI?**\n1. argparse\n2. typer\n\n"
            "**Q2. Tests?**\n1. Yes\n2. No\n"
        )
        with patch(
            "hooty.tools.ask_user_tools.multi_question_wizard",
            return_value=["typer", "Yes"],
        ):
            result = _do_prompt(question, None)
        assert "typer" in result

    def test_single_q_dispatches_to_wizard(self) -> None:
        question = "**Q1. CLI library?**\n1. argparse\n2. typer\n"
        with patch(
            "hooty.tools.ask_user_tools.multi_question_wizard",
            return_value=["typer"],
        ):
            result = _do_prompt(question, None)
        assert "typer" in result

    def test_multi_q_cancel(self) -> None:
        question = "**Q1. A?**\n1. X\n**Q2. B?**\n1. Y\n"
        with patch(
            "hooty.tools.ask_user_tools.multi_question_wizard",
            return_value=None,
        ):
            result = _do_prompt(question, None)
        assert result == NO_RESPONSE


class TestDoPromptChecklist:
    """Test that _do_prompt dispatches to checklist for checkbox patterns."""

    def test_checklist_dispatches(self) -> None:
        question = "Enable?\n- [ ] Tests\n- [ ] Lint\n"
        with patch(
            "hooty.tools.ask_user_tools.checklist_input",
            return_value=([True, False], "note"),
        ):
            result = _do_prompt(question, None)
        assert "Tests: Yes" in result
        assert "Lint: No" in result

    def test_checklist_cancel(self) -> None:
        question = "Enable?\n- [ ] A\n- [ ] B\n"
        with patch(
            "hooty.tools.ask_user_tools.checklist_input",
            return_value=None,
        ):
            result = _do_prompt(question, None)
        assert result == NO_RESPONSE
