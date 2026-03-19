"""Interactive multi-select picker for /hooks command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

from hooty.ui import _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel

    from hooty.hooks import HookEntry


def _format_row(
    event: str, entry: "HookEntry", selected: bool, checked: bool,
) -> str:
    """Format a single row with cursor marker and checkbox."""
    cursor = "\u25b8" if selected else " "
    hl_open = "[bold]" if selected else ""
    hl_close = "[/bold]" if selected else ""

    box = "[bold #E6C200]\u2611[/bold #E6C200]" if checked else "[dim]\u2610[/dim]"

    # Truncate multiline commands to first line
    cmd = entry.command.strip().split("\n")[0]
    if len(cmd) > 35:
        cmd = cmd[:32] + "..."
    # Escape Rich markup in command text
    cmd = cmd.replace("[", "\\[")

    extras: list[str] = []
    if entry.source:
        extras.append(entry.source)
    if entry.matcher:
        extras.append(entry.matcher)
    if entry.blocking:
        extras.append("blocking")
    extras.append(f"timeout: {entry.timeout}s")
    suffix = "  ".join(extras)

    return (
        f"  {hl_open}{cursor} {box}  "
        f"[cyan]{event:<22}[/cyan] "
        f"{cmd:<37} "
        f"[dim]{suffix}[/dim]{hl_close}"
    )


def _build_panel(
    items: list[tuple[str, "HookEntry"]],
    selected: int,
    checked: list[bool],
    viewport_height: int,
    scroll_offset: int,
    width: int = 90,
) -> "Panel":
    """Build a Panel showing hooks with checkboxes."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(items)
    enabled_count = sum(1 for c in checked if c)
    visible = items[scroll_offset : scroll_offset + viewport_height]

    table = Table(
        show_header=False, show_edge=False, show_lines=False,
        pad_edge=False, box=None, expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")

    if scroll_offset > 0:
        table.add_row(Text("\u25b2 more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for i, (event, entry) in enumerate(visible):
        abs_idx = scroll_offset + i
        row = Text.from_markup(
            _format_row(event, entry, selected=abs_idx == selected, checked=checked[abs_idx]),
        )
        table.add_row(row)

    if scroll_offset + viewport_height < total:
        table.add_row(Text("\u25bc more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    table.add_row(Text())
    footer_parts = ["\u2191\u2193 navigate", "Space toggle", "a all", "Enter apply"]
    table.add_row(Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]"))
    table.add_row(Text.from_markup("  [dim]Esc cancel[/dim]"))

    title = f"Hooks \u2014 {enabled_count}/{total} enabled"
    return Panel(table, title=title, border_style="dim", width=width)


def pick_hooks(
    items: list[tuple[str, "HookEntry"]],
    console: "Console",
) -> Optional[list[bool]]:
    """Interactive multi-select picker for hook enable/disable.

    *items* is a list of ``(event_name, HookEntry)`` tuples.
    Returns a list of booleans (per-hook enabled state), or None if cancelled.
    """
    if not items:
        return None

    if sys.stdin.isatty():
        return _pick_interactive(items, console)
    return None  # non-TTY: not supported


def _pick_interactive(
    items: list[tuple[str, "HookEntry"]],
    console: "Console",
) -> Optional[list[bool]]:
    """Interactive picker with checkboxes using arrow keys."""
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    checked = [entry.enabled for _, entry in items]
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = min(console.size.width - 2, 100)
    viewport_height = min(len(items), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(items, selected, checked, viewport_height, scroll_offset, panel_width)

    buf = _MeasureConsole(width=panel_width, file=StringIO(), force_terminal=True)
    buf.print(_panel())
    move_up = buf.file.getvalue().count("\n")

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
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()

        def _restore_term() -> None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
    except (ImportError, OSError, TypeError, ValueError):
        pass

    console.print(_panel())

    try:
        while True:
            key = _read_key()
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(items) - 1, selected + 1)
            elif key in (" ", "space"):
                checked[selected] = not checked[selected]
            elif key in ("a", "A"):
                new_state = not all(checked)
                checked = [new_state] * len(items)
            elif key == "enter":
                return checked
            elif key in ("q", "Q", "escape", "ctrl-c"):
                return None

            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + viewport_height:
                scroll_offset = selected - viewport_height + 1

            console.file.write(f"\033[{move_up}A\033[J")
            console.file.flush()
            console.print(_panel())
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if _restore_term:
            _restore_term()
