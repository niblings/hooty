"""Interactive model profile picker for /model command."""

from __future__ import annotations

import sys
import time
from typing import TYPE_CHECKING, Optional

from hooty.ui import _disable_echo, _read_key

if TYPE_CHECKING:
    from rich.console import Console
    from rich.panel import Panel

    from hooty.config import AppConfig


def _format_row(
    name: str,
    provider: str,
    model_id: str,
    *,
    is_active: bool,
    is_default: bool,
    selected: bool,
) -> str:
    """Format a single profile row."""
    marker = "\u2611" if is_active else " "  # ☑ for active
    default_label = " (default)" if is_default else ""
    cursor = "\u25b8" if selected else " "  # ▸ for cursor

    if selected:
        return (
            f"  [bold]{cursor} {marker} {name}{default_label}"
            f"  {provider} / {model_id}[/bold]"
        )
    return (
        f"  {cursor} {marker} {name}[dim]{default_label}"
        f"  {provider} / {model_id}[/dim]"
    )


def _build_panel(
    profile_names: list[str],
    config: "AppConfig",
    default_profile: str,
    selected: int,
    width: int = 60,
    *,
    active_override: str | None = None,
) -> "Panel":
    """Build a Panel showing available profiles.

    Args:
        active_override: If set, show ☑ on this profile instead of config.active_profile.
    """
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

    active_name = active_override if active_override is not None else config.active_profile

    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=None,
        expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")
    table.add_row(Text())

    for i, name in enumerate(profile_names):
        prof = config.profiles[name]
        row = Text.from_markup(
            _format_row(
                name,
                prof.provider.value,
                prof.model_id,
                is_active=name == active_name,
                is_default=name == default_profile,
                selected=i == selected,
            )
        )
        table.add_row(row)

    table.add_row(Text())
    table.add_row(
        Text.from_markup("  [dim]\u2191\u2193 move  Enter select  Esc cancel[/dim]")
    )

    return Panel(
        table,
        title=f"Model profiles ({len(profile_names)})",
        title_align="left",
        border_style="cyan",
        width=width,
    )


def _pick_interactive(
    profile_names: list[str],
    config: "AppConfig",
    default_profile: str,
    console: "Console",
) -> Optional[str]:
    """Interactive picker using arrow keys."""
    from io import StringIO

    from rich.console import Console as _MeasureConsole

    selected = 0
    # Start on the active profile if possible
    if config.active_profile in profile_names:
        selected = profile_names.index(config.active_profile)

    panel_width = min(console.size.width - 2, 70)
    result: str | None = None

    def _panel(active_override: str | None = None) -> "Panel":
        return _build_panel(
            profile_names, config, default_profile, selected, panel_width,
            active_override=active_override,
        )

    # Measure rendered height
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
                selected = min(len(profile_names) - 1, selected + 1)
            elif key == "enter":
                result = profile_names[selected]
            elif key in ("q", "Q", "escape", "ctrl-c"):
                return None
            else:
                continue

            # Redraw panel (show ☑ on chosen profile when confirmed)
            console.file.write(f"\033[{move_up}A\033[J")
            console.file.flush()
            console.print(_panel(active_override=result))

            if result is not None:
                time.sleep(0.08)
                return result
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()


def _pick_fallback(
    profile_names: list[str],
    config: "AppConfig",
    default_profile: str,
    console: "Console",
) -> Optional[str]:
    """Fallback picker for non-TTY environments."""
    console.print()
    console.print(f"  Model profiles ({len(profile_names)}):", style="bold")
    console.print()
    for idx, name in enumerate(profile_names, 1):
        prof = config.profiles[name]
        active_mark = " \u2611" if name == config.active_profile else ""
        default_mark = " (default)" if name == default_profile else ""
        console.print(
            f"  {idx:>3}  {name}{default_mark}{active_mark}"
            f"  [dim]{prof.provider.value} / {prof.model_id}[/dim]"
        )
    console.print()
    console.print("  [dim]Enter number to select, q to cancel[/dim]")

    while True:
        try:
            choice = input("  > ").strip()
        except (KeyboardInterrupt, EOFError):
            console.print()
            return None

        if not choice or choice.lower() == "q":
            return None

        try:
            num = int(choice)
        except ValueError:
            console.print("  [bold red]\u2717 Please enter a number[/bold red]")
            continue

        if num < 1 or num > len(profile_names):
            console.print(f"  [bold red]\u2717 Please enter 1-{len(profile_names)}[/bold red]")
            continue

        return profile_names[num - 1]


def pick_profile(config: "AppConfig", console: "Console") -> Optional[str]:
    """Interactive profile picker. Returns profile name or None on cancel."""
    if not config.profiles:
        console.print("  [dim]No profiles defined in config.yaml.[/dim]")
        return None

    profile_names = list(config.profiles.keys())

    # Use the startup-time default (frozen in load_config), not active_profile
    # which changes on /model switch.
    default_profile = config.default_profile

    if sys.stdin.isatty():
        return _pick_interactive(profile_names, config, default_profile, console)
    return _pick_fallback(profile_names, config, default_profile, console)
