"""Tests for bang command (!command) shell escape."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

from hooty.repl import REPL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repl(tmp_path: Path) -> REPL:
    """Build a REPL with heavy parts stubbed out."""
    cfg = MagicMock()
    cfg.session_id = str(uuid.uuid4())
    cfg.config_dir = tmp_path
    cfg.session_dir = tmp_path / "sessions" / cfg.session_id
    cfg.session_tmp_dir = cfg.session_dir / "tmp"
    cfg.working_directory = str(tmp_path)

    with patch.object(REPL, "__init__", lambda self, *a, **kw: None):
        repl = REPL.__new__(REPL)

    repl.config = cfg
    repl.console = MagicMock()
    return repl


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBangCommand:
    """Tests for _handle_bang_command()."""

    def test_empty_bang_shows_usage(self, tmp_path: Path) -> None:
        """'!' with no command shows usage hint."""
        repl = _make_repl(tmp_path)
        repl._handle_bang_command("!")
        repl.console.print.assert_called_once()
        msg = repl.console.print.call_args[0][0]
        assert "Usage" in msg

    def test_whitespace_only_shows_usage(self, tmp_path: Path) -> None:
        """'!   ' (whitespace only) shows usage hint."""
        repl = _make_repl(tmp_path)
        repl._handle_bang_command("!   ")
        msg = repl.console.print.call_args[0][0]
        assert "Usage" in msg

    def test_runs_command_successfully(self, tmp_path: Path) -> None:
        """'!echo hello' runs without error."""
        repl = _make_repl(tmp_path)
        repl._handle_bang_command("!echo hello")
        # No exit code message for successful command
        repl.console.print.assert_not_called()

    def test_subprocess_run_called_with_correct_args(self, tmp_path: Path) -> None:
        """Verify subprocess.run is called with expected parameters."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            repl._handle_bang_command("!git status")
            mock_run.assert_called_once_with(
                "git status",
                shell=True,
                cwd=str(tmp_path),
                stdin=subprocess.DEVNULL,
            )

    def test_cwd_is_working_directory(self, tmp_path: Path) -> None:
        """Command runs in config.working_directory."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", wraps=subprocess.run) as mock_run:
            repl._handle_bang_command("!pwd")
            _, kwargs = mock_run.call_args
            assert kwargs["cwd"] == str(tmp_path)

    def test_nonzero_exit_code_displayed(self, tmp_path: Path) -> None:
        """Non-zero exit code is shown to the user."""
        repl = _make_repl(tmp_path)
        repl._handle_bang_command("!false")
        calls = [str(c) for c in repl.console.print.call_args_list]
        assert any("exit code" in c for c in calls)

    def test_zero_exit_code_not_displayed(self, tmp_path: Path) -> None:
        """Zero exit code is not shown."""
        repl = _make_repl(tmp_path)
        repl._handle_bang_command("!true")
        repl.console.print.assert_not_called()

    def test_stdin_is_devnull(self, tmp_path: Path) -> None:
        """stdin is /dev/null — interactive commands get immediate EOF."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", wraps=subprocess.run) as mock_run:
            repl._handle_bang_command("!echo test")
            _, kwargs = mock_run.call_args
            assert kwargs["stdin"] == subprocess.DEVNULL

    def test_stdout_inherits_terminal(self, tmp_path: Path) -> None:
        """stdout/stderr are not piped — they inherit the terminal directly."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            repl._handle_bang_command("!echo test")
            _, kwargs = mock_run.call_args
            assert "stdout" not in kwargs
            assert "stderr" not in kwargs

    def test_double_bang_passes_bang_to_shell(self, tmp_path: Path) -> None:
        """'!!' passes '!' to the shell."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            repl._handle_bang_command("!!")
            args, _ = mock_run.call_args
            assert args[0] == "!"

    def test_keyboard_interrupt_caught(self, tmp_path: Path) -> None:
        """Ctrl+C during subprocess is caught gracefully."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", side_effect=KeyboardInterrupt):
            # Should not raise
            repl._handle_bang_command("!sleep 100")
        repl.console.print.assert_called()

    def test_general_exception_caught(self, tmp_path: Path) -> None:
        """Unexpected exceptions are caught and shown as error."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", side_effect=OSError("fail")):
            repl._handle_bang_command("!bogus")
        calls = [str(c) for c in repl.console.print.call_args_list]
        assert any("Shell error" in c for c in calls)

    def test_strips_leading_bang(self, tmp_path: Path) -> None:
        """Leading '!' is stripped before passing to shell."""
        repl = _make_repl(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0)) as mock_run:
            repl._handle_bang_command("!ls -la")
            args, _ = mock_run.call_args
            assert args[0] == "ls -la"


class TestBangCommandHelp:
    """Verify /help includes bang command documentation."""

    def test_help_mentions_bang(self, tmp_path: Path) -> None:
        repl = _make_repl(tmp_path)
        repl.plan_mode = False
        repl._agent_plan_mode = False
        repl._session_dir_created = False
        repl.running = True
        repl.confirm_ref = [True]
        repl.auto_ref = [False]
        repl.auto_execute_ref = [False]
        repl.pending_plan_ref = [None]
        repl.enter_plan_ref = [False]
        repl.pending_reason_ref = [None]
        repl.pending_revise_ref = [False]
        repl._last_plan_file = None
        repl._last_response_text = ""
        repl._last_final_text = ""
        repl._pending_skill_message = None
        repl.agent = MagicMock()
        repl.session_id = "test"
        repl.session_stats = MagicMock()
        repl._hooks_config = {}
        repl._loop = None

        repl._cmd_ctx = repl._build_command_context()

        from hooty.commands.misc import cmd_help
        cmd_help(repl._cmd_ctx)

        printed = " ".join(str(c) for c in repl.console.print.call_args_list)
        assert "!<command>" in printed or "!command" in printed.lower()
