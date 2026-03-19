"""Interactive multi-select picker for /memory edit (delete + move)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Literal, Optional

from hooty.memory_store import format_memory_for_display
from hooty.ui import _read_key

if TYPE_CHECKING:
    from agno.db.schemas.memory import UserMemory
    from rich.console import Console
    from rich.panel import Panel

# Action returned by the picker
MemoryAction = Literal["delete", "move"]
PickResult = Optional[tuple[MemoryAction, list[str]]]


def _format_row(
    idx: int, info: dict[str, str], selected: bool, checked: bool,
) -> str:
    """Format a single row with cursor marker and checkbox."""
    cursor = "\u25b8" if selected else " "
    box = "[bold #E6C200]\u2611[/bold #E6C200]" if checked else "[dim]\u2610[/dim]"
    highlight_open = "[bold]" if selected else ""
    highlight_close = "[/bold]" if selected else ""
    topics = info["topics"][:16].ljust(16) if info["topics"] else " " * 16
    return (
        f"  {highlight_open}{cursor} {box} {idx:>2}  "
        f"[magenta]{info['short_id']}[/magenta]  "
        f"[dim]{topics}[/dim]  "
        f"{info['memory_text']}{highlight_close}"
    )


def _build_panel(
    memory_infos: list[dict[str, str]],
    selected: int,
    checked: list[bool],
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
    is_global: bool = False,
) -> "Panel":
    """Build a Panel showing memories with checkboxes."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(memory_infos)
    checked_count = sum(checked)
    visible = memory_infos[scroll_offset : scroll_offset + viewport_height]

    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=None,
        expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")

    # Scroll indicators (always present for stable height)
    if scroll_offset > 0:
        table.add_row(Text("\u25b2 more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for i, info in enumerate(visible):
        abs_idx = scroll_offset + i
        row = Text.from_markup(
            _format_row(abs_idx + 1, info, selected=abs_idx == selected, checked=checked[abs_idx]),
        )
        table.add_row(row)

    if scroll_offset + viewport_height < total:
        table.add_row(Text("\u25bc more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    # Footer
    table.add_row(Text())
    move_label = "move \u2192 project" if is_global else "move \u2192 global"
    footer_parts = [
        "\u2191\u2193 navigate",
        "Space toggle",
        "a all",
        "d delete",
        f"m {move_label}",
        "Esc cancel",
    ]
    table.add_row(
        Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]")
    )

    scope = "global" if is_global else "project"
    title = f"Manage {scope} memories \u2014 {checked_count}/{total} selected"
    return Panel(
        table,
        title=title,
        border_style="dim",
        width=width,
    )


def pick_memory_targets(
    memories: list["UserMemory"],
    console: "Console",
    is_global: bool = False,
) -> PickResult:
    """Interactive multi-select picker for memories.

    Returns (action, ids) tuple or None if cancelled.
    action is "delete" or "move".
    """
    if not memories:
        return None

    if sys.stdin.isatty():
        return _pick_interactive(memories, console, is_global)
    return _pick_fallback(memories, console, is_global)


def _get_checked_ids(
    memories: list["UserMemory"], checked: list[bool],
) -> list[str]:
    """Extract memory IDs for checked items."""
    return [
        memories[i].memory_id
        for i in range(len(memories))
        if checked[i] and memories[i].memory_id
    ]


def _pick_interactive(
    memories: list["UserMemory"],
    console: "Console",
    is_global: bool,
) -> PickResult:
    """Interactive picker with checkboxes using arrow keys."""
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    memory_infos = [format_memory_for_display(m) for m in memories]
    checked = [False] * len(memories)  # Unchecked by default
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = console.size.width - 2
    viewport_height = min(len(memories), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(
            memory_infos, selected, checked, viewport_height, scroll_offset,
            panel_width, is_global,
        )

    # Measure rendered line count
    buf = _MeasureConsole(width=panel_width, file=StringIO(), force_terminal=True)
    buf.print(_panel())
    move_up = buf.file.getvalue().count("\n")

    # Disable input echo
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
        pass

    console.print(_panel())

    try:
        while True:
            key = _read_key()
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(memories) - 1, selected + 1)
            elif key in (" ", "space"):
                checked[selected] = not checked[selected]
            elif key in ("a", "A"):
                if all(checked):
                    checked[:] = [False] * len(memories)
                else:
                    checked[:] = [True] * len(memories)
            elif key in ("d", "D", "enter"):
                ids = _get_checked_ids(memories, checked)
                return ("delete", ids) if ids else None
            elif key in ("m", "M"):
                ids = _get_checked_ids(memories, checked)
                return ("move", ids) if ids else None
            elif key in ("q", "Q", "escape", "ctrl-c"):
                return None

            # Keep selected in viewport
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


def _pick_fallback(
    memories: list["UserMemory"],
    console: "Console",
    is_global: bool,
) -> PickResult:
    """Fallback text picker for non-TTY environments."""
    memory_infos = [format_memory_for_display(m) for m in memories]
    scope = "Global" if is_global else "Project"
    move_label = "project" if is_global else "global"

    console.print()
    console.print(f"  {scope} memories ({len(memories)}):", style="bold")
    console.print()
    for idx, info in enumerate(memory_infos, 1):
        console.print(
            f"  [bold]{idx:>3}[/bold]  "
            f"[magenta]{info['short_id']}[/magenta]  "
            f"[dim]{info['topics']:<16}[/dim]  "
            f"{info['memory_text']}"
        )

    console.print()
    console.print(
        "  [dim]Enter numbers (e.g. 1,3,5), 'a' for all, then action:[/dim]"
    )
    console.print(
        f"  [dim]  d=delete  m=move to {move_label}  q=cancel[/dim]"
    )

    # Select items
    while True:
        try:
            choice = input("  select> ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None

        if choice.lower() == "a":
            ids = [m.memory_id for m in memories if m.memory_id]
            break

        try:
            nums = [int(x.strip()) for x in choice.split(",")]
        except ValueError:
            console.print("  [bold red]\u2717 Enter numbers separated by commas[/bold red]")
            continue

        if any(n < 1 or n > len(memories) for n in nums):
            console.print(f"  [bold red]\u2717 Please enter 1-{len(memories)}[/bold red]")
            continue

        ids = [memories[n - 1].memory_id for n in nums if memories[n - 1].memory_id]
        break

    if not ids:
        return None

    # Choose action
    while True:
        try:
            action = input("  action (d/m/q)> ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if action in ("d", "delete"):
            return ("delete", ids)
        elif action in ("m", "move"):
            return ("move", ids)
        elif action in ("q", ""):
            return None
        else:
            console.print("  [dim]d=delete  m=move  q=cancel[/dim]")
