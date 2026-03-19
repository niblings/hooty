"""Interactive file/directory picker for /review scope selection."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from hooty.ui import _disable_echo, _measure_height, _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel


# Hidden entries that should never appear in the picker
_HIDDEN = {".git", "__pycache__", "node_modules", ".venv", ".mypy_cache", ".ruff_cache"}


def _list_entries(directory: str) -> tuple[list[str], list[str]]:
    """List visible directories and files in *directory*, sorted alphabetically.

    Returns (dirs, files).  Hidden entries (dotfiles, __pycache__, etc.) are excluded.
    """
    dirs: list[str] = []
    files: list[str] = []
    try:
        for entry in sorted(os.listdir(directory)):
            if entry.startswith(".") or entry in _HIDDEN:
                continue
            full = os.path.join(directory, entry)
            if os.path.isdir(full):
                dirs.append(entry)
            else:
                files.append(entry)
    except OSError:
        pass
    return dirs, files


def _build_panel(
    entries: list[tuple[str, str]],
    selected: int,
    viewport_height: int,
    scroll_offset: int,
    rel_path: str,
    width: int = 60,
    title: str = "● Review Target",
) -> "Panel":
    """Build a Panel showing directory entries with cursor."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(entries)
    visible = entries[scroll_offset : scroll_offset + viewport_height]

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

    for i, (icon, name) in enumerate(visible):
        abs_idx = scroll_offset + i
        cursor = "❯" if abs_idx == selected else " "
        if abs_idx == selected:
            row = Text.from_markup(
                f"    [bold cyan]{cursor}[/bold cyan] [bold]{icon} {name}[/bold]"
            )
        else:
            row = Text.from_markup(f"      {icon} [dim]{name}[/dim]")
        table.add_row(row)

    if scroll_offset + viewport_height < total:
        table.add_row(Text("▼ more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    # Footer
    table.add_row(Text())
    table.add_row(
        Text.from_markup(
            "    [dim]↑↓ move  Enter open/select  BS back  Esc cancel[/dim]"
        )
    )

    panel_title = f"{title} ── {rel_path}"
    return Panel(
        table,
        title=panel_title,
        title_align="left",
        border_style="cyan",
        width=width,
    )


def _make_entries(
    dirs: list[str], files: list[str], can_go_up: bool,
    *, dirs_only: bool = False,
) -> list[tuple[str, str]]:
    """Build the entry list: '. (this directory)', optional '..', then dirs, then files."""
    entries: list[tuple[str, str]] = [("📂", ". (this directory)")]
    if can_go_up:
        entries.append(("📂", ".."))
    for d in dirs:
        entries.append(("📂", d + "/"))
    if not dirs_only:
        for f in files:
            entries.append(("📄", f))
    return entries


def pick_file(
    root_dir: str,
    *,
    title: str = "● Review Target",
    con: "Console",
    allow_navigate_above: bool = False,
) -> str | None:
    """Interactive file/directory picker.

    Returns absolute path of selected target, or None if cancelled.
    When *allow_navigate_above* is False (default), cannot navigate above *root_dir*.
    """
    if sys.stdin.isatty():
        return _pick_interactive(root_dir, title=title, con=con, allow_navigate_above=allow_navigate_above)
    return _pick_fallback(root_dir, title=title, con=con, allow_navigate_above=allow_navigate_above)


def pick_directory(
    start_dir: str,
    *,
    title: str = "● Select Directory",
    con: "Console",
) -> str | None:
    """Interactive directory-only picker that can navigate above *start_dir*.

    Returns absolute path of selected directory, or None if cancelled.
    """
    if sys.stdin.isatty():
        return _pick_interactive(
            start_dir, title=title, con=con,
            dirs_only=True, allow_navigate_above=True,
        )
    return _pick_fallback(
        start_dir, title=title, con=con,
        dirs_only=True, allow_navigate_above=True,
    )


def _pick_interactive(
    root_dir: str,
    *,
    title: str,
    con: "Console",
    dirs_only: bool = False,
    allow_navigate_above: bool = False,
) -> str | None:
    """Interactive picker using arrow keys."""
    current_dir = os.path.abspath(root_dir)
    root = os.path.abspath(root_dir)
    selected = 0
    scroll_offset = 0

    panel_width = min(con.size.width - 2, 70)
    term_height = con.size.height

    def _rel_path() -> str:
        if allow_navigate_above:
            return current_dir + "/"
        rel = os.path.relpath(current_dir, root)
        if rel == ".":
            return os.path.basename(root) + "/"
        return os.path.basename(root) + "/" + rel + "/"

    def _can_go_up() -> bool:
        if allow_navigate_above:
            return os.path.dirname(current_dir) != current_dir  # not filesystem root
        return os.path.abspath(current_dir) != root

    def _refresh() -> tuple[list[tuple[str, str]], int]:
        nonlocal selected, scroll_offset
        dirs, files = _list_entries(current_dir)
        entries = _make_entries(dirs, files, _can_go_up(), dirs_only=dirs_only)
        # Clamp selection
        if selected >= len(entries):
            selected = max(0, len(entries) - 1)
        viewport = min(len(entries), max(3, term_height // 2 - 4))
        if scroll_offset > selected:
            scroll_offset = selected
        elif selected >= scroll_offset + viewport:
            scroll_offset = selected - viewport + 1
        return entries, viewport

    entries, viewport_height = _refresh()

    def _panel() -> "Panel":
        return _build_panel(
            entries, selected, viewport_height, scroll_offset,
            _rel_path(), panel_width, title,
        )

    move_up = _measure_height(_panel(), panel_width)
    restore = _disable_echo()
    con.print(_panel())

    try:
        while True:
            key = _read_key()
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(entries) - 1, selected + 1)
            elif key == "enter":
                icon, name = entries[selected]
                if name == ". (this directory)":
                    return current_dir
                elif name == "..":
                    if _can_go_up():
                        current_dir = os.path.dirname(current_dir)
                        selected = 0
                        scroll_offset = 0
                        entries, viewport_height = _refresh()
                elif icon == "📂":
                    current_dir = os.path.join(current_dir, name.rstrip("/"))
                    selected = 0
                    scroll_offset = 0
                    entries, viewport_height = _refresh()
                else:
                    return os.path.join(current_dir, name)
            elif key in ("\x7f", "\x08"):  # Backspace
                if _can_go_up():
                    current_dir = os.path.dirname(current_dir)
                    selected = 0
                    scroll_offset = 0
                    entries, viewport_height = _refresh()
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                continue

            # Keep selected in viewport
            if selected < scroll_offset:
                scroll_offset = selected
            elif selected >= scroll_offset + viewport_height:
                scroll_offset = selected - viewport_height + 1

            # Redraw
            con.file.write(f"\033[{move_up}A\033[J")
            con.file.flush()
            move_up = _measure_height(_panel(), panel_width)
            con.print(_panel())
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()


def _pick_fallback(
    root_dir: str,
    *,
    title: str,
    con: "Console",
    dirs_only: bool = False,
    allow_navigate_above: bool = False,
) -> str | None:
    """Non-TTY fallback: list entries and accept path input."""
    current_dir = os.path.abspath(root_dir)

    con.print()
    con.print(f"  {title}", style="bold")
    con.print()

    dirs, files = _list_entries(current_dir)
    idx = 1
    mapping: dict[int, str] = {}
    con.print(f"  [bold]{idx:>3}[/bold]  📂 . (this directory)")
    mapping[idx] = current_dir
    idx += 1

    for d in dirs:
        con.print(f"  [bold]{idx:>3}[/bold]  📂 {d}/")
        mapping[idx] = os.path.join(current_dir, d)
        idx += 1

    if not dirs_only:
        for f in files:
            con.print(f"  [bold]{idx:>3}[/bold]  📄 {f}")
            mapping[idx] = os.path.join(current_dir, f)
            idx += 1

    con.print()
    con.print("  [dim]Enter number to select, q to cancel[/dim]")

    while True:
        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            con.print()
            return None
        if not choice or choice.lower() == "q":
            return None
        try:
            num = int(choice)
        except ValueError:
            con.print("  [bold red]✗ Please enter a number[/bold red]")
            continue
        if num not in mapping:
            con.print(f"  [bold red]✗ Please enter 1-{len(mapping)}[/bold red]")
            continue
        return mapping[num]
