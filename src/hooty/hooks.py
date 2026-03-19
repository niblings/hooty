"""Hooks — lifecycle event system for Hooty.

Fires shell commands at session/message/tool lifecycle points.
Commands receive event data via stdin (JSON) and communicate back
via exit code + stdout.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("hooty")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


class HookEvent(str, Enum):
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    RESPONSE_ERROR = "ResponseError"
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    POST_TOOL_USE_FAILURE = "PostToolUseFailure"
    PERMISSION_REQUEST = "PermissionRequest"
    MODE_SWITCH = "ModeSwitch"
    SUBAGENT_START = "SubagentStart"
    SUBAGENT_END = "SubagentEnd"
    NOTIFICATION = "Notification"


# Events where ``matcher`` filters on a specific field
_MATCHER_FIELD: dict[str, str] = {
    HookEvent.PRE_TOOL_USE.value: "tool_name",
    HookEvent.POST_TOOL_USE.value: "tool_name",
    HookEvent.POST_TOOL_USE_FAILURE.value: "tool_name",
    HookEvent.PERMISSION_REQUEST.value: "tool_name",
    HookEvent.USER_PROMPT_SUBMIT.value: "message",
    HookEvent.SUBAGENT_START.value: "agent_name",
    HookEvent.SUBAGENT_END.value: "agent_name",
}


@dataclass
class HookEntry:
    """A single hook definition from hooks.yaml."""

    command: str
    matcher: str = ""
    blocking: bool = False
    async_exec: bool = False  # YAML key: "async"
    timeout: int = 5
    enabled: bool = True
    source: str = ""  # "global" or "project"

    @property
    def key(self) -> str:
        """Unique identifier for per-project ON/OFF toggling."""
        return self.command


@dataclass
class HookResult:
    """Result of executing a single hook command."""

    success: bool
    exit_code: int = 0
    decision: str = ""          # "allow" | "block" | ""
    reason: str = ""
    additional_context: str = ""
    error: str = ""


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


def _parse_entry(raw: dict[str, Any]) -> HookEntry | None:
    """Parse a single hook entry dict into a HookEntry."""
    command = raw.get("command")
    if not command or not isinstance(command, str):
        return None
    return HookEntry(
        command=command,
        matcher=str(raw.get("matcher", "")),
        blocking=bool(raw.get("blocking", False)),
        async_exec=bool(raw.get("async", False)),
        timeout=int(raw.get("timeout", 5)),
    )


def load_hooks_config(
    config: Any,
) -> dict[str, list[HookEntry]]:
    """Load and merge hooks from global + project YAML files.

    Returns ``{event_name: [HookEntry, ...]}`` with global entries first.
    """
    from hooty.config import AppConfig

    if not isinstance(config, AppConfig):
        return {}

    sources: list[tuple[Path, str]] = []

    # Global hooks
    global_path = config.config_dir / "hooks.yaml"
    if global_path.exists():
        sources.append((global_path, "global"))

    # Project hooks
    project_path = Path(config.working_directory) / ".hooty" / "hooks.yaml"
    if project_path.exists():
        sources.append((project_path, "project"))

    result: dict[str, list[HookEntry]] = {}
    for p, source_label in sources:
        try:
            with open(p, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except Exception:
            logger.warning("Failed to load hooks from %s", p)
            continue

        if not isinstance(data, dict):
            continue
        hooks_section = data.get("hooks")
        if not isinstance(hooks_section, dict):
            continue

        for event_name, entries in hooks_section.items():
            # Validate event name
            try:
                HookEvent(event_name)
            except ValueError:
                logger.warning("Unknown hook event: %s in %s", event_name, p)
                continue
            if not isinstance(entries, list):
                continue
            for raw in entries:
                if not isinstance(raw, dict):
                    continue
                entry = _parse_entry(raw)
                if entry is not None:
                    entry.source = source_label
                    result.setdefault(event_name, []).append(entry)

    return result


# ---------------------------------------------------------------------------
# State management (per-project ON/OFF for individual hooks)
# ---------------------------------------------------------------------------


def _hooks_state_path(config: Any) -> Path:
    """Return path to ``.hooks.json`` in the project directory."""
    return config.project_dir / ".hooks.json"


def load_disabled_hooks(config: Any) -> set[str]:
    """Load disabled hook keys from project .hooks.json."""
    path = _hooks_state_path(config)
    if not path.exists():
        return set()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return set(data.get("disabled_hooks", []))
    except (json.JSONDecodeError, OSError):
        return set()


def save_disabled_hooks(config: Any, disabled: set[str]) -> None:
    """Save disabled hook keys to project .hooks.json."""
    path = _hooks_state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, Any] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                data = {}
        except (json.JSONDecodeError, OSError):
            data = {}
    from hooty.concurrency import atomic_write_text

    data["disabled_hooks"] = sorted(disabled)
    atomic_write_text(path, json.dumps(data, indent=2) + "\n")


def apply_disabled_state(
    hooks_config: dict[str, list[HookEntry]], config: Any,
) -> None:
    """Apply per-project ON/OFF state to hook entries in-place."""
    disabled = load_disabled_hooks(config)
    for entries in hooks_config.values():
        for entry in entries:
            key = f"{_event_for_entry(hooks_config, entry)}:{entry.key}"
            entry.enabled = key not in disabled


def _event_for_entry(
    hooks_config: dict[str, list[HookEntry]], entry: HookEntry,
) -> str:
    """Find the event name for a given entry."""
    for event_name, entries in hooks_config.items():
        if entry in entries:
            return event_name
    return ""


# ---------------------------------------------------------------------------
# Execution engine
# ---------------------------------------------------------------------------


async def _execute_command_hook(
    entry: HookEntry,
    event_data: dict[str, Any],
) -> HookResult:
    """Execute a single command hook and return the result."""
    stdin_data = json.dumps(event_data, ensure_ascii=False, default=str)

    try:
        proc = await asyncio.create_subprocess_shell(
            entry.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(stdin_data.encode()),
            timeout=entry.timeout,
        )
    except asyncio.TimeoutError:
        # Kill the subprocess so it doesn't leak
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        await proc.wait()
        return HookResult(
            success=False,
            exit_code=-1,
            error=f"Hook timed out after {entry.timeout}s: {entry.command}",
        )
    except Exception as exc:
        return HookResult(
            success=False,
            exit_code=-1,
            error=f"Hook execution failed: {exc}",
        )

    exit_code = proc.returncode or 0
    stdout_text = stdout.decode(errors="replace").strip() if stdout else ""
    stderr_text = stderr.decode(errors="replace").strip() if stderr else ""

    # Exit code 2 = block (only meaningful for blocking hooks)
    if exit_code == 2:
        return HookResult(
            success=True,
            exit_code=2,
            decision="block",
            reason=stderr_text or "Blocked by hook",
        )

    # Non-zero exit (other than 2) = non-blocking error
    if exit_code != 0:
        return HookResult(
            success=False,
            exit_code=exit_code,
            error=stderr_text or f"Hook exited with code {exit_code}",
        )

    # Log stderr from successful hooks for debugging
    if stderr_text:
        logger.debug("Hook stderr [%s]: %s", entry.command, stderr_text)

    # Exit 0 — parse stdout as JSON or plain text
    decision = ""
    reason = ""
    additional_context = ""

    if stdout_text:
        try:
            parsed = json.loads(stdout_text)
            if isinstance(parsed, dict):
                decision = str(parsed.get("decision", ""))
                reason = str(parsed.get("reason", ""))
                additional_context = str(parsed.get("additionalContext", ""))
            else:
                additional_context = stdout_text
        except json.JSONDecodeError:
            additional_context = stdout_text

    return HookResult(
        success=True,
        exit_code=0,
        decision=decision,
        reason=reason,
        additional_context=additional_context,
    )


def _matches(entry: HookEntry, event_name: str, data: dict[str, Any]) -> bool:
    """Check if an entry's matcher matches the event data."""
    if not entry.matcher:
        return True
    field_name = _MATCHER_FIELD.get(event_name)
    if field_name is None:
        return True  # No matcher support for this event
    value = str(data.get(field_name, ""))
    try:
        return bool(re.search(entry.matcher, value))
    except re.error:
        logger.warning("Invalid matcher regex: %s", entry.matcher)
        return False


async def emit_hook(
    event: HookEvent,
    hooks_config: dict[str, list[HookEntry]],
    session_id: str,
    cwd: str,
    **data: Any,
) -> list[HookResult]:
    """Fire all hooks registered for an event.

    Returns a list of HookResult objects (one per matching hook).
    """
    from datetime import datetime, timezone

    entries = hooks_config.get(event.value, [])
    if not entries:
        return []

    event_data: dict[str, Any] = {
        "hook_event": event.value,
        "session_id": session_id,
        "cwd": cwd,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    event_data.update(data)

    results: list[HookResult] = []
    fire_and_forget: list[asyncio.Task[HookResult]] = []

    for entry in entries:
        if not entry.enabled:
            continue
        if not _matches(entry, event.value, event_data):
            continue

        if entry.async_exec:
            task = asyncio.create_task(_execute_command_hook(entry, event_data))
            fire_and_forget.append(task)
            continue

        result = await _execute_command_hook(entry, event_data)

        if not result.success and result.exit_code != 2:
            logger.warning(
                "Hook error [%s] %s: %s",
                event.value, entry.command, result.error,
            )

        results.append(result)

    # Log fire-and-forget task errors (but don't block)
    for task in fire_and_forget:
        task.add_done_callback(_log_task_error)

    return results


def _log_task_error(task: asyncio.Task[HookResult]) -> None:
    """Log errors from fire-and-forget hook tasks."""
    try:
        result = task.result()
        if not result.success:
            logger.warning("Async hook error: %s", result.error)
    except Exception as exc:
        logger.warning("Async hook exception: %s", exc)


def emit_hook_sync(
    event: HookEvent,
    hooks_config: dict[str, list[HookEntry]],
    session_id: str,
    cwd: str,
    *,
    loop: asyncio.AbstractEventLoop | None = None,
    **data: Any,
) -> list[HookResult]:
    """Synchronous wrapper for emit_hook().

    Uses the provided event loop if available, otherwise creates a temporary one.
    """
    entries = hooks_config.get(event.value, [])
    if not entries:
        return []

    coro = emit_hook(event, hooks_config, session_id, cwd, **data)

    if loop is not None and loop.is_running():
        # We're inside an event loop — run synchronously via a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            return future.result(timeout=30)

    if loop is not None and not loop.is_closed():
        return loop.run_until_complete(coro)

    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def has_blocking(results: list[HookResult]) -> bool:
    """Return True if any result signals a block (exit code 2)."""
    return any(r.exit_code == 2 for r in results)


def get_block_reason(results: list[HookResult]) -> str:
    """Return the reason from the first blocking result."""
    for r in results:
        if r.exit_code == 2 and r.reason:
            return r.reason
    return "Blocked by hook"


def get_additional_context(results: list[HookResult]) -> str:
    """Concatenate additional context from all successful results."""
    parts = [r.additional_context for r in results if r.additional_context]
    return "\n".join(parts)


def has_allow_decision(results: list[HookResult]) -> bool:
    """Return True if any result has decision='allow'."""
    return any(r.decision == "allow" for r in results)
