"""Tests for the shared shell runner."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from hooty.tools.shell_runner import (
    _kill_process,
    _read_file,
    _read_file_head,
    _win_creation_flags,
    count_lines,
    log_command,
    run_with_timeout,
)


# ---------------------------------------------------------------------------
# _run_simple (idle_timeout=0)
# ---------------------------------------------------------------------------


class TestRunSimple:
    """Tests for the simple subprocess.run path (idle_timeout=0)."""

    def test_successful_command(self, tmp_path):
        result = run_with_timeout(
            [sys.executable, "-c", "print('hello')"],
            cwd=str(tmp_path),
            max_timeout=10,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout
        assert result.timed_out is False
        assert result.idle_timed_out is False
        assert result.output_file is None

    def test_stderr(self, tmp_path):
        result = run_with_timeout(
            [sys.executable, "-c", "import sys; sys.stderr.write('err\\n')"],
            cwd=str(tmp_path),
            max_timeout=10,
        )
        assert "err" in result.stderr

    def test_exit_code(self, tmp_path):
        result = run_with_timeout(
            [sys.executable, "-c", "raise SystemExit(42)"],
            cwd=str(tmp_path),
            max_timeout=10,
        )
        assert result.returncode == 42

    def test_timeout(self, tmp_path):
        result = run_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
            max_timeout=2,
        )
        assert result.timed_out is True
        assert result.returncode == -1

    def test_shell_mode(self, tmp_path):
        result = run_with_timeout(
            "echo shelltest",
            cwd=str(tmp_path),
            max_timeout=10,
            shell=True,
        )
        assert result.returncode == 0
        assert "shelltest" in result.stdout


# ---------------------------------------------------------------------------
# _run_with_idle_watch (idle_timeout>0)
# ---------------------------------------------------------------------------


class TestRunWithIdleWatch:
    """Tests for the idle-timeout path (file redirect + size polling)."""

    def test_fast_command(self, tmp_path):
        result = run_with_timeout(
            [sys.executable, "-c", "print('fast')"],
            cwd=str(tmp_path),
            max_timeout=10,
            idle_timeout=5,
        )
        assert result.returncode == 0
        assert "fast" in result.stdout
        assert result.timed_out is False
        assert result.idle_timed_out is False

    def test_idle_triggered(self, tmp_path):
        # Process prints nothing and sleeps → idle timeout should fire
        result = run_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
            max_timeout=30,
            idle_timeout=2,
        )
        assert result.idle_timed_out is True
        assert result.timed_out is False

    def test_continuous_output(self, tmp_path):
        # Process produces output every 0.5s for 4s → should NOT idle-timeout at 2s
        script = (
            "import time, sys\n"
            "for i in range(8):\n"
            "    print(f'tick {i}', flush=True)\n"
            "    time.sleep(0.5)\n"
        )
        result = run_with_timeout(
            [sys.executable, "-c", script],
            cwd=str(tmp_path),
            max_timeout=30,
            idle_timeout=2,
        )
        assert result.returncode == 0
        assert result.idle_timed_out is False
        assert "tick 7" in result.stdout

    def test_wall_clock_wins(self, tmp_path):
        # Process prints every 0.5s but max_timeout fires first
        script = (
            "import time, sys\n"
            "while True:\n"
            "    print('.', flush=True)\n"
            "    time.sleep(0.5)\n"
        )
        result = run_with_timeout(
            [sys.executable, "-c", script],
            cwd=str(tmp_path),
            max_timeout=3,
            idle_timeout=60,
        )
        assert result.timed_out is True
        assert result.idle_timed_out is False

    def test_small_output_no_file(self, tmp_path):
        result = run_with_timeout(
            [sys.executable, "-c", "print('small')"],
            cwd=str(tmp_path),
            max_timeout=10,
            idle_timeout=5,
            tmp_dir=str(tmp_path),
        )
        assert result.output_file is None
        # Temp file should be cleaned up
        log_files = list(tmp_path.glob("run_*.log"))
        assert len(log_files) == 0

    def test_large_output_keeps_file(self, tmp_path):
        # Generate > 50KB of output
        script = (
            "for i in range(5000):\n"
            "    print('x' * 20)\n"
        )
        result = run_with_timeout(
            [sys.executable, "-c", script],
            cwd=str(tmp_path),
            max_timeout=30,
            idle_timeout=5,
            tmp_dir=str(tmp_path),
        )
        assert result.output_file is not None
        assert Path(result.output_file).exists()
        # stdout should be truncated (not all 5000 lines)
        assert len(result.stdout) <= 55_000

    def test_large_output_file_readable(self, tmp_path):
        script = (
            "for i in range(5000):\n"
            "    print(f'line {i}: ' + 'x' * 20)\n"
        )
        result = run_with_timeout(
            [sys.executable, "-c", script],
            cwd=str(tmp_path),
            max_timeout=30,
            idle_timeout=5,
            tmp_dir=str(tmp_path),
        )
        assert result.output_file is not None
        content = Path(result.output_file).read_text()
        assert "line 0:" in content
        assert "line 4999:" in content

    def test_tmp_dir_used(self, tmp_path):
        session_tmp = tmp_path / "session_tmp"
        session_tmp.mkdir()
        result = run_with_timeout(
            [sys.executable, "-c", "print('hello')"],
            cwd=str(tmp_path),
            max_timeout=10,
            idle_timeout=5,
            tmp_dir=str(session_tmp),
        )
        # The file should have been created in session_tmp (then deleted for small output)
        assert result.returncode == 0


# ---------------------------------------------------------------------------
# stdin=DEVNULL (interactive command hang prevention)
# ---------------------------------------------------------------------------


class TestStdinDevnull:
    """Verify that stdin is /dev/null so interactive commands don't hang."""

    def test_stdin_reads_empty(self, tmp_path):
        """sys.stdin.read() should return empty string (EOF from DEVNULL)."""
        script = "import sys; print(repr(sys.stdin.read()))"
        result = run_with_timeout(
            [sys.executable, "-c", script],
            cwd=str(tmp_path),
            max_timeout=10,
        )
        assert result.returncode == 0
        assert "''" in result.stdout

    def test_bare_python_exits_immediately(self, tmp_path):
        """Bare python (REPL) should exit immediately due to EOF on stdin."""
        result = run_with_timeout(
            [sys.executable],
            cwd=str(tmp_path),
            max_timeout=5,
        )
        assert result.timed_out is False
        assert result.returncode == 0

    def test_stdin_devnull_with_idle_watch(self, tmp_path):
        """stdin=DEVNULL also works in the idle_timeout path."""
        script = "import sys; print(repr(sys.stdin.read()))"
        result = run_with_timeout(
            [sys.executable, "-c", script],
            cwd=str(tmp_path),
            max_timeout=10,
            idle_timeout=5,
        )
        assert result.returncode == 0
        assert "''" in result.stdout

    def test_bare_python_exits_with_idle_watch(self, tmp_path):
        """Bare python exits immediately in the idle_timeout path too."""
        result = run_with_timeout(
            [sys.executable],
            cwd=str(tmp_path),
            max_timeout=5,
            idle_timeout=3,
        )
        assert result.timed_out is False
        assert result.idle_timed_out is False

    def test_shell_heredoc_unaffected(self, tmp_path):
        """Shell heredoc/pipe should still work (stdin=DEVNULL only affects
        commands that don't redirect stdin themselves)."""
        result = run_with_timeout(
            "echo hello | cat",
            cwd=str(tmp_path),
            max_timeout=10,
            shell=True,
        )
        assert result.returncode == 0
        assert "hello" in result.stdout


# ---------------------------------------------------------------------------
# _kill_process
# ---------------------------------------------------------------------------


class TestKillProcess:
    """Test the process termination helper."""

    def test_kills_running_process(self, tmp_path):
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
        )
        assert proc.poll() is None
        _kill_process(proc)
        assert proc.poll() is not None

    def test_no_error_on_dead_process(self, tmp_path):
        import subprocess

        proc = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            cwd=str(tmp_path),
        )
        proc.wait()
        # Should not raise
        _kill_process(proc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    """Test _read_file, _read_file_head, count_lines."""

    def test_read_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello\nworld\n")
        assert _read_file(str(f)) == "hello\nworld\n"

    def test_read_file_none(self):
        assert _read_file(None) == ""

    def test_read_file_missing(self, tmp_path):
        assert _read_file(str(tmp_path / "nonexistent")) == ""

    def test_read_file_head(self, tmp_path):
        f = tmp_path / "big.txt"
        lines = [f"line {i}\n" for i in range(100)]
        f.write_text("".join(lines))
        result = _read_file_head(str(f), max_lines=10, max_bytes=100_000)
        assert result.count("\n") == 10

    def test_read_file_head_bytes_limit(self, tmp_path):
        f = tmp_path / "big.txt"
        lines = [f"{'x' * 100}\n" for _ in range(1000)]
        f.write_text("".join(lines))
        result = _read_file_head(str(f), max_lines=10000, max_bytes=500)
        assert len(result.encode("utf-8")) <= 500

    def test_count_lines(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("a\nb\nc\n")
        assert count_lines(str(f)) == 3

    def test_count_lines_missing(self, tmp_path):
        assert count_lines(str(tmp_path / "missing")) == 0


# ---------------------------------------------------------------------------
# log_command
# ---------------------------------------------------------------------------


class TestLogCommand:
    """Test command history logging."""

    def test_log_creates_history_file(self, tmp_path):
        log_command(
            str(tmp_path),
            command="echo hello",
            returncode=0,
            duration=0.5,
        )
        history = tmp_path / "shell_history.jsonl"
        assert history.exists()
        entry = json.loads(history.read_text().strip())
        assert entry["command"] == "echo hello"
        assert entry["returncode"] == 0
        assert entry["duration_seconds"] == 0.5
        assert entry["timed_out"] is False
        assert entry["idle_timed_out"] is False
        assert "timestamp" in entry

    def test_log_appends(self, tmp_path):
        log_command(str(tmp_path), command="cmd1", returncode=0, duration=1.0)
        log_command(str(tmp_path), command="cmd2", returncode=1, duration=2.0)
        history = tmp_path / "shell_history.jsonl"
        lines = history.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0])["command"] == "cmd1"
        assert json.loads(lines[1])["command"] == "cmd2"

    def test_log_with_output_file(self, tmp_path):
        log_command(
            str(tmp_path),
            command="big cmd",
            returncode=0,
            duration=3.0,
            output_file="/tmp/run_001.log",
        )
        entry = json.loads((tmp_path / "shell_history.jsonl").read_text().strip())
        assert entry["output_file"] == "/tmp/run_001.log"

    def test_log_timeout_flags(self, tmp_path):
        log_command(
            str(tmp_path),
            command="slow",
            returncode=-1,
            duration=120.0,
            timed_out=True,
            idle_timed_out=True,
        )
        entry = json.loads((tmp_path / "shell_history.jsonl").read_text().strip())
        assert entry["timed_out"] is True
        assert entry["idle_timed_out"] is True

    def test_log_none_session_dir(self):
        # Should not raise
        log_command(None, command="test", returncode=0, duration=0.1)

    def test_log_list_command(self, tmp_path):
        log_command(
            str(tmp_path),
            command=["python", "-c", "print('hi')"],
            returncode=0,
            duration=0.2,
        )
        entry = json.loads((tmp_path / "shell_history.jsonl").read_text().strip())
        assert entry["command"] == "python -c print('hi')"


# ---------------------------------------------------------------------------
# _win_creation_flags
# ---------------------------------------------------------------------------


class TestWinCreationFlags:
    """Test the Windows process group isolation helper."""

    def test_returns_int(self):
        result = _win_creation_flags()
        assert isinstance(result, int)

    def test_win32_returns_create_new_process_group(self):
        expected = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        with patch("hooty.tools.shell_runner.sys") as mock_sys:
            mock_sys.platform = "win32"
            from hooty.tools.shell_runner import _win_creation_flags as fn
            with patch.object(sys.modules["hooty.tools.shell_runner"], "sys", mock_sys):
                assert fn() == expected

    def test_linux_returns_zero(self):
        with patch("hooty.tools.shell_runner.sys") as mock_sys:
            mock_sys.platform = "linux"
            from hooty.tools.shell_runner import _win_creation_flags as fn
            with patch.object(sys.modules["hooty.tools.shell_runner"], "sys", mock_sys):
                assert fn() == 0

    def test_darwin_returns_zero(self):
        with patch("hooty.tools.shell_runner.sys") as mock_sys:
            mock_sys.platform = "darwin"
            from hooty.tools.shell_runner import _win_creation_flags as fn
            with patch.object(sys.modules["hooty.tools.shell_runner"], "sys", mock_sys):
                assert fn() == 0


# ---------------------------------------------------------------------------
# _interrupt_event (cancellation via event)
# ---------------------------------------------------------------------------


class TestInterruptEvent:
    """Test that _interrupt_event aborts running commands."""

    def setup_method(self):
        from hooty.tools.shell_runner import _interrupt_event
        _interrupt_event.clear()

    def teardown_method(self):
        from hooty.tools.shell_runner import _interrupt_event
        _interrupt_event.clear()

    def test_interrupt_event_simple(self, tmp_path):
        """_interrupt_event set during _run_simple should return interrupted."""
        import threading
        from hooty.tools.shell_runner import _interrupt_event

        # Set the event after a short delay to interrupt the sleeping command
        def _set_event():
            import time
            time.sleep(1.5)
            _interrupt_event.set()

        t = threading.Thread(target=_set_event, daemon=True)
        t.start()

        result = run_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
            max_timeout=30,
        )
        t.join(timeout=5)
        assert result.interrupted is True
        assert result.returncode == -1

    def test_interrupt_event_idle_watch(self, tmp_path):
        """_interrupt_event set during _run_with_idle_watch should return interrupted."""
        import threading
        from hooty.tools.shell_runner import _interrupt_event

        def _set_event():
            import time
            time.sleep(1.5)
            _interrupt_event.set()

        t = threading.Thread(target=_set_event, daemon=True)
        t.start()

        result = run_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
            max_timeout=30,
            idle_timeout=60,
        )
        t.join(timeout=5)
        assert result.interrupted is True
        assert result.returncode == -1

    def test_already_set_returns_immediately(self, tmp_path):
        """If _interrupt_event is already set, run_with_timeout returns immediately."""
        import time
        from hooty.tools.shell_runner import _interrupt_event

        _interrupt_event.set()
        start = time.monotonic()
        result = run_with_timeout(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=str(tmp_path),
            max_timeout=30,
        )
        elapsed = time.monotonic() - start
        assert result.interrupted is True
        assert result.returncode == -1
        # Should return nearly instantly (no process started)
        assert elapsed < 1.0

    def test_subsequent_calls_also_interrupted(self, tmp_path):
        """After CTRL-C, subsequent run_with_timeout calls also return interrupted."""
        from hooty.tools.shell_runner import _interrupt_event

        _interrupt_event.set()
        # First call
        r1 = run_with_timeout(["echo", "a"], cwd=str(tmp_path), max_timeout=10)
        # Second call — event should still be set
        r2 = run_with_timeout(["echo", "b"], cwd=str(tmp_path), max_timeout=10)
        assert r1.interrupted is True
        assert r2.interrupted is True
