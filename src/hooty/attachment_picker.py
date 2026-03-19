"""Interactive picker for /attach list — view and delete attachments."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING

from hooty.attachment import Attachment, AttachmentStack, _format_size
from hooty.ui import _disable_echo, _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel


def _format_row(idx: int, item: Attachment, selected: bool, checked: bool) -> str:
    """Format a single row with cursor marker and checkbox."""
    cursor = "▸" if selected else " "
    box = "[bold #E6C200]☑[/bold #E6C200]" if checked else "[dim]☐[/dim]"
    hl_open = "[bold]" if selected else ""
    hl_close = "[/bold]" if selected else ""

    if item.kind == "image":
        size_str = f"{item.width}x{item.height}" if item.width and item.height else "?"
        detail = f"image  {size_str}"
    else:
        detail = f"text   {_format_size(item.file_size)}"

    tokens = f"~{item.estimated_tokens}tk"
    return (
        f"  {hl_open}{cursor} {box}  "
        f"{item.display_name:<20s} {detail:<16s} {tokens}{hl_close}"
    )


def _build_panel(
    items: list[Attachment],
    selected: int,
    checked: list[bool],
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
) -> "Panel":
    """Build a Panel showing attachments with checkboxes."""
    from rich.panel import Panel as RPanel
    from rich.table import Table
    from rich.text import Text

    total = len(items)
    checked_count = sum(checked)
    visible = items[scroll_offset : scroll_offset + viewport_height]

    table = Table(
        show_header=False, show_edge=False, show_lines=False,
        pad_edge=False, box=None, expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")

    # Scroll indicators
    if scroll_offset > 0:
        table.add_row(Text("▲ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for i, item in enumerate(visible):
        abs_idx = scroll_offset + i
        row = Text.from_markup(
            _format_row(abs_idx, item, selected=abs_idx == selected, checked=checked[abs_idx]),
        )
        table.add_row(row)

    if scroll_offset + viewport_height < total:
        table.add_row(Text("▼ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    # Footer
    table.add_row(Text())
    footer_parts = [
        "↑↓ move",
        "Space toggle",
        "a all",
        "d delete",
        "Esc close",
    ]
    table.add_row(
        Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]")
    )

    title = f"\U0001f4ce Attachments — {checked_count}/{total} selected"
    return RPanel(table, title=title, border_style="dim", width=width)


def pick_attachments(stack: AttachmentStack, console: Console) -> None:
    """Interactive picker for attachment management. Mutates stack in-place."""
    items = stack.items()
    if not items:
        console.print("  [dim]No attachments.[/dim]")
        return

    if not sys.stdin.isatty():
        # Fallback: just list items
        for i, item in enumerate(items):
            console.print(f"  {i + 1}. {item.display_name} \\[{item.kind}, ~{item.estimated_tokens}tk]")
        return

    from io import StringIO
    from rich.console import Console as _MeasureConsole

    checked = [False] * len(items)
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = console.size.width - 2
    viewport_height = min(len(items), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(
            items, selected, checked, viewport_height, scroll_offset, panel_width,
        )

    # Measure rendered line count
    buf = _MeasureConsole(width=panel_width, file=StringIO(), force_terminal=True)
    buf.print(_panel())
    move_up = buf.file.getvalue().count("\n")

    restore = _disable_echo()
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
                if all(checked):
                    checked[:] = [False] * len(items)
                else:
                    checked[:] = [True] * len(items)
            elif key in ("d", "D"):
                indices = [i for i in range(len(items)) if checked[i]]
                if indices:
                    stack.remove(indices)
                    items = stack.items()
                    if not items:
                        break
                    checked = [False] * len(items)
                    selected = min(selected, len(items) - 1)
                    viewport_height = min(len(items), max(3, term_height // 2 - 6))
                    # Re-measure panel height
                    buf2 = _MeasureConsole(width=panel_width, file=StringIO(), force_terminal=True)
                    buf2.print(_panel())
                    move_up_new = buf2.file.getvalue().count("\n")
                    # Clear more lines than new panel (old panel may be taller)
                    console.file.write(f"\033[{move_up}A\033[J")
                    console.file.flush()
                    move_up = move_up_new
                    console.print(_panel())
                    continue
            elif key in ("q", "Q", "escape", "ctrl-c"):
                break

            # Keep selected in viewport
            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + viewport_height:
                scroll_offset = selected - viewport_height + 1

            console.file.write(f"\033[{move_up}A\033[J")
            console.file.flush()
            console.print(_panel())
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        if restore:
            restore()
