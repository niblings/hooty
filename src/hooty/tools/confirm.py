"""Confirmation dialog utilities shared across tool modules."""

from __future__ import annotations

import logging
import sys
import threading
from typing import Any

from hooty.ui import _active_console, hotkey_select

logger = logging.getLogger("hooty")

# Shared reference to the active Rich Live instance (set by REPL during streaming)
_active_live: list[Any] = [None]

# Auto-approve flag for the current response turn (reset by REPL each turn)
_auto_approve: list[bool] = [False]

# Non-interactive mode flag (set once at startup, never reset)
_non_interactive: list[bool] = [False]

# Serialise confirmation dialogs so parallel tool calls don't race on stdin/termios.
_confirm_lock = threading.Lock()

# Hook references injected by REPL (hooks_config, session_id, cwd, loop)
_hooks_ref: list[Any] = [None, None, None, None]

# Windows deferred task-cancellation flag.  Set by the console-ctrl handler
# when CTRL-C arrives during tool execution.  A scheduled event-loop callback
# checks this flag and cancels the main async task only if still True.
# Interactive dialogs clear it on return so that a CTRL-C during a dialog
# does not poison execution after the user makes a choice.
_win_cancel_requested: list[bool] = [False]


def _clear_win_cancel_state() -> None:
    """Clear cancellation state left by CTRL-C during an interactive dialog.

    On Windows, the console-ctrl handler suppresses CTRL-C and sets
    cancellation events/flags.  If this happens while a dialog is
    visible, those events become stale once the user makes a choice.
    Call this after any interactive dialog returns normally (not via
    ``KeyboardInterrupt``).
    """
    if sys.platform != "win32":
        return
    _win_cancel_requested[0] = False
    try:
        from hooty.tools.sub_agent_runner import cancel_event
        cancel_event.clear()
    except ImportError:
        pass
    try:
        from hooty.tools.shell_runner import _interrupt_event
        _interrupt_event.clear()
    except ImportError:
        pass

def _flush_win_input() -> None:
    """Drain stale characters from the Windows console input buffer.

    ConPTY may echo back escape-sequence bytes after a Rich panel is
    rendered.  If left in the buffer they can be mis-interpreted as
    keyboard input on subsequent reads.  On non-Windows platforms this
    is a no-op.
    """
    if sys.platform != "win32":
        return
    try:
        import msvcrt

        flushed = 0
        while msvcrt.kbhit():
            msvcrt.getwch()
            flushed += 1
        if flushed:
            logger.debug("[win-flush] drained %d stale chars from console input", flushed)
    except Exception:  # noqa: BLE001
        pass


CONFIRM_OPTIONS: list[tuple[str, str]] = [
    ("Y", "Yes, approve this action."),
    ("N", "No, reject this action."),
    ("A", "All, approve remaining actions."),
    ("Q", "Quit, cancel execution."),
]


def _confirm_action(description: str, *, title: str = "\u26a0", tool_name: str = "") -> bool:
    """Prompt user for confirmation using a Rich Panel hotkey selector.

    Returns True if the user approved, False otherwise.
    Raises KeyboardInterrupt if the user chooses Quit.
    """
    if _auto_approve[0]:
        return True

    # Hook: PermissionRequest
    hooks_config, session_id, cwd, loop = _hooks_ref
    if hooks_config and session_id:
        try:
            from hooty.hooks import (
                HookEvent,
                emit_hook_sync,
                get_block_reason,
                has_allow_decision,
                has_blocking,
            )

            results = emit_hook_sync(
                HookEvent.PERMISSION_REQUEST, hooks_config,
                session_id, cwd or "",
                loop=loop,
                tool_name=tool_name,
                description=description,
            )
            if has_blocking(results):
                reason = get_block_reason(results)
                logger.info("PermissionRequest blocked by hook: %s", reason)
                return False
            if has_allow_decision(results):
                return True
        except Exception:
            logger.debug("PermissionRequest hook error", exc_info=True)

    # Non-interactive mode: no stdin available — deny by default
    if _non_interactive[0]:
        import sys

        print(
            f"[non-interactive] denied: {description}",
            file=sys.stderr,
        )
        return False

    with _confirm_lock:
        # Re-check after acquiring lock (another thread may have set "All")
        if _auto_approve[0]:
            return True

        live = _active_live[0]
        if live:
            live.stop()
            # Erase residual spinner content for ConPTY
            from hooty.repl_ui import _erase_live_area

            lr = getattr(live, "_live_render", None)
            shape = getattr(lr, "_shape", None)
            height = shape[1] if shape else 1
            _erase_live_area(live.console.file, height)

        try:
            con = _active_console[0]
            if con is None:
                from rich.console import Console

                con = Console()

            key = hotkey_select(
                CONFIRM_OPTIONS,
                title=title,
                subtitle=description,
                border_style="yellow",
                con=con,
            )
            _flush_win_input()
        finally:
            if live:
                live.start()

        if key == "Q":
            raise KeyboardInterrupt
        # Clear any cancellation state set by CTRL-C during the dialog.
        # The user made a deliberate choice (Y/N/A), so stale cancel
        # signals should not poison subsequent execution.
        _clear_win_cancel_state()
        if key == "A":
            _auto_approve[0] = True
            return True
        return key == "Y"
