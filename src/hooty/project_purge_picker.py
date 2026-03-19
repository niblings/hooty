"""Interactive multi-select picker for /memory purge."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

from hooty.project_store import ProjectInfo, format_project_for_display
from hooty.ui import _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel


def _format_row(
    idx: int, info: dict[str, str], selected: bool, checked: bool,
) -> str:
    """Format a single row with cursor marker and checkbox."""
    cursor = "\u25b8" if selected else " "
    box = "[bold #E6C200]\u2611[/bold #E6C200]" if checked else "[dim]\u2610[/dim]"
    highlight_open = "[bold]" if selected else ""
    highlight_close = "[/bold]" if selected else ""

    parts = [
        f"  {highlight_open}{cursor} {box} {idx:>2}  ",
        f"[cyan]{info['dir_name']}[/cyan]  ",
    ]
    if info["path_display"]:
        parts.append(f"[dim]{info['path_display']}[/dim] ")
    if info["status"]:
        parts.append(f"[yellow]{info['status']}[/yellow]  ")
    if info["memory_count"]:
        parts.append(f"[dim]{info['memory_count']}[/dim]")
    parts.append(highlight_close)

    return "".join(parts)


def _build_panel(
    project_infos: list[dict[str, str]],
    selected: int,
    checked: list[bool],
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
) -> "Panel":
    """Build a Panel showing projects with checkboxes."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(project_infos)
    checked_count = sum(checked)
    visible = project_infos[scroll_offset : scroll_offset + viewport_height]

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
    footer_parts = [
        "\u2191\u2193 navigate",
        "Space toggle",
        "a all",
        "d delete",
        "Esc cancel",
    ]
    table.add_row(
        Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]")
    )

    title = f"Purge orphaned projects \u2014 {checked_count}/{total} selected"
    return Panel(
        table,
        title=title,
        border_style="dim",
        width=width,
    )


def pick_purge_targets(
    projects: list[ProjectInfo],
    console: "Console",
) -> Optional[list[ProjectInfo]]:
    """Interactive multi-select picker for orphaned projects to purge.

    Returns a list of ProjectInfo to delete, or None if cancelled.
    - Projects with path not found: checked ON by default
    - Projects with metadata missing: checked OFF by default
    """
    if not projects:
        return None

    if sys.stdin.isatty():
        return _pick_interactive(projects, console)
    return _pick_fallback(projects, console)


def _default_checked(projects: list[ProjectInfo]) -> list[bool]:
    """Determine default checked state for each project.

    Path not found (orphaned) → ON, metadata missing → OFF.
    """
    checked: list[bool] = []
    for p in projects:
        if p.working_directory is not None:
            # Has metadata, path not found → ON
            checked.append(True)
        else:
            # No metadata → OFF
            checked.append(False)
    return checked


def _pick_interactive(
    projects: list[ProjectInfo],
    console: "Console",
) -> Optional[list[ProjectInfo]]:
    """Interactive picker with checkboxes using arrow keys."""
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    project_infos = [format_project_for_display(p) for p in projects]
    checked = _default_checked(projects)
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = console.size.width - 2
    viewport_height = min(len(projects), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(
            project_infos, selected, checked, viewport_height, scroll_offset,
            panel_width,
        )

    # Measure rendered line count (constant height due to always-present indicators)
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
                selected = min(len(projects) - 1, selected + 1)
            elif key in (" ", "space"):
                checked[selected] = not checked[selected]
            elif key in ("a", "A"):
                if all(checked):
                    checked[:] = [False] * len(projects)
                else:
                    checked[:] = [True] * len(projects)
            elif key in ("d", "D", "enter"):
                result = [
                    projects[i]
                    for i in range(len(projects))
                    if checked[i]
                ]
                return result if result else None
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
    projects: list[ProjectInfo],
    console: "Console",
) -> Optional[list[ProjectInfo]]:
    """Fallback text picker for non-TTY environments."""
    project_infos = [format_project_for_display(p) for p in projects]

    console.print()
    console.print(f"  Orphaned projects ({len(projects)}):", style="bold")
    console.print()
    for idx, info in enumerate(project_infos, 1):
        parts = [f"  [bold]{idx:>3}[/bold]  [cyan]{info['dir_name']}[/cyan]"]
        if info["path_display"]:
            parts.append(f"  [dim]{info['path_display']}[/dim]")
        if info["status"]:
            parts.append(f"  [yellow]{info['status']}[/yellow]")
        if info["memory_count"]:
            parts.append(f"  [dim]{info['memory_count']}[/dim]")
        console.print("".join(parts))

    console.print()
    console.print("  [dim]Enter numbers to delete (e.g. 1,3,5), 'a' for all, q to cancel[/dim]")

    while True:
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None

        if choice.lower() == "a":
            return list(projects)

        try:
            nums = [int(x.strip()) for x in choice.split(",")]
        except ValueError:
            console.print("  [bold red]\u2717 Enter numbers separated by commas[/bold red]")
            continue

        if any(n < 1 or n > len(projects) for n in nums):
            console.print(f"  [bold red]\u2717 Please enter 1-{len(projects)}[/bold red]")
            continue

        return [projects[n - 1] for n in nums]
