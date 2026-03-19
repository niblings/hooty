"""Interactive multi-select picker for review findings."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from hooty.review import FixRequest
from hooty.ui import _disable_echo, _measure_height, _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel


_SEVERITY_ICON = {
    "Critical": "🔴",
    "Warning": "🟡",
    "Suggestion": "🔵",
}


def _format_row(
    idx: int,
    finding: dict,
    selected: bool,
    checked: bool,
    custom_instruction: str | None = None,
) -> str:
    """Format a single row with cursor marker, checkbox, severity and location."""
    cursor = "▸" if selected else " "
    box = "[bold #E6C200]☑[/bold #E6C200]" if checked else "[dim]☐[/dim]"
    severity = finding.get("severity", "Info")
    icon = _SEVERITY_ICON.get(severity, "🔵")
    file_ref = finding.get("file", "")
    line = finding.get("line")
    loc = f"{file_ref}:{line}" if line else file_ref
    title = finding.get("title", "")

    highlight_open = "[bold]" if selected else ""
    highlight_close = "[/bold]" if selected else ""

    # Truncate location for alignment
    loc_display = loc[:20].ljust(20)

    row = (
        f"  {highlight_open}{cursor} {box}  {idx:>2}  "
        f"{icon} {severity:<10} {loc_display} "
        f"{title}{highlight_close}"
    )

    if custom_instruction:
        row += f"\n       [dim italic]  ↳ {custom_instruction}[/dim italic]"

    return row


def _build_panel(
    findings: list[dict],
    selected: int,
    checked: list[bool],
    custom_instructions: list[str | None],
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
) -> "Panel":
    """Build a Panel showing findings with checkboxes."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(findings)
    checked_count = sum(checked)
    visible_range = range(scroll_offset, min(scroll_offset + viewport_height, total))

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
        table.add_row(Text("▲ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for abs_idx in visible_range:
        row = Text.from_markup(
            _format_row(
                abs_idx + 1,
                findings[abs_idx],
                selected=abs_idx == selected,
                checked=checked[abs_idx],
                custom_instruction=custom_instructions[abs_idx],
            ),
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
        "i instruct",
        "f fix selected",
        "Esc cancel",
    ]
    table.add_row(
        Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]")
    )

    title = f"Review Findings — {checked_count}/{total} selected"
    return Panel(
        table,
        title=title,
        border_style="dim",
        width=width,
    )


def pick_review_findings(
    findings: list[dict],
    console: "Console",
) -> list[FixRequest] | None:
    """Multi-select picker for review findings.

    Returns selected findings with optional custom instructions,
    or None if cancelled.
    """
    if not findings:
        return None

    if sys.stdin.isatty():
        return _pick_interactive(findings, console)
    return _pick_fallback(findings, console)


def _pick_interactive(
    findings: list[dict],
    console: "Console",
) -> list[FixRequest] | None:
    """Interactive picker with checkboxes using arrow keys."""
    checked = [False] * len(findings)
    custom_instructions: list[str | None] = [None] * len(findings)
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = min(console.size.width - 2, 90)
    viewport_height = min(len(findings), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(
            findings, selected, checked, custom_instructions,
            viewport_height, scroll_offset, panel_width,
        )

    move_up = _measure_height(_panel(), panel_width)
    restore = _disable_echo()
    console.print(_panel())

    try:
        while True:
            key = _read_key()
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(findings) - 1, selected + 1)
            elif key in (" ", "space"):
                checked[selected] = not checked[selected]
            elif key in ("a", "A"):
                # Toggle all
                if all(checked):
                    checked[:] = [False] * len(findings)
                else:
                    checked[:] = [True] * len(findings)
            elif key in ("i", "I"):
                # Add custom instruction for current finding
                if checked[selected] or True:  # Allow instruction on any finding
                    # Erase picker, show text input, then redraw
                    console.file.write(f"\033[{move_up}A\033[J")
                    console.file.flush()

                    # Temporarily restore terminal for text_input
                    if restore:
                        restore()

                    from hooty.ui import text_input

                    f = findings[selected]
                    severity = f.get("severity", "Info")
                    icon = _SEVERITY_ICON.get(severity, "🔵")
                    file_ref = f.get("file", "")
                    title = f.get("title", "")
                    subtitle = f"{icon} {file_ref} — {title}"

                    result = text_input(
                        title="● Custom fix instruction",
                        subtitle=subtitle,
                        con=console,
                    )
                    if result:
                        custom_instructions[selected] = result
                        # Auto-check when instruction is added
                        checked[selected] = True

                    # Re-disable echo for picker
                    restore = _disable_echo()
                    move_up = _measure_height(_panel(), panel_width)
                    console.print(_panel())
                    continue
            elif key in ("f", "F", "enter"):
                result_list = [
                    FixRequest(
                        finding=findings[i],
                        custom_instruction=custom_instructions[i],
                    )
                    for i in range(len(findings))
                    if checked[i]
                ]
                return result_list if result_list else None
            elif key in ("q", "Q", "escape", "ctrl-c"):
                return None
            else:
                continue

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
        if restore:
            restore()


def _pick_fallback(
    findings: list[dict],
    console: "Console",
) -> list[FixRequest] | None:
    """Fallback text picker for non-TTY environments."""
    console.print()
    console.print(f"  Review Findings ({len(findings)}):", style="bold")
    console.print()

    for idx, f in enumerate(findings, 1):
        severity = f.get("severity", "Info")
        icon = _SEVERITY_ICON.get(severity, "🔵")
        file_ref = f.get("file", "")
        line = f.get("line")
        loc = f"{file_ref}:{line}" if line else file_ref
        title = f.get("title", "")
        console.print(f"  [bold]{idx:>3}[/bold]  {icon} {severity:<10} {loc:<20} {title}")

    console.print()
    console.print("  [dim]Enter numbers to fix (e.g. 1,3,5), 'a' for all, q to cancel[/dim]")

    while True:
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None

        if choice.lower() == "a":
            return [FixRequest(finding=f) for f in findings]

        try:
            nums = [int(x.strip()) for x in choice.split(",")]
        except ValueError:
            console.print("  [bold red]✗ Enter numbers separated by commas[/bold red]")
            continue

        if any(n < 1 or n > len(findings) for n in nums):
            console.print(f"  [bold red]✗ Please enter 1-{len(findings)}[/bold red]")
            continue

        return [FixRequest(finding=findings[n - 1]) for n in nums]
