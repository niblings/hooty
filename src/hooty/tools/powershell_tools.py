"""PowerShell tools for Hooty — Windows-native cmdlet execution."""

from __future__ import annotations

import atexit
import functools
import re
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

from agno.tools import Toolkit

from hooty.tools.coding_tools import _filter_available_commands
from hooty.tools.confirm import _confirm_action
from hooty.tools.dev_commands import DEV_TOOL_COMMANDS
from hooty.tools.shell_runner import count_lines, log_command, run_with_timeout

# Maximum output limits (same as CodingTools)
MAX_LINES = 2000
MAX_BYTES = 50_000

# Default shell timeout in seconds
DEFAULT_TIMEOUT = 120

# Dangerous patterns blocked unconditionally (case-insensitive substring match)
BLOCKED_PATTERNS: list[str] = [
    "invoke-expression",
    "iex ",
    "iex(",
    "start-process",
    "invoke-webrequest",
    "invoke-restmethod",
    "set-executionpolicy",
    "add-type",
    "[system.reflection.assembly]",
    "downloadstring",
    "downloadfile",
]

# PowerShell cmdlets (fixed, always allowed)
_PS_CMDLETS: set[str] = {
    # File operations
    "get-childitem",
    "get-content",
    "set-content",
    "new-item",
    "copy-item",
    "move-item",
    "remove-item",
    "rename-item",
    # Exploration
    "select-string",
    "test-path",
    "resolve-path",
    "get-location",
    # Formatting / filtering
    "format-table",
    "format-list",
    "sort-object",
    "where-object",
    "select-object",
    "foreach-object",
    # String / utility
    "out-string",
    "join-path",
    "split-path",
    "get-unique",
    "measure-object",
    "group-object",
    "compare-object",
    # Conversion
    "convertto-json",
    "convertfrom-json",
    "convertto-csv",
    "convertfrom-csv",
}

INSTRUCTIONS = """\
You have access to `run_powershell` for executing PowerShell commands on Windows.
Use PowerShell cmdlets like `Get-ChildItem`, `Select-String`, `Get-Content`, etc.
Pipe operators (`|`) are supported. Example:
  Get-ChildItem -Recurse -Filter *.py | Select-String "TODO"
Note: Only whitelisted cmdlets are allowed. Dangerous operations are blocked."""


@functools.lru_cache(maxsize=1)
def _detect_powershell() -> str | None:
    """Detect available PowerShell executable.

    Prefers ``pwsh`` (PowerShell Core 7+) over ``powershell.exe``.
    Returns the full path or ``None`` if not found.
    Result is cached; call ``_detect_powershell.cache_clear()`` to reset.
    """
    for candidate in ("pwsh", "powershell"):
        path = shutil.which(candidate)
        if path:
            return path
    return None


def _check_blocked(command: str) -> str | None:
    """Return an error message if *command* contains a blocked pattern."""
    lower = command.lower()
    for pattern in BLOCKED_PATTERNS:
        if pattern in lower:
            return f"Error: Command blocked — '{pattern}' is not allowed for security reasons."
    return None


def _check_allowed(command: str, allowed: set[str] | None = None) -> str | None:
    """Validate that every pipeline segment starts with an allowed command.

    Returns an error message if any segment is disallowed, otherwise ``None``.
    """
    allowed_set = allowed if allowed is not None else _PS_CMDLETS
    # Split on pipes (not inside quotes — simple heuristic)
    segments = re.split(r"\|", command)
    for segment in segments:
        token = segment.strip().split()[0] if segment.strip() else ""
        if not token:
            continue
        if token.lower() not in allowed_set:
            return (
                f"Error: Command '{token}' is not in the allowed list. "
                f"Allowed commands: {', '.join(sorted(allowed_set))}"
            )
    return None


def _truncate_output(text: str) -> tuple[str, bool, int]:
    """Truncate text to MAX_LINES / MAX_BYTES limits.

    Returns (possibly_truncated_text, was_truncated, total_line_count).
    """
    lines = text.split("\n")
    total_lines = len(lines)
    was_truncated = False

    if total_lines > MAX_LINES:
        lines = lines[:MAX_LINES]
        was_truncated = True

    result = "\n".join(lines)

    if len(result.encode("utf-8", errors="replace")) > MAX_BYTES:
        truncated_lines: list[str] = []
        current_bytes = 0
        for line in lines:
            line_bytes = len((line + "\n").encode("utf-8", errors="replace"))
            if current_bytes + line_bytes > MAX_BYTES:
                break
            truncated_lines.append(line)
            current_bytes += line_bytes
        result = "\n".join(truncated_lines)
        was_truncated = True

    return result, was_truncated, total_lines


class PowerShellTools(Toolkit):
    """Toolkit for executing PowerShell commands."""

    def __init__(
        self,
        powershell_path: str,
        base_dir: Path,
        shell_timeout: int = DEFAULT_TIMEOUT,
        idle_timeout: int = 0,
        extra_commands: list[str] | None = None,
        tmp_dir: str | None = None,
        session_dir: str | None = None,
    ) -> None:
        super().__init__(
            name="powershell_tools",
            instructions=INSTRUCTIONS,
            add_instructions=True,
        )
        self._powershell_path = powershell_path
        self.base_dir = base_dir
        self.shell_timeout = shell_timeout
        self.idle_timeout = idle_timeout
        self.tmp_dir = tmp_dir
        self.session_dir = session_dir
        self._temp_files: list[str] = []
        self._allowed: set[str] = {
            *_PS_CMDLETS,
            *(cmd.lower() for cmd in _filter_available_commands(DEV_TOOL_COMMANDS, base_dir=base_dir)),
            *(cmd.lower() for cmd in _filter_available_commands(extra_commands or [], base_dir=base_dir)),
        }
        self.register(self.run_powershell)
        atexit.register(self._cleanup_temp_files)

    def _cleanup_temp_files(self) -> None:
        """Remove temporary files created during output truncation."""
        for path in self._temp_files:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                pass
        self._temp_files.clear()

    def run_powershell(self, command: str, timeout: Optional[int] = None) -> str:
        """Execute a PowerShell command and return its output.

        Runs the command via PowerShell with ``-NoProfile -NonInteractive``.
        Output is truncated if it exceeds 2000 lines or 50 KB.

        :param command: The PowerShell command to execute.
        :param timeout: Timeout in seconds. Defaults to 120.
        :return: Command output (stdout + stderr combined), or an error message.
        """
        # Security checks
        blocked = _check_blocked(command)
        if blocked:
            return blocked

        allowed = _check_allowed(command, self._allowed)
        if allowed:
            return allowed

        effective_timeout = timeout if timeout is not None else self.shell_timeout
        cmd = [
            self._powershell_path,
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            command,
        ]

        start = time.monotonic()
        try:
            result = run_with_timeout(
                cmd,
                cwd=str(self.base_dir),
                max_timeout=effective_timeout,
                idle_timeout=self.idle_timeout,
                shell=False,
                tmp_dir=self.tmp_dir,
            )
        except Exception as e:
            return f"Error running PowerShell command: {e}"

        duration = time.monotonic() - start
        log_command(
            self.session_dir,
            command=command,
            returncode=result.returncode,
            duration=duration,
            timed_out=result.timed_out,
            idle_timed_out=result.idle_timed_out,
            output_file=result.output_file,
        )

        if result.interrupted:
            return f"Command interrupted by user. Partial output:\n{result.stdout}"
        if result.timed_out and not result.idle_timed_out:
            return f"Error: Command timed out after {effective_timeout} seconds"
        if result.idle_timed_out:
            return (
                f"Error: Command killed — no output for {self.idle_timeout} seconds "
                f"(idle timeout). Partial output:\n{result.stdout}"
            )

        output = result.stdout
        if result.stderr:
            output += result.stderr

        header = f"Exit code: {result.returncode}\n"

        if result.output_file:
            self._temp_files.append(result.output_file)
            total = count_lines(result.output_file)
            truncated_output = output + (
                f"\n[Output truncated: {total} lines total. "
                f"Full output saved to: {result.output_file}]"
            )
            return header + truncated_output

        truncated_output, was_truncated, total_lines = _truncate_output(output)

        if was_truncated:
            tmp = tempfile.NamedTemporaryFile(
                mode="w",
                delete=False,
                suffix=".txt",
                prefix="powershell_tools_",
                dir=self.tmp_dir,
            )
            tmp.write(output)
            tmp.close()
            self._temp_files.append(tmp.name)
            truncated_output += (
                f"\n[Output truncated: {total_lines} lines total. "
                f"Full output saved to: {tmp.name}]"
            )

        return header + truncated_output


class ConfirmablePowerShellTools(PowerShellTools):
    """PowerShellTools with user confirmation before execution (Safe mode)."""

    def __init__(self, confirm_ref: list[bool], **kwargs: Any) -> None:
        self._confirm_ref = confirm_ref
        super().__init__(**kwargs)

    def run_powershell(self, command: str, timeout: Optional[int] = None) -> str:
        if self._confirm_ref[0]:
            if not _confirm_action(command, title="\u26a0  PowerShell", tool_name="run_powershell"):
                return "User cancelled the operation."
        return super().run_powershell(command, timeout)


class PlanModePowerShellTools(PowerShellTools):
    """Plan mode: PowerShell always requires user confirmation.

    When *auto_execute_ref* is set and ``True``, the transition to coding
    mode is pending — all run_powershell calls are blocked.
    """

    _TRANSITION_MSG = (
        "Transition to coding mode is pending. "
        "Do not execute further actions in planning mode."
    )

    def __init__(
        self, auto_execute_ref: list[bool] | None = None, **kwargs: Any
    ) -> None:
        self._auto_execute_ref = auto_execute_ref
        super().__init__(**kwargs)

    def run_powershell(self, command: str, timeout: Optional[int] = None) -> str:
        if self._auto_execute_ref and self._auto_execute_ref[0]:
            return self._TRANSITION_MSG
        if not _confirm_action(command, title="\u26a0  PowerShell (Plan)", tool_name="run_powershell"):
            return "User cancelled the operation."
        return super().run_powershell(command, timeout)


def create_powershell_tools(
    working_directory: str,
    confirm_ref: list[bool] | None = None,
    plan_mode: bool = False,
    auto_execute_ref: list[bool] | None = None,
    extra_commands: list[str] | None = None,
    shell_timeout: int = DEFAULT_TIMEOUT,
    idle_timeout: int = 0,
    tmp_dir: str | None = None,
    session_dir: str | None = None,
) -> PowerShellTools | None:
    """Create PowerShell tools if PowerShell is available.

    Returns ``None`` when no PowerShell executable is found.
    """
    ps_path = _detect_powershell()
    if ps_path is None:
        return None

    base_dir = Path(working_directory).resolve()
    kwargs: dict[str, Any] = dict(
        powershell_path=ps_path,
        base_dir=base_dir,
        shell_timeout=shell_timeout,
        idle_timeout=idle_timeout,
        extra_commands=extra_commands,
        tmp_dir=tmp_dir,
        session_dir=session_dir,
    )

    if plan_mode:
        return PlanModePowerShellTools(auto_execute_ref=auto_execute_ref, **kwargs)
    if confirm_ref is not None:
        return ConfirmablePowerShellTools(confirm_ref=confirm_ref, **kwargs)
    return PowerShellTools(**kwargs)
