"""Tests for session picker module."""

from unittest.mock import patch

from rich.console import Console

from hooty.config import AppConfig
from rich.panel import Panel

from hooty.session_picker import (
    _build_panel,
    _format_row,
    _pick_fallback,
    pick_session,
)
from hooty.session_store import format_session_for_display


def _make_console() -> Console:
    """Create a non-interactive console for testing."""
    return Console(force_terminal=False, no_color=True)


def _make_sessions(count: int) -> list[dict]:
    """Create dummy session dicts."""
    return [
        {
            "session_id": f"sess-{i:04d}-0000-0000-000000000000",
            "updated_at": 1740000000 + i,
            "runs": [{"input": {"input_content": f"message {i}"}}],
        }
        for i in range(count)
    ]


# -- Formatting helpers --


class TestFormatRow:
    """Test row formatting."""

    def test_selected_row_has_marker(self):
        info = format_session_for_display(_make_sessions(1)[0])
        row = _format_row(1, info, selected=True)
        assert "▸" in row

    def test_unselected_row_no_marker(self):
        info = format_session_for_display(_make_sessions(1)[0])
        row = _format_row(1, info, selected=False)
        assert "▸" not in row


def _render_panel(panel: Panel, width: int = 120) -> str:
    """Render a Panel to plain text for assertion."""
    console = Console(force_terminal=True, width=width, no_color=True)
    with console.capture() as capture:
        console.print(panel)
    return capture.get()


class TestBuildPanel:
    """Test Panel-based dialog building."""

    def test_panel_has_border(self):
        infos = [format_session_for_display(s) for s in _make_sessions(3)]
        panel = _build_panel(infos, selected=0, viewport_height=3, scroll_offset=0)
        assert isinstance(panel, Panel)
        text = _render_panel(panel)
        # Panel borders use box-drawing characters
        assert "─" in text or "┌" in text

    def test_title_contains_count(self):
        infos = [format_session_for_display(s) for s in _make_sessions(5)]
        panel = _build_panel(infos, selected=0, viewport_height=3, scroll_offset=0)
        text = _render_panel(panel)
        assert "Saved sessions (5)" in text

    def test_no_scroll_indicators_when_all_visible(self):
        infos = [format_session_for_display(s) for s in _make_sessions(3)]
        panel = _build_panel(infos, selected=0, viewport_height=3, scroll_offset=0)
        text = _render_panel(panel)
        assert "▲" not in text
        assert "▼" not in text

    def test_scroll_down_indicator_when_more_below(self):
        infos = [format_session_for_display(s) for s in _make_sessions(5)]
        panel = _build_panel(infos, selected=0, viewport_height=3, scroll_offset=0)
        text = _render_panel(panel)
        assert "▼" in text
        assert "▲" not in text

    def test_scroll_up_indicator_when_more_above(self):
        infos = [format_session_for_display(s) for s in _make_sessions(5)]
        panel = _build_panel(infos, selected=4, viewport_height=3, scroll_offset=2)
        text = _render_panel(panel)
        assert "▲" in text
        assert "▼" not in text

    def test_both_scroll_indicators(self):
        infos = [format_session_for_display(s) for s in _make_sessions(10)]
        panel = _build_panel(infos, selected=3, viewport_height=3, scroll_offset=2)
        text = _render_panel(panel)
        assert "▲" in text
        assert "▼" in text

    def test_viewport_shows_only_visible_rows(self):
        infos = [format_session_for_display(s) for s in _make_sessions(5)]
        panel = _build_panel(infos, selected=0, viewport_height=2, scroll_offset=0, width=120)
        text = _render_panel(panel)
        # Rows 1 and 2 should be visible (1-indexed display numbers)
        assert "message 0" in text
        assert "message 1" in text
        # Rows 3-5 should not be visible
        assert "message 2" not in text
        assert "message 3" not in text
        assert "message 4" not in text

    def test_viewport_offset_shows_correct_rows(self):
        infos = [format_session_for_display(s) for s in _make_sessions(5)]
        panel = _build_panel(infos, selected=3, viewport_height=2, scroll_offset=2, width=120)
        text = _render_panel(panel)
        # Rows 3 and 4 should be visible (0-indexed: 2, 3)
        assert "message 2" in text
        assert "message 3" in text
        # Others should not
        assert "message 0" not in text
        assert "message 1" not in text
        assert "message 4" not in text

    def test_footer_present(self):
        infos = [format_session_for_display(s) for s in _make_sessions(1)]
        panel = _build_panel(infos, selected=0, viewport_height=1, scroll_offset=0)
        text = _render_panel(panel)
        assert "navigate" in text
        assert "Enter" in text
        assert "Esc" in text

    def test_selected_row_has_marker(self):
        infos = [format_session_for_display(s) for s in _make_sessions(3)]
        panel = _build_panel(infos, selected=1, viewport_height=3, scroll_offset=0)
        text = _render_panel(panel)
        assert "▸" in text


# -- Interactive mode (mock _read_key) --


class TestPickInteractive:
    """Test interactive picker with mocked key input."""

    @patch("hooty.session_picker._read_key", side_effect=["enter"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_enter_selects_first(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        sessions = _make_sessions(3)
        mock_list.return_value = (sessions, 3)

        result = pick_session(AppConfig(), _make_console())
        assert result == "sess-0000-0000-0000-000000000000"

    @patch("hooty.session_picker._read_key", side_effect=["down", "down", "enter"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_down_then_enter(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        sessions = _make_sessions(3)
        mock_list.return_value = (sessions, 3)

        result = pick_session(AppConfig(), _make_console())
        assert result == "sess-0002-0000-0000-000000000000"

    @patch("hooty.session_picker._read_key", side_effect=["down", "up", "enter"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_down_up_enter(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        sessions = _make_sessions(3)
        mock_list.return_value = (sessions, 3)

        result = pick_session(AppConfig(), _make_console())
        assert result == "sess-0000-0000-0000-000000000000"

    @patch("hooty.session_picker._read_key", side_effect=["up", "enter"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_up_at_top_stays(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        sessions = _make_sessions(3)
        mock_list.return_value = (sessions, 3)

        result = pick_session(AppConfig(), _make_console())
        assert result == "sess-0000-0000-0000-000000000000"

    @patch("hooty.session_picker._read_key", side_effect=["down", "down", "down", "enter"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_down_at_bottom_stays(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        sessions = _make_sessions(2)
        mock_list.return_value = (sessions, 2)

        # 3 downs on 2 items → clamped to index 1
        result = pick_session(AppConfig(), _make_console())
        assert result == "sess-0001-0000-0000-000000000000"

    @patch("hooty.session_picker._read_key", side_effect=["q"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_q_cancels(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        mock_list.return_value = (_make_sessions(2), 2)

        result = pick_session(AppConfig(), _make_console())
        assert result is None

    @patch("hooty.session_picker._read_key", side_effect=["escape"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_escape_cancels(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        mock_list.return_value = (_make_sessions(2), 2)

        result = pick_session(AppConfig(), _make_console())
        assert result is None

    @patch("hooty.session_picker._read_key", side_effect=["ctrl-c"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_ctrl_c_cancels(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        mock_list.return_value = (_make_sessions(2), 2)

        result = pick_session(AppConfig(), _make_console())
        assert result is None

    @patch("hooty.session_picker._read_key", side_effect=["n"])
    @patch("hooty.session_picker.list_sessions")
    @patch("sys.stdin")
    def test_n_starts_new_session(self, mock_stdin, mock_list, _mock_key):
        mock_stdin.isatty.return_value = True
        mock_list.return_value = (_make_sessions(2), 2)

        result = pick_session(AppConfig(), _make_console())
        assert result == ""


# -- Fallback mode (number input) --


class TestPickFallback:
    """Test fallback number-input picker for non-TTY environments."""

    @patch("builtins.input", return_value="1")
    def test_select_first(self, _mock_input):
        sessions = _make_sessions(3)
        result = _pick_fallback(sessions, 3, _make_console())
        assert result == "sess-0000-0000-0000-000000000000"

    @patch("builtins.input", return_value="3")
    def test_select_last(self, _mock_input):
        sessions = _make_sessions(3)
        result = _pick_fallback(sessions, 3, _make_console())
        assert result == "sess-0002-0000-0000-000000000000"

    @patch("builtins.input", return_value="q")
    def test_q_returns_none(self, _mock_input):
        result = _pick_fallback(_make_sessions(2), 2, _make_console())
        assert result is None

    @patch("builtins.input", return_value="")
    def test_empty_returns_none(self, _mock_input):
        result = _pick_fallback(_make_sessions(2), 2, _make_console())
        assert result is None

    @patch("builtins.input", side_effect=KeyboardInterrupt)
    def test_ctrl_c_returns_none(self, _mock_input):
        result = _pick_fallback(_make_sessions(2), 2, _make_console())
        assert result is None

    @patch("builtins.input", side_effect=["0", "4", "2"])
    def test_out_of_range_reprompts(self, _mock_input):
        sessions = _make_sessions(3)
        result = _pick_fallback(sessions, 3, _make_console())
        assert result == "sess-0001-0000-0000-000000000000"

    @patch("builtins.input", side_effect=["abc", "1"])
    def test_non_numeric_reprompts(self, _mock_input):
        sessions = _make_sessions(2)
        result = _pick_fallback(sessions, 2, _make_console())
        assert result == "sess-0000-0000-0000-000000000000"

    @patch("builtins.input", return_value="n")
    def test_n_starts_new_session(self, _mock_input):
        result = _pick_fallback(_make_sessions(2), 2, _make_console())
        assert result == ""


# -- Edge cases --


class TestPickSessionNoSessions:
    """Test picker when no sessions exist."""

    @patch("hooty.session_picker.list_sessions")
    def test_returns_none_when_empty(self, mock_list):
        mock_list.return_value = ([], 0)
        result = pick_session(AppConfig(), _make_console())
        assert result is None


class TestPickSessionDbError:
    """Test DB error handling."""

    @patch("hooty.session_picker.list_sessions", side_effect=Exception("db error"))
    def test_db_error_returns_none(self, _mock_list):
        result = pick_session(AppConfig(), _make_console())
        assert result is None
