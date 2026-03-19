"""Interactive multi-select picker for /skills command."""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

from hooty.ui import _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel

    from hooty.skill_store import SkillInfo


def _format_row(
    skill: "SkillInfo", selected: bool, checked: bool,
) -> str:
    """Format a single row with cursor marker and checkbox."""
    cursor = "\u25b8" if selected else " "
    highlight_open = "[bold]" if selected else ""
    highlight_close = "[/bold]" if selected else ""

    if skill.disable_model_invocation:
        # Manual-only skill — not toggleable
        box = "[dim]\u2298[/dim]"
        suffix = "[dim][manual only][/dim]"
    else:
        box = "[bold #E6C200]\u2611[/bold #E6C200]" if checked else "[dim]\u2610[/dim]"
        if not skill.user_invocable:
            suffix = "[dim][auto only][/dim]"
        else:
            suffix = ""

    # Truncate description
    desc = skill.description
    if len(desc) > 30:
        desc = desc[:27] + "..."

    source = skill.source
    # Shorten source labels
    for full, short in [
        ("project (.claude)", ".claude"),
        ("project (.github)", ".github"),
        ("project (.hooty)", ".hooty"),
    ]:
        if source == full:
            source = short
            break

    return (
        f"  {highlight_open}{cursor} {box}  "
        f"[cyan]{skill.name:<18}[/cyan] "
        f"[dim]{source:<8}[/dim] "
        f"{desc}  {suffix}{highlight_close}"
    )


def _build_panel(
    skills: list["SkillInfo"],
    selected: int,
    checked: list[bool],
    viewport_height: int,
    scroll_offset: int,
    width: int = 80,
) -> "Panel":
    """Build a Panel showing skills with checkboxes."""
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    total = len(skills)
    enabled_count = sum(
        1 for i, s in enumerate(skills)
        if checked[i] and not s.disable_model_invocation
    )
    toggleable = sum(1 for s in skills if not s.disable_model_invocation)
    visible = skills[scroll_offset : scroll_offset + viewport_height]

    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=None,
        expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")

    # Scroll indicator top
    if scroll_offset > 0:
        table.add_row(Text("\u25b2 more", style="dim", justify="right"))
    else:
        table.add_row(Text())

    for i, skill in enumerate(visible):
        abs_idx = scroll_offset + i
        row = Text.from_markup(
            _format_row(skill, selected=abs_idx == selected, checked=checked[abs_idx]),
        )
        table.add_row(row)

    # Scroll indicator bottom
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
        "Enter apply",
    ]
    table.add_row(
        Text.from_markup(f"  [dim]{'  '.join(footer_parts)}[/dim]")
    )
    table.add_row(
        Text.from_markup("  [dim]Esc cancel[/dim]")
    )

    title = f"Skills \u2014 {enabled_count}/{toggleable} enabled"
    return Panel(
        table,
        title=title,
        border_style="dim",
        width=width,
    )


def pick_skills(
    skills: list["SkillInfo"],
    console: "Console",
) -> Optional[list[bool]]:
    """Interactive multi-select picker for skill enable/disable.

    Returns a list of booleans (per-skill enabled state), or None if cancelled.
    disable-model-invocation skills are shown but not toggleable.
    """
    if not skills:
        return None

    if sys.stdin.isatty():
        return _pick_interactive(skills, console)
    return _pick_fallback(skills, console)


def _pick_interactive(
    skills: list["SkillInfo"],
    console: "Console",
) -> Optional[list[bool]]:
    """Interactive picker with checkboxes using arrow keys."""
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    checked = [s.enabled for s in skills]
    selected = 0
    scroll_offset = 0

    term_height = console.size.height
    panel_width = min(console.size.width - 2, 90)
    viewport_height = min(len(skills), max(3, term_height // 2 - 6))

    def _panel() -> "Panel":
        return _build_panel(
            skills, selected, checked, viewport_height, scroll_offset, panel_width,
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
                selected = min(len(skills) - 1, selected + 1)
            elif key in (" ", "space"):
                # Only toggle non-manual-only skills
                if not skills[selected].disable_model_invocation:
                    checked[selected] = not checked[selected]
            elif key in ("a", "A"):
                # Toggle all toggleable skills
                toggleable_checked = [
                    checked[i] for i in range(len(skills))
                    if not skills[i].disable_model_invocation
                ]
                new_state = not all(toggleable_checked)
                for i in range(len(skills)):
                    if not skills[i].disable_model_invocation:
                        checked[i] = new_state
            elif key == "enter":
                return checked
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
    skills: list["SkillInfo"],
    console: "Console",
) -> Optional[list[bool]]:
    """Fallback text picker for non-TTY environments."""
    console.print()
    console.print(f"  Skills ({len(skills)}):", style="bold")
    console.print()
    for idx, skill in enumerate(skills, 1):
        state = "\u2611" if skill.enabled else "\u2610"
        if skill.disable_model_invocation:
            state = "\u2298"
        tag = " [manual only]" if skill.disable_model_invocation else ""
        console.print(
            f"  [bold]{idx:>3}[/bold]  {state} [cyan]{skill.name}[/cyan]  "
            f"[dim]{skill.source}[/dim]  {skill.description}{tag}"
        )

    console.print()
    console.print("  [dim]Enter numbers to toggle (e.g. 1,3), 'a' for all, q to cancel[/dim]")

    checked = [s.enabled for s in skills]
    while True:
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None

        if choice.lower() == "a":
            toggleable = [
                i for i in range(len(skills))
                if not skills[i].disable_model_invocation
            ]
            all_on = all(checked[i] for i in toggleable)
            for i in toggleable:
                checked[i] = not all_on
            return checked

        try:
            nums = [int(x.strip()) for x in choice.split(",")]
        except ValueError:
            console.print("  [bold red]\u2717 Enter numbers separated by commas[/bold red]")
            continue

        if any(n < 1 or n > len(skills) for n in nums):
            console.print(f"  [bold red]\u2717 Please enter 1-{len(skills)}[/bold red]")
            continue

        for n in nums:
            i = n - 1
            if not skills[i].disable_model_invocation:
                checked[i] = not checked[i]
        return checked
