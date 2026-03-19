"""UI confirmation prompt mock — hybrid cursor + shortcut key edition.

Standalone preview of all Hooty interactive prompt patterns.  Each selector
supports BOTH arrow-key cursor movement (↑↓ + Enter) AND shortcut keys for
instant selection:

  - Hotkey+cursor:  ↑↓ + Enter  or  y/n/a/q  — operation confirm, mode switch
  - Number+cursor:  ↑↓ + Enter  or  1-9      — multiple-choice ask-user
  - Free input:     Panel frame + input() + Enter — open-ended ask-user

Run in a terminal for full interactive mode, or pipe input for the non-TTY
fallback.

Source prompts:
  - Operation confirmation: src/hooty/tools/confirm.py:59-61
  - Mode switch:            src/hooty/repl.py:907-908
  - Ask user:               src/hooty/tools/ask_user_tools.py:32-38

Cursor-select / keystroke reader copied from:
  - src/hooty/ui.py  (_read_key, Panel+Table, ANSI redraw)
"""

from __future__ import annotations

import sys
from io import StringIO

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

# Inline copy of HOOTY_THEME (src/hooty/repl.py:187-203)
HOOTY_THEME = Theme(
    {
        "banner.owl": "bright_white",
        "banner.eye": "bold #E6C200",
        "banner.version": "cyan",
        "banner.info": "dim",
        "prompt": "bold white",
        "tool_call": "yellow",
        "response": "green",
        "error": "bold red",
        "warning": "yellow",
        "success": "green",
        "session_id": "magenta",
        "slash_cmd": "cyan",
        "slash_desc": "dim",
    }
)

console = Console(theme=HOOTY_THEME)


# ---------------------------------------------------------------------------
# Keystroke reader (copied from src/hooty/session_picker.py:17-67)
# ---------------------------------------------------------------------------

def _read_key() -> str:
    """Read a single keypress and return a normalized name.

    Returns one of: 'up', 'down', 'enter', 'escape', 'ctrl-c', or the
    raw character for anything else.
    """
    try:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            ch = sys.stdin.read(1)
            if ch == "\x1b":
                ch2 = sys.stdin.read(1)
                if ch2 == "[":
                    ch3 = sys.stdin.read(1)
                    if ch3 == "A":
                        return "up"
                    if ch3 == "B":
                        return "down"
                    if ch3 == "C":
                        return "right"
                    if ch3 == "D":
                        return "left"
                    if ch3 == "H":
                        return "home"
                    if ch3 == "F":
                        return "end"
                    # Longer CSI: \x1b[3~ (Delete), \x1b[5~ (PgUp), etc.
                    # Consume remaining bytes then map known sequences.
                    if ch3.isdigit():
                        seq = ch3
                        while True:
                            trail = sys.stdin.read(1)
                            if not trail.isdigit() and trail != ";":
                                break
                            seq += trail
                        if trail == "~":
                            if seq == "3":
                                return "delete"
                            if seq in ("1", "7"):
                                return "home"
                            if seq in ("4", "8"):
                                return "end"
                    return ""
                return "escape"
            if ch in ("\r", "\n"):
                return "enter"
            if ch == "\x03":
                return "ctrl-c"
            return ch
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except ImportError:
        # Windows
        import msvcrt

        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            ch2 = msvcrt.getwch()
            if ch2 == "H":
                return "up"
            if ch2 == "P":
                return "down"
            if ch2 == "M":
                return "right"
            if ch2 == "K":
                return "left"
            if ch2 == "S":
                return "delete"
            if ch2 == "G":
                return "home"
            if ch2 == "O":
                return "end"
            return ""
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            return "escape"
        if ch == "\x03":
            return "ctrl-c"
        return ch


# ---------------------------------------------------------------------------
# Panel builders
# ---------------------------------------------------------------------------

def _new_table() -> Table:
    """Create a borderless single-column Table for panel content."""
    table = Table(
        show_header=False,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=None,
        expand=True,
    )
    table.add_column(no_wrap=True, overflow="ellipsis")
    return table


def _hotkey_row(
    key_char: str, rest: str, *, selected: bool, border_style: str,
) -> str:
    """Format a hotkey option row with the shortcut letter color-highlighted.

    Selected:     ``❯ Yes``  — Y in bold border_style, es in bold white
    Non-selected: ``  Yes``  — Y in border_style, es in dim
    """
    if selected:
        return (
            f"    [bold {border_style}]❯ {key_char}[/bold {border_style}]"
            f"[bold]{rest}[/bold]"
        )
    return (
        f"    [{border_style}]  {key_char}[/{border_style}]"
        f"[dim]{rest}[/dim]"
    )


def _build_hotkey_panel(
    options: list[tuple[str, str]],
    *,
    selected: int,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    width: int = 60,
) -> Panel:
    """Panel with hotkey options and a cursor marker on the selected row.

    The shortcut letter in each label is color-highlighted (not bracketed).
    """
    from rich.console import Group
    from rich.padding import Padding

    table = _new_table()
    table.add_row(Text())

    for i, (key, label) in enumerate(options):
        # Split label into highlighted first char + rest
        row = Text.from_markup(
            _hotkey_row(label[0], label[1:], selected=i == selected, border_style=border_style)
        )
        table.add_row(row)

    keys_hint = "/".join(k.lower() for k, _ in options)
    table.add_row(Text())
    table.add_row(
        Text.from_markup(f"    [dim]↑↓ move  Enter select  {keys_hint} shortcut  Esc cancel[/dim]")
    )

    if subtitle:
        body: Table | Group = Group(Padding(Text(subtitle), (1, 2, 0, 4)), table)
    else:
        body = table

    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=border_style,
        width=width,
    )


def _build_number_panel(
    options: list[str],
    *,
    selected: int,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    width: int = 60,
) -> Panel:
    """Panel with numbered options and a cursor marker on the selected row.

    The number is color-highlighted as the shortcut key.
    """
    from rich.console import Group
    from rich.padding import Padding

    table = _new_table()
    table.add_row(Text())

    for i, option in enumerate(options):
        num = i + 1
        if i == selected:
            row = Text.from_markup(
                f"    [bold {border_style}]❯ {num}.[/bold {border_style}]"
                f"[bold] {option}[/bold]"
            )
        else:
            row = Text.from_markup(
                f"    [{border_style}]  {num}.[/{border_style}]"
                f"[dim] {option}[/dim]"
            )
        table.add_row(row)

    hint = f"1-{len(options)}" if len(options) > 1 else "1"
    table.add_row(Text())
    table.add_row(
        Text.from_markup(f"    [dim]↑↓ move  Enter select  {hint} shortcut  Esc cancel[/dim]")
    )

    if subtitle:
        body: Table | Group = Group(Padding(Text(subtitle), (1, 2, 0, 4)), table)
    else:
        body = table

    return Panel(
        body,
        title=title,
        title_align="left",
        border_style=border_style,
        width=width,
    )


def _build_text_input_panel(
    *,
    title: str,
    subtitle: str | None = None,
    text: str = "",
    pos: int | None = None,
    border_style: str = "cyan",
    width: int = 60,
) -> Panel:
    """Panel with a multiline-capable text input area.

    Text wraps automatically inside the panel.  ``pos`` is the cursor
    position within *text*; ``None`` for static preview (cursor at end).
    """
    from rich.console import Group
    from rich.padding import Padding

    parts: list = []
    if subtitle:
        parts.append(Padding(Text(subtitle), (1, 2, 0, 4)))

    # Build input text with cursor highlight
    input_text = Text()
    if pos is None:
        input_text.append(text)
        input_text.append("\u2588", style="dim")
    elif pos < len(text):
        input_text.append(text[:pos])
        input_text.append(text[pos], style="reverse")
        input_text.append(text[pos + 1 :])
    else:
        input_text.append(text)
        input_text.append("\u2588", style="dim")

    hint = Text(
        "\u2190\u2192 move  BS del  Enter submit  Esc cancel",
        style="dim",
    )

    parts.append(Padding(input_text, (1, 2, 0, 4)))
    parts.append(Padding(hint, (1, 2, 0, 4)))

    return Panel(
        Group(*parts),
        title=title,
        title_align="left",
        border_style=border_style,
        width=width,
    )


# ---------------------------------------------------------------------------
# Interactive selectors (hybrid: cursor ↑↓+Enter AND shortcut keys)
# ---------------------------------------------------------------------------

def _disable_echo() -> object | None:
    """Disable terminal echo+canonical mode.  Returns a restore callable."""
    try:
        import termios

        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        new_attrs = termios.tcgetattr(fd)
        new_attrs[3] &= ~(termios.ECHO | termios.ICANON)
        new_attrs[6][termios.VMIN] = 1
        new_attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
        return lambda: termios.tcsetattr(  # noqa: E731
            fd, termios.TCSADRAIN, old_attrs
        )
    except (ImportError, OSError, TypeError, ValueError):
        return None


def _measure_height(panel: Panel, width: int) -> int:
    """Measure rendered line count of a panel using an off-screen Console."""
    buf = Console(width=width, file=StringIO(), force_terminal=True)
    buf.print(panel)
    return buf.file.getvalue().count("\n")


def hotkey_select(
    options: list[tuple[str, str]],
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
) -> str | None:
    """Hybrid selector: ↑↓+Enter cursor OR hotkey instant select.

    Returns the matched key string (e.g. 'Y') or None on cancel.
    """
    if not sys.stdin.isatty():
        return _hotkey_fallback(options, title=title, subtitle=subtitle, con=con)

    selected = 0
    panel_width = min(con.size.width - 2, 60)
    valid_keys = {k.lower(): i for i, (k, _) in enumerate(options)}

    def _panel() -> Panel:
        return _build_hotkey_panel(
            options, selected=selected, title=title,
            subtitle=subtitle, border_style=border_style, width=panel_width,
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
                selected = min(len(options) - 1, selected + 1)
            elif key == "enter":
                return options[selected][0]
            elif key.lower() in valid_keys:
                return options[valid_keys[key.lower()]][0]
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                continue

            # Redraw panel at same position
            con.file.write(f"\033[{move_up}A\033[J")
            con.file.flush()
            con.print(_panel())
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()


def _hotkey_fallback(
    options: list[tuple[str, str]],
    *,
    title: str,
    subtitle: str | None = None,
    con: Console,
) -> str | None:
    """Non-TTY fallback for hotkey_select."""
    con.print()
    con.print(f"  {title}", style="bold")
    if subtitle:
        con.print(f"  {subtitle}")
    con.print()
    keys_display = []
    for key, label in options:
        con.print(f"    [bold]{label[0]}[/bold]{label[1:]}")
        keys_display.append(key)
    con.print()
    hint = "/".join(keys_display)
    con.print(f"  [dim]Enter key ({hint}) to select, q to cancel[/dim]")

    valid_keys = {k.lower(): k for k, _ in options}
    while True:
        try:
            choice = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            con.print()
            return None
        if not choice or choice.lower() == "q":
            if "q" in valid_keys:
                return valid_keys["q"]
            return None
        if choice.lower() in valid_keys:
            return valid_keys[choice.lower()]
        con.print(f"  [bold red]✗ Please enter one of: {hint}[/bold red]")


def number_select(
    options: list[str],
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
) -> int | None:
    """Hybrid selector: ↑↓+Enter cursor OR number-key instant select.

    Returns 0-based index or None on cancel.
    """
    if not sys.stdin.isatty():
        return _number_fallback(options, title=title, subtitle=subtitle, con=con)

    selected = 0
    panel_width = min(con.size.width - 2, 60)
    num_keys = {str(i + 1): i for i in range(len(options))}

    def _panel() -> Panel:
        return _build_number_panel(
            options, selected=selected, title=title,
            subtitle=subtitle, border_style=border_style, width=panel_width,
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
                selected = min(len(options) - 1, selected + 1)
            elif key == "enter":
                return selected
            elif key in num_keys:
                return num_keys[key]
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                continue

            # Redraw panel at same position
            con.file.write(f"\033[{move_up}A\033[J")
            con.file.flush()
            con.print(_panel())
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()


def _number_fallback(
    options: list[str],
    *,
    title: str,
    subtitle: str | None = None,
    con: Console,
) -> int | None:
    """Non-TTY fallback for number_select."""
    con.print()
    con.print(f"  {title}", style="bold")
    if subtitle:
        con.print(f"  {subtitle}")
    con.print()
    for i, option in enumerate(options, 1):
        con.print(f"    {i}. {option}")
    con.print()
    con.print(f"  [dim]Enter number (1-{len(options)}) to select, q to cancel[/dim]")

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
        if num < 1 or num > len(options):
            con.print(f"  [bold red]✗ Please enter 1-{len(options)}[/bold red]")
            continue
        return num - 1


def text_input(
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
) -> str | None:
    """In-panel multiline text input with cursor movement.

    Text wraps automatically inside the panel.  Supports left/right
    arrow, Home/End, Backspace, Delete.  The panel height adjusts
    dynamically as text grows or shrinks.
    """
    if not sys.stdin.isatty():
        return _text_input_fallback(title=title, subtitle=subtitle, con=con)

    text = ""
    pos = 0
    panel_width = min(con.size.width - 2, 60)

    def _panel() -> Panel:
        return _build_text_input_panel(
            title=title, subtitle=subtitle, text=text, pos=pos,
            border_style=border_style, width=panel_width,
        )

    p = _panel()
    prev_height = _measure_height(p, panel_width)
    restore = _disable_echo()
    con.print(p)

    try:
        while True:
            key = _read_key()
            if key == "enter":
                return text.strip()
            if key in ("escape", "ctrl-c"):
                return None
            if key == "left":
                pos = max(0, pos - 1)
            elif key == "right":
                pos = min(len(text), pos + 1)
            elif key == "home":
                pos = 0
            elif key == "end":
                pos = len(text)
            elif key in ("\x7f", "\x08"):  # backspace
                if pos > 0:
                    text = text[: pos - 1] + text[pos:]
                    pos -= 1
            elif key == "delete":
                if pos < len(text):
                    text = text[:pos] + text[pos + 1 :]
            elif len(key) == 1 and key.isprintable():
                text = text[:pos] + key + text[pos:]
                pos += 1
            else:
                continue

            # Erase previous frame, print new one (height may differ)
            con.file.write(f"\033[{prev_height}A\033[J")
            con.file.flush()
            p = _panel()
            prev_height = _measure_height(p, panel_width)
            con.print(p)
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()


def _text_input_fallback(
    *,
    title: str,
    subtitle: str | None = None,
    con: Console,
) -> str | None:
    """Non-TTY fallback for text_input."""
    con.print()
    con.print(f"  {title}", style="bold")
    if subtitle:
        con.print(f"  {subtitle}")
    con.print()
    try:
        answer = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        con.print()
        return None
    return answer if answer else None


# ---------------------------------------------------------------------------
# Section 1: Operation Confirmation  (hotkey: Y / N / A / Q + cursor)
# ---------------------------------------------------------------------------

CONFIRM_HOTKEYS: list[tuple[str, str]] = [
    ("Y", "Yes, approve this action."),
    ("N", "No, reject this action."),
    ("A", "All, approve remaining actions."),
    ("Q", "Quit, cancel execution."),
]
CONFIRM_RESULTS: dict[str | None, str] = {
    "Y": "Approved",
    "N": "Rejected",
    "A": "Approved all (remaining actions auto-approved)",
    "Q": "Cancelled (KeyboardInterrupt in production)",
    None: "Cancelled",
}


def section_confirm() -> None:
    console.print()
    console.rule("[bold]Section 1: Operation Confirmation[/bold]")
    console.print()
    console.print(
        "  Source: [dim]src/hooty/tools/confirm.py:59-61[/dim]  "
        "[yellow]⚠[/yellow] cursor + hotkey [Y]/[N]/[A]/[Q]"
    )

    # Static previews
    static_previews = [
        ("⚠  Write File", "src/hooty/config.py"),
        ("⚠  Shell", 'uv run pytest -m "not integration"'),
        ("⚠  Execute Plan", "Add retry logic to provider factory"),
    ]
    console.print()
    console.print("  [bold]Static previews:[/bold]")
    pw = min(console.size.width - 4, 60)
    for t, sub in static_previews:
        console.print()
        console.print(
            _build_hotkey_panel(
                CONFIRM_HOTKEYS,
                selected=0,
                title=t,
                subtitle=sub,
                border_style="yellow",
                width=pw,
            )
        )

    # Interactive trial
    console.print()
    console.print("  [bold]Interactive trial:[/bold]")
    key = hotkey_select(
        CONFIRM_HOTKEYS,
        title="⚠  Edit File",
        subtitle="src/hooty/repl.py",
        border_style="yellow",
        con=console,
    )
    console.print(f"  → Result: [bold]{CONFIRM_RESULTS.get(key, 'Cancelled')}[/bold]")


# ---------------------------------------------------------------------------
# Section 2: Mode Switch  (hotkey: Y / N + cursor)
# ---------------------------------------------------------------------------

MODE_HOTKEYS: list[tuple[str, str]] = [
    ("Y", "Yes, switch to coding"),
    ("N", "No, stay in planning"),
]
MODE_RESULTS: dict[str | None, str] = {
    "Y": "\033[32m✓ Switched to CODING mode\033[0m",
    "N": "Staying in PLANNING mode",
    None: "Staying in PLANNING mode (cancelled)",
}


def section_mode_switch() -> None:
    console.print()
    console.rule("[bold]Section 2: Mode Switch (Plan → Coding)[/bold]")
    console.print()
    console.print(
        "  Source: [dim]src/hooty/repl.py:907-908[/dim]  "
        "[cyan]●[/cyan] cursor + hotkey [Y]/[N]"
    )

    # Static preview
    console.print()
    console.print("  [bold]Static preview:[/bold]")
    pw = min(console.size.width - 4, 60)
    console.print()
    console.print(
        _build_hotkey_panel(
            MODE_HOTKEYS,
            selected=0,
            title="● Switch to coding mode?",
            border_style="cyan",
            width=pw,
        )
    )

    # Interactive trial
    console.print()
    console.print("  [bold]Interactive trial:[/bold]")
    key = hotkey_select(
        MODE_HOTKEYS,
        title="● Switch to coding mode?",
        border_style="cyan",
        con=console,
    )
    console.print(f"  → Result: [bold]{MODE_RESULTS.get(key, MODE_RESULTS[None])}[/bold]")


# ---------------------------------------------------------------------------
# Section 3: Ask User
# ---------------------------------------------------------------------------

def section_ask_user() -> None:
    console.print()
    console.rule("[bold]Section 3: Ask User[/bold]")
    console.print()
    console.print(
        "  Source: [dim]src/hooty/tools/ask_user_tools.py:32-38[/dim]  "
        "[cyan]❓[/cyan] icon + question"
    )

    pw = min(console.size.width - 4, 60)

    # --- 3a: With choices (cursor + number key) ---
    console.print()
    console.print("  [bold]3a. With choices (cursor + number key):[/bold]")

    question_3a = "Which test framework do you prefer?"
    choices_3a = ["pytest", "unittest", "nose2", "(type custom answer)"]

    # Static preview
    console.print()
    console.print("  [bold]Static preview:[/bold]")
    console.print()
    console.print(
        _build_number_panel(
            choices_3a,
            selected=0,
            title="❓ Question for you",
            subtitle=question_3a,
            border_style="cyan",
            width=pw,
        )
    )

    # Interactive trial
    console.print()
    console.print("  [bold]Interactive trial:[/bold]")
    idx = number_select(
        choices_3a,
        title="❓ Question for you",
        subtitle=question_3a,
        border_style="cyan",
        con=console,
    )
    if idx is not None and idx == len(choices_3a) - 1:
        # Last option → in-panel free-form input
        answer = text_input(
            title="❓ Question for you",
            subtitle=f"{question_3a} (custom)",
            border_style="cyan",
            con=console,
        )
        if answer is None or answer == "":
            answer = "(no response)"
        console.print(f"  → Answer: [bold]{answer}[/bold]")
    elif idx is not None:
        console.print(f"  → Answer: [bold]{choices_3a[idx]}[/bold]")
    else:
        console.print("  → Answer: [bold](cancelled)[/bold]")

    # --- 3b: Free input (in-panel text input) ---
    console.print()
    console.print("  [bold]3b. Free input (in-panel text input):[/bold]")

    question_3b = "What should the new module be named?"

    # Static preview (show with example text)
    console.print()
    console.print("  [bold]Static preview:[/bold]")
    console.print()
    console.print(
        _build_text_input_panel(
            title="❓ Question for you",
            subtitle=question_3b,
            text="my_utils",
            border_style="cyan",
            width=pw,
        )
    )

    # Interactive trial
    console.print()
    console.print("  [bold]Interactive trial:[/bold]")
    answer = text_input(
        title="❓ Question for you",
        subtitle=question_3b,
        border_style="cyan",
        con=console,
    )
    if answer is None or answer == "":
        answer = "(no response)"
    console.print(f"  → Answer: [bold]{answer}[/bold]")


# ---------------------------------------------------------------------------
# Footer: Legend
# ---------------------------------------------------------------------------

def footer() -> None:
    console.print()
    console.rule("[bold]Legend[/bold]")
    console.print()
    console.print(
        "  [yellow]⚠[/yellow]  Operation confirmation  "
        "[dim]→ ↑↓+Enter or Y/N/A/Q  src/hooty/tools/confirm.py[/dim]"
    )
    console.print(
        "  [cyan]●[/cyan]  Mode switch              "
        "[dim]→ ↑↓+Enter or Y/N      src/hooty/repl.py[/dim]"
    )
    console.print(
        "  [cyan]❓[/cyan] Ask user (choices)        "
        "[dim]→ ↑↓+Enter or 1-N      src/hooty/tools/ask_user_tools.py[/dim]"
    )
    console.print(
        "  [cyan]❓[/cyan] Ask user (free input)     "
        "[dim]→ in-panel text input     src/hooty/tools/ask_user_tools.py[/dim]"
    )
    console.print()
    console.print(
        "  [dim]Non-TTY: text-based fallback (pipe-friendly)[/dim]"
    )
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    console.print()
    console.print(
        Panel.fit(
            "[bold]Hooty UI Confirmation Prompt Mock[/bold]\n"
            "[dim]Hybrid: cursor ↑↓ + shortcut keys[/dim]",
            border_style="cyan",
        )
    )

    section_confirm()
    section_mode_switch()
    section_ask_user()
    footer()
