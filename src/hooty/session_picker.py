"""Interactive session picker for --resume flag."""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import TYPE_CHECKING, Optional

from hooty.session_store import format_session_for_display, list_sessions
from hooty.ui import _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel

    from hooty.config import AppConfig


def _compute_mismatched_ids(
    session_infos: list[dict[str, str]],
    current_wd: str,
    config_dir: Path,
) -> set[str]:
    """Return session IDs whose working directory differs from *current_wd*.

    Checks workspace.yaml first (already rebound on resume), then falls
    back to the DB's session_state working_directory.
    """
    if not current_wd:
        return set()

    from hooty.workspace import load_workspace

    norm_cwd = os.path.normcase(os.path.normpath(current_wd))
    mismatched: set[str] = set()
    sessions_base = config_dir / "sessions"

    for info in session_infos:
        sid = info["session_id"]
        # Prefer workspace.yaml (reflects rebind); fall back to DB value
        wd: str | None = None
        session_dir = sessions_base / sid
        if session_dir.exists():
            wd = load_workspace(session_dir)
        if not wd:
            wd = info.get("working_directory", "")
        if wd and os.path.normcase(os.path.normpath(wd)) != norm_cwd:
            mismatched.add(sid)

    return mismatched


def _fork_col(info: dict[str, str]) -> str:
    """Return a fixed-width fork origin column value."""
    forked = info.get("forked_from", "")
    return f"⑂ {forked[:8]}" if forked else "—"


def _project_col(info: dict[str, str], mismatched: bool = False) -> str:
    """Return a pre-padded project column value with optional mismatch marker.

    Returns a string already padded to 16 visual characters so that
    Rich markup (for the 🚫 marker) does not break alignment.
    """
    project = info.get("project", "\u2014")
    if len(project) > 12:
        project = project[:9] + "..."
    if mismatched:
        # 🚫 + space = 3 visual chars; pad project text to fill remaining 13
        return f"🚫 {project:<13}"
    return f"{project:<16}"


def _format_row(
    idx: int, info: dict[str, str], selected: bool,
    locked: bool = False, mismatched: bool = False,
) -> str:
    """Format a single session row with optional selection marker."""
    fork = _fork_col(info)
    project = _project_col(info, mismatched=mismatched)
    if locked:
        marker = "🔒"
        return (
            f"  [dim]{marker} {idx:>2}  "
            f"{info['short_id']}  "
            f"{fork:<12}"
            f"{info['updated_at']}  "
            f"{info['run_count']:>4}   "
            f"{project}"
            f"{info['preview']}[/dim]"
        )
    marker = "▸" if selected else " "
    highlight_open = "[bold]" if selected else ""
    highlight_close = "[/bold]" if selected else ""
    return (
        f"  {highlight_open}{marker} {idx:>2}  "
        f"[magenta]{info['short_id']}[/magenta]  "
        f"[dim]{fork:<12}[/dim]"
        f"[dim]{info['updated_at']}[/dim]  "
        f"{info['run_count']:>4}   "
        f"{project}"
        f"{info['preview']}{highlight_close}"
    )


def _build_panel(
    session_infos: list[dict[str, str]],
    selected: int,
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
    locked_ids: set[str] | None = None,
    mismatched_ids: set[str] | None = None,
) -> "Panel":
    """Build a Panel dialog showing a viewport slice of sessions.

    Args:
        width: Explicit panel width (typically console.size.width).
        locked_ids: Set of session IDs that are locked by other processes.
        mismatched_ids: Set of session IDs whose working directory differs from CWD.
    """
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    _locked = locked_ids or set()
    _mismatched = mismatched_ids or set()
    total = len(session_infos)
    visible = session_infos[scroll_offset : scroll_offset + viewport_height]

    # Single-column Table enforces width constraints on every row
    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=None,
        expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")

    # Always include both indicator rows to keep panel height constant
    # (Live tracks previous frame height for cursor repositioning).
    if scroll_offset > 0:
        table.add_row(Text("▲ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for i, info in enumerate(visible):
        abs_idx = scroll_offset + i
        sid = info.get("session_id", "")
        is_locked = sid in _locked
        is_mismatched = sid in _mismatched
        row = Text.from_markup(
            _format_row(
                abs_idx + 1, info, selected=abs_idx == selected,
                locked=is_locked, mismatched=is_mismatched,
            ),
        )
        table.add_row(row)

    if scroll_offset + viewport_height < total:
        table.add_row(Text("▼ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    # Footer with key hints and legend
    table.add_row(Text())
    footer = "  [dim]↑↓ navigate  Enter select  n new session  Esc to cancel[/dim]"
    if _mismatched:
        footer += "\n  [dim]🚫 different working directory[/dim]"
    table.add_row(Text.from_markup(footer))

    return Panel(
        table,
        title=f"Saved sessions ({total})",
        border_style="dim",
        width=width,
    )


def _pick_interactive(
    sessions: list[dict], total: int, console: Console,
    locked_ids: set[str] | None = None,
    current_wd: str = "",
    config_dir: Path | None = None,
) -> Optional[str]:
    """Interactive picker using arrow keys.

    Disables input echo for the entire picker session so that
    arrow-key escape sequences are never leaked to stdout
    (fixes WSL / Windows Terminal rendering).  Uses manual ANSI
    cursor control instead of Rich Live.
    """
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    _locked = locked_ids or set()
    session_infos = [format_session_for_display(s) for s in sessions]
    selected = 0
    scroll_offset = 0

    # Compute mismatched session IDs (workspace.yaml preferred over DB)
    mismatched_ids: set[str] = set()
    if current_wd and config_dir:
        mismatched_ids = _compute_mismatched_ids(session_infos, current_wd, config_dir)

    # Compute viewport height and panel width based on terminal size.
    # Subtract 2 from width to avoid line-wrap on terminals where writing
    # to the last column advances the cursor (common on WSL / Windows Terminal).
    term_height = console.size.height
    panel_width = console.size.width - 2
    viewport_height = min(len(sessions), max(3, term_height // 2 - 4))

    def _panel() -> "Panel":
        return _build_panel(
            session_infos, selected, viewport_height, scroll_offset, panel_width,
            locked_ids=_locked, mismatched_ids=mismatched_ids,
        )

    # Measure rendered line count once (constant — indicator rows always present)
    buf = _MeasureConsole(width=panel_width, file=StringIO(), force_terminal=True)
    buf.print(_panel())
    move_up = buf.file.getvalue().count("\n")

    # Disable input echo for the entire picker session.
    # _read_key() toggles raw mode per-keystroke; between calls the terminal
    # briefly returns to normal mode where echo is enabled.  On WSL this
    # window is long enough for arrow-key sequences to be echoed to stdout.
    # Keeping ECHO disabled throughout eliminates the race.
    _restore_term = None
    try:
        import termios

        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        new_attrs = termios.tcgetattr(fd)
        new_attrs[3] &= ~(termios.ECHO | termios.ICANON)
        new_attrs[6][termios.VMIN] = 1
        new_attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
        # Hide cursor
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        def _restore_term() -> None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            # Show cursor
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
    except (ImportError, OSError, TypeError, ValueError):
        pass  # Not a Unix tty or mocked stdin; _read_key() manages its own mode

    # Render initial panel
    console.print(_panel())

    try:
        while True:
            key = _read_key()
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(sessions) - 1, selected + 1)
            elif key == "enter":
                sid = sessions[selected]["session_id"]
                if sid not in _locked:
                    return sid
                # Locked session — ignore Enter
            elif key in ("n", "N"):
                return ""
            elif key in ("q", "Q", "escape", "ctrl-c"):
                return None

            # Adjust scroll_offset to keep selected row visible
            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + viewport_height:
                scroll_offset = selected - viewport_height + 1

            # Move cursor to start of panel, clear below, and reprint
            console.file.write(f"\033[{move_up}A\033[J")
            console.file.flush()
            console.print(_panel())
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if _restore_term:
            _restore_term()


def _pick_fallback(
    sessions: list[dict], total: int, console: Console,
    locked_ids: set[str] | None = None,
    current_wd: str = "",
    config_dir: Path | None = None,
) -> Optional[str]:
    """Fallback picker using number input for non-TTY environments."""
    _locked = locked_ids or set()
    session_infos = [format_session_for_display(s) for s in sessions]

    # Compute mismatched session IDs (workspace.yaml preferred over DB)
    mismatched_ids: set[str] = set()
    if current_wd and config_dir:
        mismatched_ids = _compute_mismatched_ids(session_infos, current_wd, config_dir)

    # Display header
    console.print()
    console.print(f"  Saved sessions ({total}):", style="bold")
    console.print()
    console.print(
        f"  {'#':<4} {'ID':<10} {'Forked':<12} {'Updated':<18} {'Runs':<6} {'Project':<16} {'First message'}",
        style="dim",
    )
    console.print(
        f"  {'─' * 4} {'─' * 10} {'─' * 12} {'─' * 18} {'─' * 6} {'─' * 16} {'─' * 22}",
        style="dim",
    )

    for idx, info in enumerate(session_infos, 1):
        sid = info["session_id"]
        is_locked = sid in _locked
        is_mismatched = sid in mismatched_ids
        lock_mark = " 🔒" if is_locked else ""
        fork = _fork_col(info)
        project = _project_col(info, mismatched=is_mismatched)
        style_open = "[dim]" if is_locked else ""
        style_close = "[/dim]" if is_locked else ""
        console.print(
            f"  {style_open}[bold]{idx:>3}[/bold]  "
            f"[magenta]{info['short_id']}[/magenta]  "
            f"[dim]{fork:<12}[/dim]"
            f"[dim]{info['updated_at']}[/dim]  "
            f"{info['run_count']:>4}   "
            f"{project}"
            f"{info['preview']}{lock_mark}{style_close}"
        )

    console.print()
    console.print("  [dim]Enter number to select, n for new session, q to cancel[/dim]")

    while True:
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None
        if choice.lower() == "n":
            return ""

        try:
            num = int(choice)
        except ValueError:
            console.print("  [bold red]✗ Please enter a number[/bold red]")
            continue

        if num < 1 or num > len(sessions):
            console.print(
                f"  [bold red]✗ Please enter 1-{len(sessions)}[/bold red]"
            )
            continue

        chosen = sessions[num - 1]
        if chosen["session_id"] in _locked:
            console.print("  [bold red]✗ That session is locked by another process[/bold red]")
            continue

        return chosen["session_id"]


def pick_session(config: AppConfig, console: Console) -> Optional[str]:
    """Display an interactive session picker and return the chosen session ID.

    Uses arrow-key navigation when stdin is a TTY, otherwise falls back to
    number input.

    Returns None if no sessions exist, the user cancels, or an error occurs.
    """
    try:
        sessions, total = list_sessions(config, limit=20)
    except Exception:
        console.print("  [bold red]✗ Failed to load sessions[/bold red]")
        return None

    if not sessions:
        console.print("  [dim]No saved sessions found.[/dim]")
        return None

    # Determine which sessions are locked by other processes
    locked_ids: set[str] = set()
    try:
        from hooty.session_lock import is_locked
        for s in sessions:
            sid = s.get("session_id", "")
            if sid and is_locked(config, sid):
                locked_ids.add(sid)
    except Exception:
        pass

    current_wd = config.working_directory
    config_dir = config.config_dir

    if sys.stdin.isatty():
        return _pick_interactive(
            sessions, total, console,
            locked_ids=locked_ids, current_wd=current_wd, config_dir=config_dir,
        )
    return _pick_fallback(
        sessions, total, console,
        locked_ids=locked_ids, current_wd=current_wd, config_dir=config_dir,
    )
