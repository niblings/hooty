"""Interactive unified picker for /plans (view + delete)."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

from hooty.ui import _read_key
from hooty.plan_store import PlanInfo, format_plan_for_display

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel


def _format_row(
    idx: int, info: dict[str, str], selected: bool, checked: bool,
) -> str:
    """Format a single row with cursor marker and checkbox."""
    cursor = "▸" if selected else " "
    box = "[bold #E6C200]☑[/bold #E6C200]" if checked else "[dim]☐[/dim]"
    highlight_open = "[bold]" if selected else ""
    highlight_close = "[/bold]" if selected else ""
    status_icon = info.get("status_icon", "?")
    return (
        f"  {highlight_open}{cursor} {box} {idx:>2}  "
        f"{status_icon} "
        f"[magenta]{info['short_id']}[/magenta]  "
        f"[dim]{info['created_at']}[/dim]  "
        f"{info['size']:>6}  "
        f"{info['summary']}{highlight_close}"
    )


def _build_panel(
    plan_infos: list[dict[str, str]],
    selected: int,
    checked: list[bool],
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
) -> "Panel":
    """Build a Panel showing plans with checkboxes."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(plan_infos)
    checked_count = sum(checked)
    visible = plan_infos[scroll_offset : scroll_offset + viewport_height]

    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=None,
        expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")

    # Scroll indicators
    if scroll_offset > 0:
        table.add_row(Text("▲ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for i, info in enumerate(visible):
        abs_idx = scroll_offset + i
        row = Text.from_markup(
            _format_row(abs_idx + 1, info, selected=abs_idx == selected, checked=checked[abs_idx]),
        )
        table.add_row(row)

    if scroll_offset + viewport_height < total:
        table.add_row(Text("▼ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    # Footer
    table.add_row(Text())
    footer_parts = [
        "↑↓ navigate",
        "Space toggle",
        "a all",
        "v view",
        "d delete",
        "Esc cancel",
    ]
    table.add_row(
        Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]")
    )

    title = f"Plans — {checked_count}/{total} selected"
    return Panel(
        table,
        title=title,
        border_style="dim",
        width=width,
    )


def pick_plans(
    plans: list[PlanInfo],
    console: "Console",
) -> Optional[tuple[str, list[str]]]:
    """Interactive unified picker for plans.

    Returns:
        ("view", [plan_id]) — view the plan at cursor
        ("delete", [plan_id, ...]) — delete checked plans
        None — cancelled
    """
    if not plans:
        return None

    if sys.stdin.isatty():
        return _pick_interactive(plans, console)
    return _pick_fallback(plans, console)


def _pick_interactive(
    plans: list[PlanInfo],
    console: "Console",
) -> Optional[tuple[str, list[str]]]:
    """Interactive picker with checkboxes using arrow keys."""
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    plan_infos = [format_plan_for_display(p) for p in plans]
    checked = [False] * len(plans)
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = console.size.width - 2
    viewport_height = min(len(plans), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(
            plan_infos, selected, checked, viewport_height, scroll_offset,
            panel_width,
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
                selected = min(len(plans) - 1, selected + 1)
            elif key in (" ", "space"):
                checked[selected] = not checked[selected]
            elif key in ("a", "A"):
                if all(checked):
                    checked[:] = [False] * len(plans)
                else:
                    checked[:] = [True] * len(plans)
            elif key in ("v", "V", "enter"):
                return ("view", [plans[selected].plan_id])
            elif key in ("d", "D"):
                ids = [
                    plans[i].plan_id
                    for i in range(len(plans))
                    if checked[i]
                ]
                if ids:
                    return ("delete", ids)
                # Nothing checked — ignore
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
    plans: list[PlanInfo],
    console: "Console",
) -> Optional[tuple[str, list[str]]]:
    """Fallback text picker for non-TTY environments."""
    plan_infos = [format_plan_for_display(p) for p in plans]

    console.print()
    console.print(f"  Plans ({len(plans)}):", style="bold")
    console.print()
    for idx, info in enumerate(plan_infos, 1):
        status_icon = info.get("status_icon", "?")
        console.print(
            f"  [bold]{idx:>3}[/bold]  "
            f"{status_icon} "
            f"[magenta]{info['short_id']}[/magenta]  "
            f"[dim]{info['created_at']}[/dim]  "
            f"{info['size']:>6}  "
            f"{info['summary']}"
        )

    console.print()
    console.print("  [dim]v <N> to view, d <N,...> to delete, 'a' to delete all, q to cancel[/dim]")

    while True:
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None

        lower = choice.lower()

        # View: v <N>
        if lower.startswith("v "):
            try:
                n = int(lower[2:].strip())
            except ValueError:
                console.print("  [bold red]✗ Usage: v <number>[/bold red]")
                continue
            if n < 1 or n > len(plans):
                console.print(f"  [bold red]✗ Please enter 1-{len(plans)}[/bold red]")
                continue
            return ("view", [plans[n - 1].plan_id])

        # Delete all
        if lower == "a":
            return ("delete", [p.plan_id for p in plans])

        # Delete: d <N,...>
        if lower.startswith("d "):
            rest = lower[2:].strip()
            try:
                nums = [int(x.strip()) for x in rest.split(",")]
            except ValueError:
                console.print("  [bold red]✗ Usage: d <numbers separated by commas>[/bold red]")
                continue
            if any(n < 1 or n > len(plans) for n in nums):
                console.print(f"  [bold red]✗ Please enter 1-{len(plans)}[/bold red]")
                continue
            return ("delete", [plans[n - 1].plan_id for n in nums])

        console.print("  [bold red]✗ Use v <N>, d <N,...>, a, or q[/bold red]")
