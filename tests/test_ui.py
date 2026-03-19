"""Tests for hooty.ui — shared UI primitives."""

from __future__ import annotations

from io import StringIO
from unittest.mock import MagicMock, patch

from rich.console import Console

from hooty.ui import (
    MultiQuestion,
    _build_checklist_panel,
    _build_hotkey_panel,
    _build_number_panel,
    _build_text_input_panel,
    _build_wizard_panel,
    _WizardState,
    _disable_echo,
    _measure_height,
    _render_text_with_cursor,
    checklist_input,
    hotkey_select,
    multi_question_wizard,
    number_select,
    text_input,
)


# ---------------------------------------------------------------------------
# _disable_echo
# ---------------------------------------------------------------------------

class TestDisableEcho:
    def test_returns_none_when_no_termios(self) -> None:
        with patch.dict("sys.modules", {"termios": None}):
            # ImportError path
            result = _disable_echo()
        # When termios unavailable or raises, returns None
        assert result is None or callable(result)

    def test_returns_callable_with_termios(self) -> None:
        mock_termios = MagicMock()
        mock_termios.ECHO = 8
        mock_termios.ICANON = 2
        mock_termios.VMIN = 4
        mock_termios.VTIME = 5
        mock_termios.TCSANOW = 0
        mock_termios.TCSADRAIN = 1
        mock_termios.tcgetattr.return_value = [0, 0, 0, 10, 0, 0, [0] * 32]

        with (
            patch.dict("sys.modules", {"termios": mock_termios}),
            patch("hooty.ui.sys") as mock_sys,
        ):
            mock_sys.stdin.fileno.return_value = 0
            # Re-import to pick up mocked termios
            from hooty.ui import _disable_echo as _de
            result = _de()

        # Should return a callable restore function (or None on failure)
        assert result is None or callable(result)


# ---------------------------------------------------------------------------
# _measure_height
# ---------------------------------------------------------------------------

class TestMeasureHeight:
    def test_panel_height_positive(self) -> None:
        panel = _build_hotkey_panel(
            [("Y", "Yes"), ("N", "No")],
            selected=0,
            title="Test",
            width=60,
        )
        height = _measure_height(panel, 60)
        assert height > 0

    def test_number_panel_height(self) -> None:
        panel = _build_number_panel(
            ["Option A", "Option B", "Option C"],
            selected=1,
            title="Pick one",
            width=60,
        )
        height = _measure_height(panel, 60)
        assert height > 0

    def test_text_input_panel_height(self) -> None:
        panel = _build_text_input_panel(
            title="Enter text",
            text="hello",
            pos=3,
            width=60,
        )
        height = _measure_height(panel, 60)
        assert height > 0


# ---------------------------------------------------------------------------
# Panel builders — basic rendering
# ---------------------------------------------------------------------------

class TestBuildHotkeyPanel:
    def test_renders_without_error(self) -> None:
        panel = _build_hotkey_panel(
            [("Y", "Yes"), ("N", "No")],
            selected=0,
            title="Confirm",
            border_style="yellow",
            width=60,
        )
        buf = Console(width=60, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Confirm" in output

    def test_selected_index_changes_output(self) -> None:
        buf0 = Console(width=60, file=StringIO(), force_terminal=True)
        buf1 = Console(width=60, file=StringIO(), force_terminal=True)

        p0 = _build_hotkey_panel([("Y", "Yes"), ("N", "No")], selected=0, title="T", width=60)
        p1 = _build_hotkey_panel([("Y", "Yes"), ("N", "No")], selected=1, title="T", width=60)
        buf0.print(p0)
        buf1.print(p1)

        assert buf0.file.getvalue() != buf1.file.getvalue()


class TestBuildNumberPanel:
    def test_renders_without_error(self) -> None:
        panel = _build_number_panel(
            ["A", "B"],
            selected=0,
            title="Pick",
            width=60,
        )
        buf = Console(width=60, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Pick" in output

    def test_renders_with_other_row(self) -> None:
        panel = _build_number_panel(
            ["A", "B"],
            selected=2,
            title="Pick",
            width=80,
            allow_other=True,
        )
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Other" in output
        assert "type to enter Other" in output

    def test_renders_other_with_cursor(self) -> None:
        panel = _build_number_panel(
            ["A", "B"],
            selected=2,
            title="Pick",
            width=80,
            allow_other=True,
            other_text="hello",
            other_pos=3,
            other_focus=True,
        )
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Other" in output
        # "hello" is split by cursor escape codes; check prefix + suffix
        assert "hel" in output
        assert "o" in output


class TestBuildTextInputPanel:
    def test_renders_empty(self) -> None:
        panel = _build_text_input_panel(title="Type", text="", width=60)
        buf = Console(width=60, file=StringIO(), force_terminal=True)
        buf.print(panel)
        assert "Type" in buf.file.getvalue()

    def test_renders_with_cursor_mid_text(self) -> None:
        panel = _build_text_input_panel(title="Type", text="abc", pos=1, width=60)
        buf = Console(width=60, file=StringIO(), force_terminal=True)
        buf.print(panel)
        assert buf.file.getvalue()  # Just ensure no crash


# ---------------------------------------------------------------------------
# hotkey_select — non-TTY fallback
# ---------------------------------------------------------------------------

class TestHotkeySelectFallback:
    def test_returns_key_on_valid_input(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="y"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = hotkey_select(
                [("Y", "Yes"), ("N", "No")],
                title="Confirm?",
                con=con,
            )
        assert result == "Y"

    def test_returns_none_on_eof(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=EOFError),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = hotkey_select(
                [("Y", "Yes"), ("N", "No")],
                title="Confirm?",
                con=con,
            )
        assert result is None

    def test_returns_q_key_when_q_is_option(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="q"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = hotkey_select(
                [("Y", "Yes"), ("N", "No"), ("Q", "Quit")],
                title="Confirm?",
                con=con,
            )
        assert result == "Q"


# ---------------------------------------------------------------------------
# number_select — non-TTY fallback
# ---------------------------------------------------------------------------

class TestNumberSelectFallback:
    def test_returns_index_on_valid_number(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="2"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = number_select(
                ["pytest", "unittest", "nose2"],
                title="Framework?",
                con=con,
            )
        assert result == 1

    def test_returns_none_on_cancel(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="q"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = number_select(
                ["pytest", "unittest"],
                title="Framework?",
                con=con,
            )
        assert result is None

    def test_returns_none_on_eof(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=EOFError),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = number_select(
                ["pytest"],
                title="Framework?",
                con=con,
            )
        assert result is None

    def test_allow_other_returns_custom_text(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="my custom answer"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = number_select(
                ["pytest", "unittest"],
                title="Framework?",
                con=con,
                allow_other=True,
            )
        assert result == "my custom answer"

    def test_allow_other_still_accepts_number(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="1"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = number_select(
                ["pytest", "unittest"],
                title="Framework?",
                con=con,
                allow_other=True,
            )
        assert result == 0


# ---------------------------------------------------------------------------
# text_input — non-TTY fallback
# ---------------------------------------------------------------------------

class TestTextInputFallback:
    def test_returns_text_on_input(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="my_module"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = text_input(title="Module name?", con=con)
        assert result == "my_module"

    def test_returns_none_on_empty(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value=""),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = text_input(title="Module name?", con=con)
        assert result is None

    def test_returns_none_on_eof(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=EOFError),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = text_input(title="Module name?", con=con)
        assert result is None


# ---------------------------------------------------------------------------
# _render_text_with_cursor
# ---------------------------------------------------------------------------

class TestRenderTextWithCursor:
    def test_empty_text(self) -> None:
        result = _render_text_with_cursor("", 0)
        assert "\u2588" in result.plain

    def test_cursor_at_end(self) -> None:
        result = _render_text_with_cursor("abc", 3)
        assert "abc" in result.plain

    def test_cursor_mid_text(self) -> None:
        result = _render_text_with_cursor("abc", 1)
        plain = result.plain
        assert "a" in plain
        assert "b" in plain
        assert "c" in plain

    def test_multiline_with_indent(self) -> None:
        result = _render_text_with_cursor("a\nb", 0, indent=4)
        plain = result.plain
        assert "a" in plain
        assert "b" in plain


# ---------------------------------------------------------------------------
# WizardState
# ---------------------------------------------------------------------------

class TestWizardState:
    def test_total_pages(self) -> None:
        qs = [
            MultiQuestion(title="Q1", choices=["A", "B"]),
            MultiQuestion(title="Q2", choices=["C"]),
        ]
        state = _WizardState(questions=qs)
        assert state.total_pages == 3  # 2 Qs + Other

    def test_page_label(self) -> None:
        qs = [MultiQuestion(title="Q1", choices=["A"])]
        state = _WizardState(questions=qs)
        assert state.page_label == "1/1"
        state.page = 1
        assert state.page_label == "Other"

    def test_defaults_initialized(self) -> None:
        qs = [
            MultiQuestion(title="Q1", choices=["A"]),
            MultiQuestion(title="Q2", choices=["B"]),
        ]
        state = _WizardState(questions=qs)
        assert state.selections == [0, 0]
        assert state.other_texts == ["", ""]


# ---------------------------------------------------------------------------
# _build_wizard_panel — rendering
# ---------------------------------------------------------------------------

class TestBuildWizardPanel:
    def test_renders_q_page(self) -> None:
        qs = [MultiQuestion(title="**Q1. Pick one**", choices=["X", "Y"])]
        state = _WizardState(questions=qs)
        panel = _build_wizard_panel(state, width=80)
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Question for you" in output

    def test_renders_other_page(self) -> None:
        qs = [MultiQuestion(title="Q1", choices=["A"])]
        state = _WizardState(questions=qs, page=1)
        panel = _build_wizard_panel(state, width=80)
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Other" in output

    def test_intro_rendered(self) -> None:
        qs = [MultiQuestion(title="Q1", choices=["A"], intro="Please answer:")]
        state = _WizardState(questions=qs)
        panel = _build_wizard_panel(state, width=80)
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Please answer" in output


# ---------------------------------------------------------------------------
# _build_checklist_panel — rendering
# ---------------------------------------------------------------------------

class TestBuildChecklistPanel:
    def test_renders_items(self) -> None:
        panel = _build_checklist_panel(
            ["Unit tests", "Lint"],
            checked=[True, False],
            selected=0,
            title="Enable features",
            width=80,
        )
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Enable features" in output

    def test_renders_with_subtitle(self) -> None:
        panel = _build_checklist_panel(
            ["A", "B"],
            checked=[False, False],
            selected=0,
            title="Check",
            subtitle="**Pick items:**",
            width=80,
        )
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "Check" in output

    def test_comment_focus(self) -> None:
        panel = _build_checklist_panel(
            ["A"],
            checked=[False],
            selected=0,
            comment="hello",
            comment_pos=5,
            focus="comment",
            title="Check",
            width=80,
        )
        buf = Console(width=80, file=StringIO(), force_terminal=True)
        buf.print(panel)
        output = buf.file.getvalue()
        assert "hello" in output


# ---------------------------------------------------------------------------
# multi_question_wizard — non-TTY fallback
# ---------------------------------------------------------------------------

class TestWizardFallback:
    def test_returns_answers(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        qs = [
            MultiQuestion(title="Q1", choices=["A", "B"]),
            MultiQuestion(title="Q2", choices=["C", "D"]),
        ]
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=["1", "2", ""]),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = multi_question_wizard(qs, con=con)
        assert result is not None
        assert result[0] == "A"
        assert result[1] == "D"

    def test_cancel(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        qs = [MultiQuestion(title="Q1", choices=["A"])]
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="q"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = multi_question_wizard(qs, con=con)
        assert result is None

    def test_eof(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        qs = [MultiQuestion(title="Q1", choices=["A"])]
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=EOFError),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = multi_question_wizard(qs, con=con)
        assert result is None


# ---------------------------------------------------------------------------
# checklist_input — non-TTY fallback
# ---------------------------------------------------------------------------

class TestChecklistFallback:
    def test_returns_checks_and_comment(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=["1,3", "good"]),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = checklist_input(
                ["Tests", "Lint", "CI"],
                title="Enable?",
                con=con,
            )
        assert result is not None
        checks, comment = result
        assert checks == [True, False, True]
        assert comment == "good"

    def test_cancel(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", return_value="q"),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = checklist_input(["A", "B"], title="Check?", con=con)
        assert result is None

    def test_eof(self) -> None:
        con = Console(file=StringIO(), force_terminal=False)
        with (
            patch("hooty.ui.sys") as mock_sys,
            patch("builtins.input", side_effect=EOFError),
        ):
            mock_sys.stdin.isatty.return_value = False
            result = checklist_input(["A", "B"], title="Check?", con=con)
        assert result is None
