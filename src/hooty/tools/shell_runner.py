"""Shared shell execution with wall-clock and idle timeout support."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("hooty")

# Module-level interrupt event — set by the Windows console-ctrl handler
# (or other cancellation mechanisms) to signal running shell commands to
# abort without raising KeyboardInterrupt (which would corrupt the
# ProactorEventLoop on Windows).
_interrupt_event = threading.Event()


def _win_creation_flags() -> int:
    """Return subprocess creation flags to isolate child from parent console group.

    On Windows, CREATE_NEW_PROCESS_GROUP places the child process in its
    own process group, separating its console signal handling from the parent.
    """
    if sys.platform == "win32":
        return getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    return 0


# Truncation thresholds (same as agno CodingTools defaults)
_MAX_LINES = 2000
_MAX_BYTES = 50_000


@dataclass
class ShellResult:
    """Result of a shell command execution."""

    stdout: str
    stderr: str
    returncode: int
    timed_out: bool = False
    idle_timed_out: bool = False
    interrupted: bool = False
    output_file: str | None = None


def run_with_timeout(
    cmd: str | list[str],
    *,
    cwd: str,
    max_timeout: int = 120,
    idle_timeout: int = 0,
    shell: bool = False,
    tmp_dir: str | None = None,
) -> ShellResult:
    """Execute a command with wall-clock and optional idle timeout.

    When *idle_timeout* is 0, uses ``subprocess.run`` (legacy behavior).
    When *idle_timeout* > 0, redirects output to a temp file and polls
    ``os.path.getsize`` to detect idle processes.

    :param cmd: Command string or list.
    :param cwd: Working directory.
    :param max_timeout: Maximum wall-clock seconds.
    :param idle_timeout: Kill after this many seconds of no output (0 = disabled).
    :param shell: Whether to use shell mode.
    :param tmp_dir: Directory for temp files (None = system default).
    """
    # If a previous Ctrl+C already set the interrupt flag, return
    # immediately — do not start a new process after cancellation.
    # The flag is cleared at the start of each new user request
    # (_stream_response) rather than per-command, so all subsequent
    # shell calls in the same cancelled response are also skipped.
    if _interrupt_event.is_set():
        return ShellResult(stdout="", stderr="", returncode=-1, interrupted=True)
    if idle_timeout > 0:
        return _run_with_idle_watch(
            cmd,
            cwd=cwd,
            max_timeout=max_timeout,
            idle_timeout=idle_timeout,
            shell=shell,
            tmp_dir=tmp_dir,
        )
    return _run_simple(cmd, cwd=cwd, timeout=max_timeout, shell=shell)


def _run_simple(
    cmd: str | list[str],
    *,
    cwd: str,
    timeout: int,
    shell: bool,
) -> ShellResult:
    """Execute a command with periodic interrupt checks.

    Uses Popen + communicate(timeout=1s) polling so that the
    ``_interrupt_event`` (set by the Windows console-ctrl handler) can
    abort the command without relying on ``KeyboardInterrupt``.
    """
    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=shell,
            cwd=cwd,
            encoding="utf-8",
            errors="replace",
            creationflags=_win_creation_flags(),
        )
    except OSError as e:
        return ShellResult(stdout="", stderr=str(e), returncode=-1)

    start = time.monotonic()
    while True:
        try:
            stdout, stderr = proc.communicate(timeout=1.0)
            return ShellResult(
                stdout=stdout or "",
                stderr=stderr or "",
                returncode=proc.returncode,
            )
        except subprocess.TimeoutExpired:
            if _interrupt_event.is_set():
                logger.debug("[shell] _run_simple: interrupt event detected")
                _kill_process(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    stdout, stderr = "", ""
                return ShellResult(
                    stdout=stdout or "",
                    stderr=stderr or "",
                    returncode=-1,
                    interrupted=True,
                )
            if time.monotonic() - start >= timeout:
                logger.debug("[shell] _run_simple: TimeoutExpired (timeout=%ds)", timeout)
                _kill_process(proc)
                try:
                    proc.communicate(timeout=5)
                except (subprocess.TimeoutExpired, OSError):
                    pass
                return ShellResult(stdout="", stderr="", returncode=-1, timed_out=True)
        except KeyboardInterrupt:
            logger.debug("[shell] _run_simple: KeyboardInterrupt caught")
            _kill_process(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                stdout, stderr = "", ""
            return ShellResult(
                stdout=stdout or "",
                stderr=stderr or "",
                returncode=-1,
                interrupted=True,
            )


def _run_with_idle_watch(
    cmd: str | list[str],
    *,
    cwd: str,
    max_timeout: int,
    idle_timeout: int,
    shell: bool,
    tmp_dir: str | None = None,
) -> ShellResult:
    """Execute with file-redirect + size polling for idle detection."""
    proc: subprocess.Popen | None = None
    tmp_path: str | None = None
    keep_file = False

    try:
        tmp = tempfile.NamedTemporaryFile(
            mode="wb",
            delete=False,
            prefix="run_",
            suffix=".log",
            dir=tmp_dir,
        )
        tmp_path = tmp.name

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=tmp,
            stderr=subprocess.STDOUT,
            shell=shell,
            cwd=cwd,
            creationflags=_win_creation_flags(),
        )
        tmp.close()

        start = time.monotonic()
        last_size = 0
        last_activity = start
        timed_out = False
        idle_timed_out = False
        interrupted = False

        while proc.poll() is None:
            time.sleep(1.0)
            now = time.monotonic()

            if _interrupt_event.is_set():
                interrupted = True
                _kill_process(proc)
                break

            if now - start >= max_timeout:
                timed_out = True
                _kill_process(proc)
                break

            cur_size = os.path.getsize(tmp_path)
            if cur_size != last_size:
                last_size = cur_size
                last_activity = now
            elif now - last_activity >= idle_timeout:
                idle_timed_out = True
                _kill_process(proc)
                break

        returncode = -1 if interrupted else (proc.returncode if proc.returncode is not None else -1)
        file_size = os.path.getsize(tmp_path)

        if file_size > _MAX_BYTES:
            output = _read_file_head(tmp_path, _MAX_LINES, _MAX_BYTES)
            keep_file = True
            return ShellResult(
                stdout=output,
                stderr="",
                returncode=returncode,
                timed_out=timed_out,
                idle_timed_out=idle_timed_out,
                interrupted=interrupted,
                output_file=tmp_path,
            )
        else:
            output = _read_file(tmp_path)
            return ShellResult(
                stdout=output,
                stderr="",
                returncode=returncode,
                timed_out=timed_out,
                idle_timed_out=idle_timed_out,
                interrupted=interrupted,
            )

    except KeyboardInterrupt:
        if proc is not None and proc.poll() is None:
            _kill_process(proc)
        output = _read_file(tmp_path) if tmp_path else ""
        return ShellResult(
            stdout=output, stderr="", returncode=-1, interrupted=True,
        )
    finally:
        if proc is not None and proc.poll() is None:
            _kill_process(proc)
        if tmp_path and not keep_file:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except OSError:
                pass


def _kill_process(proc: subprocess.Popen) -> None:
    """Terminate → wait(5s) → kill → wait. Ensures process is reaped to prevent zombies."""
    try:
        proc.terminate()
    except OSError:
        # Process already gone
        return
    try:
        proc.wait(timeout=5)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        proc.kill()
    except OSError:
        # Process already gone
        return
    # Always reap the process — wait indefinitely rather than risk a zombie.
    # After SIGKILL, wait() should return almost immediately.
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # Extremely unlikely after SIGKILL; log but do not suppress
        logger.warning("Process %s not reaped after SIGKILL + 10s wait", proc.pid)


def _read_file(path: str | None) -> str:
    """Read entire file contents."""
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _read_file_head(path: str, max_lines: int, max_bytes: int) -> str:
    """Read only the head of a file (memory-efficient for large outputs)."""
    lines: list[str] = []
    current_bytes = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f):
                if i >= max_lines:
                    break
                line_bytes = len(line.encode("utf-8", errors="replace"))
                if current_bytes + line_bytes > max_bytes:
                    break
                lines.append(line)
                current_bytes += line_bytes
    except OSError:
        return ""
    return "".join(lines)


def count_lines(path: str) -> int:
    """Count the number of lines in a file without loading it into memory."""
    count = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for _ in f:
                count += 1
    except OSError:
        pass
    return count


def log_command(
    session_dir: str | None,
    *,
    command: str | list[str],
    returncode: int,
    duration: float,
    timed_out: bool = False,
    idle_timed_out: bool = False,
    output_file: str | None = None,
) -> None:
    """Append a command execution record to {session_dir}/shell_history.jsonl."""
    if not session_dir:
        return
    history_path = Path(session_dir) / "shell_history.jsonl"
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "command": command if isinstance(command, str) else " ".join(command),
        "returncode": returncode,
        "duration_seconds": round(duration, 2),
        "timed_out": timed_out,
        "idle_timed_out": idle_timed_out,
    }
    if output_file:
        entry["output_file"] = output_file
    try:
        with open(history_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass
