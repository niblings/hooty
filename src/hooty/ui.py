"""Shared UI primitives — interactive selectors for Hooty REPL.

Provides hotkey-select, number-select and free text-input widgets built on
Rich Panel + ANSI cursor redraw.  Each widget supports both TTY mode (arrow
keys + shortcut keys) and a non-TTY fallback (plain text input).
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from io import StringIO
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Shared reference set by REPL.__init__ so tools can access the console.
_active_console: list[Console | None] = [None]


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _read_key() -> str:
    """Read a single keypress and return a normalized name.

    Returns one of: 'up', 'down', 'left', 'right', 'enter', 'home', 'end',
    'delete', 'escape', 'ctrl-c', 'tab', 'shift-tab', 'space', 'alt-enter',
    'paste:<text>' for bracketed paste, or the raw character for anything else.
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
                    if ch3 == "Z":
                        return "shift-tab"
                    # Longer CSI: \x1b[3~ (Delete), \x1b[5~ (PgUp), etc.
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
                            # Bracketed paste start: \x1b[200~
                            if seq == "200":
                                return "paste:" + _read_bracketed_paste(fd)
                    return ""
                if ch2 in ("\r", "\n"):
                    return "alt-enter"
                return "escape"
            if ch == "\t":
                return "tab"
            if ch in ("\r", "\n"):
                return "enter"
            if ch == "\x03":
                return "ctrl-c"
            if ch == " ":
                return "space"
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
        if ch == "\t":
            return "tab"
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x1b":
            return "escape"
        if ch == "\x03":
            return "ctrl-c"
        if ch == " ":
            return "space"
        return ch


def _enable_bracketed_paste() -> Callable[[], None] | None:
    """Enable bracketed paste mode.  Returns a callable to disable it."""
    try:
        sys.stdout.write("\x1b[?2004h")
        sys.stdout.flush()
        return lambda: (sys.stdout.write("\x1b[?2004l"), sys.stdout.flush())
    except OSError:
        return None


def _read_bracketed_paste(fd: int) -> str:
    """Read pasted text until the bracketed paste end sequence \\x1b[201~.

    Must be called in raw mode right after \\x1b[200~ has been consumed.
    """
    chars: list[str] = []
    while True:
        ch = sys.stdin.read(1)
        if ch == "\x1b":
            # Potential paste-end sequence \x1b[201~
            ch2 = sys.stdin.read(1)
            if ch2 == "[":
                seq = ""
                while True:
                    trail = sys.stdin.read(1)
                    if trail.isdigit() or trail == ";":
                        seq += trail
                    else:
                        break
                if seq == "201" and trail == "~":
                    break
                # Not paste-end; discard consumed escape sequence
            continue
        # Filter to printable characters only
        if len(ch) == 1 and (ch.isprintable() or ch in ("\r", "\n")):
            if ch not in ("\r", "\n"):
                chars.append(ch)
    return "".join(chars)


def _disable_echo() -> Callable[[], None] | None:
    """Disable terminal echo+canonical mode and hide cursor. Returns a restore callable."""
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

        def _restore() -> None:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)
            # Show cursor
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()

        return _restore
    except (ImportError, OSError, TypeError, ValueError):
        return None


def _drain_printable() -> str:
    """Read all immediately available printable chars from stdin.

    Used after inserting the first character from a paste operation so that
    the remaining buffered characters are consumed in one batch instead of
    being re-drawn one-by-one (which can lose characters on fast paste).

    Line endings (``\\r``/``\\n``) embedded in pasted text are silently
    skipped so that they do not prematurely terminate the input field.
    """
    try:
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            chars: list[str] = []
            while select.select([fd], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                if ch == "\x1b":
                    # Skip escape sequences (e.g. bracketed paste end \x1b[201~)
                    while select.select([fd], [], [], 0)[0]:
                        trail = sys.stdin.read(1)
                        if not trail.isdigit() and trail not in ("[", ";"):
                            break
                    continue
                # Skip line endings from pasted text
                if ch in ("\r", "\n"):
                    continue
                if len(ch) == 1 and ch.isprintable():
                    chars.append(ch)
                else:
                    break
            return "".join(chars)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    except (ImportError, OSError):
        # Windows: use msvcrt to batch-read buffered input
        try:
            import msvcrt

            chars_w: list[str] = []
            while msvcrt.kbhit():
                ch = msvcrt.getwch()
                # Extended key prefix — consume the second byte and skip
                if ch in ("\x00", "\xe0"):
                    if msvcrt.kbhit():
                        msvcrt.getwch()
                    continue
                # Skip escape and line endings (common in pasted text)
                if ch in ("\x1b", "\r", "\n"):
                    continue
                if len(ch) == 1 and ch.isprintable():
                    chars_w.append(ch)
                else:
                    break
            return "".join(chars_w)
        except ImportError:
            return ""


def _measure_height(panel: Panel, width: int) -> int:
    """Measure rendered line count of a panel using an off-screen Console."""
    buf = Console(width=width, file=StringIO(), force_terminal=True)
    buf.print(panel)
    return buf.file.getvalue().count("\n")


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
    """Format a hotkey option row with the shortcut letter color-highlighted."""
    if selected:
        return (
            f"    [bold {border_style}]\u276f {key_char}[/bold {border_style}]"
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
    """Panel with hotkey options and a cursor marker on the selected row."""
    from rich.console import Group
    from rich.padding import Padding

    table = _new_table()
    table.add_row(Text())

    for i, (_key, label) in enumerate(options):
        row = Text.from_markup(
            _hotkey_row(label[0], label[1:], selected=i == selected, border_style=border_style)
        )
        table.add_row(row)

    keys_hint = "/".join(k.lower() for k, _ in options)
    table.add_row(Text())
    table.add_row(
        Text.from_markup(f"    [dim]\u2191\u2193 move  Enter select  {keys_hint} shortcut  Esc cancel[/dim]")
    )

    if subtitle and subtitle.strip():
        from rich.markdown import Markdown

        body: Table | Group = Group(Padding(Markdown(subtitle), (1, 2, 0, 4)), table)
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
    allow_other: bool = False,
    other_text: str = "",
    other_pos: int = 0,
    other_focus: bool = False,
) -> Panel:
    """Panel with numbered options and a cursor marker on the selected row.

    When *allow_other* is True an additional "Other: …" row is appended after
    the numbered options, allowing the user to type a free-form answer.
    """
    from rich.console import Group
    from rich.padding import Padding

    table = _new_table()
    table.add_row(Text())

    for i, option in enumerate(options):
        num = i + 1
        if i == selected and not other_focus:
            row = Text.from_markup(
                f"    [bold {border_style}]\u276f {num}.[/bold {border_style}]"
                f"[bold] {option}[/bold]"
            )
        else:
            row = Text.from_markup(
                f"    [{border_style}]  {num}.[/{border_style}]"
                f"[dim] {option}[/dim]"
            )
        table.add_row(row)

    # Other row
    if allow_other:
        other_idx = len(options)
        is_other_cursor = (selected == other_idx)
        other_display = Text()
        if is_other_cursor and other_focus:
            other_display.append_text(Text.from_markup(
                f"    [bold {border_style}]\u276f[/bold {border_style}]"
                f" [bold]Other:[/bold] "
            ))
            other_display.append_text(_render_text_with_cursor(
                other_text, other_pos, indent=13,
            ))
        elif is_other_cursor:
            other_display = Text.from_markup(
                f"    [bold {border_style}]\u276f[/bold {border_style}]"
                f" [bold]Other:[/bold] "
                f"{'[dim]' + other_text + '[/dim]' if other_text else '[dim]\u2588[/dim]'}"
            )
        else:
            other_display = Text.from_markup(
                f"    [{border_style}] [/{border_style}]"
                f" [dim]Other: type to enter...[/dim]"
            )
        table.add_row(other_display)

    hint = f"1-{len(options)}" if len(options) > 1 else "1"
    table.add_row(Text())
    hints = ["\u2191\u2193 move", "Enter select", f"{hint} shortcut"]
    if allow_other:
        hints.append("type to enter Other")
    hints.append("Esc cancel")
    table.add_row(
        Text.from_markup(f"    [dim]{'  '.join(hints)}[/dim]")
    )

    if subtitle and subtitle.strip():
        from rich.markdown import Markdown

        body: Table | Group = Group(Padding(Markdown(subtitle), (1, 2, 0, 4)), table)
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
    mask: str | None = None,
    border_style: str = "cyan",
    width: int = 60,
) -> Panel:
    """Panel with a text input area and cursor indicator."""
    from rich.console import Group
    from rich.padding import Padding

    parts: list = []
    if subtitle and subtitle.strip():
        from rich.markdown import Markdown

        parts.append(Padding(Markdown(subtitle), (1, 2, 0, 4)))

    display = (mask * len(text)) if mask else text

    input_text = Text()
    if pos is None:
        input_text.append(display)
        input_text.append("\u2588", style="dim")
    elif pos < len(display):
        input_text.append(display[:pos])
        input_text.append(display[pos], style="reverse")
        input_text.append(display[pos + 1:])
    else:
        input_text.append(display)
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
# Interactive selectors
# ---------------------------------------------------------------------------

def hotkey_select(
    options: list[tuple[str, str]],
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
    max_width: int = 60,
) -> str | None:
    """Hybrid selector: arrow-keys + Enter OR hotkey instant select.

    Returns the matched key string (e.g. 'Y') or None on cancel.
    """
    if not sys.stdin.isatty():
        return _hotkey_fallback(options, title=title, subtitle=subtitle, con=con)

    selected = 0
    panel_width = min(con.size.width - 2, max_width)
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
            result: str | None = None
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(len(options) - 1, selected + 1)
            elif key == "enter":
                result = options[selected][0]
            elif key.lower() in valid_keys:
                selected = valid_keys[key.lower()]
                result = options[selected][0]
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                continue

            # Redraw panel with updated selection
            con.file.write(f"\033[{move_up}A\033[J")
            con.file.flush()
            con.print(_panel())

            if result is not None:
                time.sleep(0.08)
                return result
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
        con.print(f"  [bold red]\u2717 Please enter one of: {hint}[/bold red]")


def number_select(
    options: list[str],
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
    max_width: int = 60,
    allow_other: bool = False,
) -> int | str | None:
    """Hybrid selector: arrow-keys + Enter OR number-key instant select.

    Returns 0-based index, Other text (str) when *allow_other* is True,
    or None on cancel.
    """
    if not sys.stdin.isatty():
        return _number_fallback(
            options, title=title, subtitle=subtitle, con=con,
            allow_other=allow_other,
        )

    selected = 0
    panel_width = min(con.size.width - 2, max_width)
    num_keys = {str(i + 1): i for i in range(len(options))}
    max_sel = len(options) if allow_other else len(options) - 1

    # Other input state
    other_text = ""
    other_pos = 0
    focus = "list"  # "list" or "input"

    def _panel() -> Panel:
        return _build_number_panel(
            options, selected=selected, title=title,
            subtitle=subtitle, border_style=border_style, width=panel_width,
            allow_other=allow_other, other_text=other_text,
            other_pos=other_pos, other_focus=(focus == "input"),
        )

    move_up = _measure_height(_panel(), panel_width)
    restore = _disable_echo()
    con.print(_panel())

    def _redraw() -> None:
        nonlocal move_up
        con.file.write(f"\033[{move_up}A\033[J")
        con.file.flush()
        p = _panel()
        move_up = _measure_height(p, panel_width)
        con.print(p)

    try:
        while True:
            key = _read_key()

            # --- Other input mode ---
            if focus == "input":
                txt = other_text
                pos = other_pos

                if key == "enter":
                    if txt.strip():
                        time.sleep(0.08)
                        return txt.strip()
                    # Empty Other → stay
                    _redraw()
                    continue
                if key in ("escape", "ctrl-c"):
                    return None
                if key == "up":
                    focus = "list"
                    selected = len(options) - 1 if options else 0
                    _redraw()
                    continue

                if key == "left":
                    other_pos = max(0, pos - 1)
                elif key == "right":
                    other_pos = min(len(txt), pos + 1)
                elif key == "home":
                    other_pos = 0
                elif key == "end":
                    other_pos = len(txt)
                elif key in ("\x7f", "\x08"):
                    if pos > 0:
                        other_text = txt[:pos - 1] + txt[pos:]
                        other_pos = pos - 1
                    elif pos == 0 and len(txt) == 0:
                        focus = "list"
                elif key == "delete":
                    if pos < len(txt):
                        other_text = txt[:pos] + txt[pos + 1:]
                elif key == "space":
                    other_text = txt[:pos] + " " + txt[pos:]
                    other_pos = pos + 1
                elif key.startswith("paste:"):
                    pasted = key[6:]
                    other_text = txt[:pos] + pasted + txt[pos:]
                    other_pos = pos + len(pasted)
                elif len(key) == 1 and key.isprintable():
                    other_text = txt[:pos] + key + txt[pos:]
                    other_pos = pos + 1
                    extra = _drain_printable()
                    if extra:
                        other_text = (
                            other_text[:other_pos] + extra
                            + other_text[other_pos:]
                        )
                        other_pos += len(extra)
                else:
                    continue
                _redraw()
                continue

            # --- List navigation ---
            result: int | None = None
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                selected = min(max_sel, selected + 1)
            elif key == "enter":
                if allow_other and selected == len(options):
                    # On Other row without text → switch to input mode
                    if other_text.strip():
                        time.sleep(0.08)
                        return other_text.strip()
                    focus = "input"
                    other_pos = len(other_text)
                    _redraw()
                    continue
                result = selected
            elif key == "space":
                if allow_other and selected == len(options):
                    focus = "input"
                    other_pos = len(other_text)
                    _redraw()
                    continue
                result = selected
            elif key in num_keys:
                selected = num_keys[key]
                result = selected
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                # Printable char on Other row → switch to input
                if (
                    allow_other
                    and selected == len(options)
                    and len(key) == 1
                    and key.isprintable()
                ):
                    focus = "input"
                    other_text = key
                    other_pos = 1
                    extra = _drain_printable()
                    if extra:
                        other_text += extra
                        other_pos += len(extra)
                    _redraw()
                    continue
                continue

            # Redraw panel with updated selection
            _redraw()

            if result is not None:
                time.sleep(0.08)
                return result
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
    allow_other: bool = False,
) -> int | str | None:
    """Non-TTY fallback for number_select."""
    con.print()
    con.print(f"  {title}", style="bold")
    if subtitle:
        con.print(f"  {subtitle}")
    con.print()
    for i, option in enumerate(options, 1):
        con.print(f"    {i}. {option}")
    con.print()
    if allow_other:
        con.print(
            f"  [dim]Enter number (1-{len(options)}) to select,"
            " or type custom answer, q to cancel[/dim]"
        )
    else:
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
            if allow_other:
                return choice  # Free-text Other answer
            con.print("  [bold red]\u2717 Please enter a number[/bold red]")
            continue
        if num < 1 or num > len(options):
            if allow_other:
                return choice  # Treat out-of-range number as Other text
            con.print(f"  [bold red]\u2717 Please enter 1-{len(options)}[/bold red]")
            continue
        return num - 1


def text_input(
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
    max_width: int = 60,
) -> str | None:
    """In-panel text input with cursor movement.

    Returns the entered text (stripped) or None on cancel.
    """
    if not sys.stdin.isatty():
        return _text_input_fallback(title=title, subtitle=subtitle, con=con)

    text = ""
    pos = 0
    panel_width = min(con.size.width - 2, max_width)

    def _panel() -> Panel:
        return _build_text_input_panel(
            title=title, subtitle=subtitle, text=text, pos=pos,
            border_style=border_style, width=panel_width,
        )

    p = _panel()
    prev_height = _measure_height(p, panel_width)
    restore = _disable_echo()
    disable_paste = _enable_bracketed_paste()
    con.print(p)

    try:
        while True:
            key = _read_key()
            if key == "enter":
                return text.strip()
            if key in ("escape", "ctrl-c"):
                return None
            if key.startswith("paste:"):
                pasted = key[6:]
                text = text[:pos] + pasted + text[pos:]
                pos += len(pasted)
            elif key == "left":
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
                    text = text[:pos] + text[pos + 1:]
            elif len(key) == 1 and key.isprintable():
                text = text[:pos] + key + text[pos:]
                pos += 1
                # Batch-read remaining chars (non-bracketed paste fallback)
                batch = _drain_printable()
                if batch:
                    text = text[:pos] + batch + text[pos:]
                    pos += len(batch)
            else:
                continue

            con.file.write(f"\033[{prev_height}A\033[J")
            con.file.flush()
            p = _panel()
            prev_height = _measure_height(p, panel_width)
            con.print(p)
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if disable_paste:
            disable_paste()
        if restore:
            restore()


def password_input(
    *,
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
) -> str | None:
    """In-panel password input (characters shown as '*').

    Returns the entered text (stripped) or None on cancel.
    """
    if not sys.stdin.isatty():
        return _password_input_fallback(title=title, subtitle=subtitle, con=con)

    text = ""
    pos = 0
    panel_width = min(con.size.width - 2, 60)

    def _panel() -> Panel:
        return _build_text_input_panel(
            title=title, subtitle=subtitle, text=text, pos=pos,
            mask="*", border_style=border_style, width=panel_width,
        )

    p = _panel()
    prev_height = _measure_height(p, panel_width)
    restore = _disable_echo()
    disable_paste = _enable_bracketed_paste()
    con.print(p)

    try:
        while True:
            key = _read_key()
            if key == "enter":
                return text.strip()
            if key in ("escape", "ctrl-c"):
                return None
            if key.startswith("paste:"):
                pasted = key[6:]
                text = text[:pos] + pasted + text[pos:]
                pos += len(pasted)
            elif key == "left":
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
                    text = text[:pos] + text[pos + 1:]
            elif len(key) == 1 and key.isprintable():
                text = text[:pos] + key + text[pos:]
                pos += 1
                # Batch-read remaining chars (non-bracketed paste fallback)
                batch = _drain_printable()
                if batch:
                    text = text[:pos] + batch + text[pos:]
                    pos += len(batch)
            else:
                continue

            con.file.write(f"\033[{prev_height}A\033[J")
            con.file.flush()
            p = _panel()
            prev_height = _measure_height(p, panel_width)
            con.print(p)
    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if disable_paste:
            disable_paste()
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


def _password_input_fallback(
    *,
    title: str,
    subtitle: str | None = None,
    con: Console,
) -> str | None:
    """Non-TTY fallback for password_input."""
    import getpass as _getpass

    con.print()
    con.print(f"  {title}", style="bold")
    if subtitle:
        con.print(f"  {subtitle}")
    con.print()
    try:
        answer = _getpass.getpass("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        con.print()
        return None
    return answer if answer else None


# ---------------------------------------------------------------------------
# Text cursor rendering helper
# ---------------------------------------------------------------------------

def _render_text_with_cursor(txt: str, pos: int, *, indent: int = 0) -> Text:
    """Render text with a cursor indicator, supporting multiline (\\n).

    ``indent`` is the number of spaces to prepend to continuation lines
    (lines after the first \\n) so they align with the input start position.
    """
    indent_str = " " * indent
    display = txt.replace("\n", "\n" + indent_str)
    # Adjust pos to account for added indent chars
    nl_before = txt[:pos].count("\n")
    display_pos = pos + nl_before * indent

    result = Text()
    if display_pos < len(display):
        ch = display[display_pos]
        result.append(display[:display_pos])
        if ch == "\n":
            result.append("\u2588", style="dim")
            result.append(display[display_pos:])
        else:
            result.append(ch, style="reverse")
            result.append(display[display_pos + 1:])
    else:
        result.append(display)
        result.append("\u2588", style="dim")
    return result


# ---------------------------------------------------------------------------
# Multi-Q Wizard — data types
# ---------------------------------------------------------------------------


@dataclass
class MultiQuestion:
    """A single question in a multi-Q wizard."""
    title: str
    choices: list[str]
    intro: str = ""


@dataclass
class _WizardState:
    """Internal state for the multi-Q wizard."""
    questions: list[MultiQuestion]
    page: int = 0                        # 0..N-1 = Qs, N = Other page
    selections: list[int] = field(default_factory=list)   # selected choice per Q (-1 = Other)
    other_texts: list[str] = field(default_factory=list)  # Other text per Q
    comment: str = ""                     # Other page text
    cursor: int = 0                       # cursor within current page
    focus: str = "choices"                # "choices" or "input"
    input_pos: int = 0                    # cursor position within active text input

    def __post_init__(self) -> None:
        n = len(self.questions)
        if not self.selections:
            self.selections = [0] * n
        if not self.other_texts:
            self.other_texts = [""] * n

    @property
    def total_pages(self) -> int:
        return len(self.questions) + 1   # Qs + Other page

    @property
    def is_other_page(self) -> bool:
        return self.page >= len(self.questions)

    @property
    def current_q(self) -> MultiQuestion | None:
        if self.page < len(self.questions):
            return self.questions[self.page]
        return None

    @property
    def page_label(self) -> str:
        if self.is_other_page:
            return "Other"
        return f"{self.page + 1}/{len(self.questions)}"


# ---------------------------------------------------------------------------
# Multi-Q Wizard — panel builder
# ---------------------------------------------------------------------------

def _build_wizard_panel(
    state: _WizardState,
    *,
    border_style: str = "cyan",
    width: int = 80,
) -> Panel:
    """Build a wizard panel for the current page."""
    from rich.console import Group
    from rich.markdown import Markdown
    from rich.padding import Padding

    parts: list = []

    if state.is_other_page:
        # Other page — free text input
        parts.append(Padding(
            Text.from_markup(
                "[dim]Enter any additional comments or answers\n"
                "that don't fit the above questions.[/dim]"
            ),
            (1, 2, 0, 4),
        ))

        input_line = Text()
        input_line.append_text(Text.from_markup(
            f"[bold {border_style}]Other:[/bold {border_style}] "
        ))
        input_line.append_text(_render_text_with_cursor(
            state.comment, state.input_pos, indent=7,
        ))
        parts.append(Padding(input_line, (1, 2, 0, 4)))

        hints = []
        if state.page > 0:
            hints.append("Shift+Tab \u2190prev")
        hints.append("\\+Enter newline")
        hints.append("Enter confirm all")
        hints.append("Esc cancel")
        parts.append(Padding(Text(" ".join(hints), style="dim"), (1, 2, 0, 4)))

    else:
        q = state.current_q
        assert q is not None

        if q.intro:
            parts.append(Padding(Markdown(q.intro), (1, 2, 0, 4)))

        parts.append(Padding(Markdown(q.title), (0, 2, 0, 4)))

        table = _new_table()
        table.add_row(Text())
        for i, choice in enumerate(q.choices):
            num = i + 1
            is_selected = (i == state.cursor and state.focus == "choices")
            is_answered = (state.selections[state.page] == i)

            if is_selected:
                marker = f"[bold {border_style}]\u276f[/bold {border_style}]"
            elif is_answered:
                marker = f"[{border_style}]\u2713[/{border_style}]"
            else:
                marker = " "

            if is_selected:
                row = Text.from_markup(
                    f"    {marker} [bold {border_style}]{num}.[/bold {border_style}]"
                    f"[bold] {choice}[/bold]"
                )
            elif is_answered:
                row = Text.from_markup(
                    f"    {marker} [{border_style}]{num}.[/{border_style}]"
                    f" {choice}"
                )
            else:
                row = Text.from_markup(
                    f"    {marker} [{border_style}]{num}.[/{border_style}]"
                    f"[dim] {choice}[/dim]"
                )
            table.add_row(row)

        # Other row
        other_idx = len(q.choices)
        is_other_cursor = (state.cursor == other_idx)
        other_text = state.other_texts[state.page]
        is_other_answered = (state.selections[state.page] == -1)

        if is_other_cursor:
            marker = f"[bold {border_style}]\u276f[/bold {border_style}]"
        elif is_other_answered:
            marker = f"[{border_style}]\u2713[/{border_style}]"
        else:
            marker = " "

        other_display = Text()
        if is_other_cursor and state.focus == "input":
            other_display.append_text(Text.from_markup(
                f"    {marker} [bold]Other:[/bold] "
            ))
            other_display.append_text(_render_text_with_cursor(
                other_text, state.input_pos, indent=13,
            ))
        elif is_other_cursor:
            other_display = Text.from_markup(
                f"    {marker} [bold]Other:[/bold] "
                f"{'[dim]' + other_text + '[/dim]' if other_text else '[dim]\u2588[/dim]'}"
            )
        elif is_other_answered and other_text:
            other_display = Text.from_markup(
                f"    {marker} Other: {other_text}"
            )
        else:
            other_display = Text.from_markup(
                f"    {marker} [dim]Other: type to enter...[/dim]"
            )

        table.add_row(other_display)
        parts.append(table)

        # Hint line
        table2 = _new_table()
        table2.add_row(Text())
        hints = ["\u2191\u2193 select"]
        if state.page > 0:
            hints.append("Shift+Tab \u2190prev")
        if state.page < len(state.questions) - 1:
            hints.append("Tab next\u2192")
        else:
            hints.append("Tab Other\u2192")
        num_choices = len(q.choices)
        if num_choices > 1:
            hints.append(f"1-{num_choices} shortcut")
        hints.append("Enter select\u2192next")
        hints.append("Esc cancel")
        table2.add_row(Text.from_markup(
            f"    [dim]{('  ').join(hints)}[/dim]"
        ))
        parts.append(table2)

    title = f"\u2753 Question for you ({state.page_label})"
    return Panel(
        Group(*parts),
        title=title,
        title_align="left",
        border_style=border_style,
        width=width,
    )


# ---------------------------------------------------------------------------
# Multi-Q Wizard — interactive loop
# ---------------------------------------------------------------------------

def multi_question_wizard(
    questions: list[MultiQuestion],
    *,
    border_style: str = "cyan",
    con: Console,
    max_width: int = 80,
) -> list[str] | None:
    """Paged wizard: Tab switches Q pages, last page is 'Other' free text.

    Returns list of answer strings (one per Q + optional Other comment),
    or None on cancel.
    """
    if not sys.stdin.isatty():
        return _wizard_fallback(questions, con=con)

    state = _WizardState(questions=questions)
    panel_width = min(con.size.width - 2, max_width)

    def _panel() -> Panel:
        return _build_wizard_panel(
            state, border_style=border_style, width=panel_width,
        )

    p = _panel()
    prev_height = _measure_height(p, panel_width)
    restore = _disable_echo()
    con.print(p)

    def _redraw() -> None:
        nonlocal prev_height
        con.file.write(f"\033[{prev_height}A\033[J")
        con.file.flush()
        p = _panel()
        prev_height = _measure_height(p, panel_width)
        con.print(p)

    try:
        while True:
            key = _read_key()

            # --- Page navigation ---
            if key == "tab":
                if state.page < state.total_pages - 1:
                    state.page += 1
                    state.focus = "choices"
                    if state.is_other_page:
                        state.input_pos = len(state.comment)
                    else:
                        state.cursor = state.selections[state.page]
                        if state.cursor == -1:
                            q = state.current_q
                            state.cursor = len(q.choices) if q else 0
                    _redraw()
                continue

            if key == "shift-tab":
                if state.page > 0:
                    state.page -= 1
                    state.focus = "choices"
                    if not state.is_other_page:
                        state.cursor = state.selections[state.page]
                        if state.cursor == -1:
                            q = state.current_q
                            state.cursor = len(q.choices) if q else 0
                    _redraw()
                continue

            # --- Other (last) page: free text ---
            if state.is_other_page:
                if key == "enter":
                    txt = state.comment
                    pos = state.input_pos
                    if pos > 0 and txt[pos - 1] == "\\":
                        state.comment = txt[:pos - 1] + "\n" + txt[pos:]
                        _redraw()
                        continue
                    break
                if key in ("escape", "ctrl-c"):
                    return None
                txt = state.comment
                pos = state.input_pos
                if key == "alt-enter":
                    state.comment = txt[:pos] + "\n" + txt[pos:]
                    state.input_pos = pos + 1
                elif key == "left":
                    state.input_pos = max(0, pos - 1)
                elif key == "right":
                    state.input_pos = min(len(txt), pos + 1)
                elif key == "home":
                    state.input_pos = 0
                elif key == "end":
                    state.input_pos = len(txt)
                elif key in ("\x7f", "\x08"):
                    if pos > 0:
                        state.comment = txt[:pos - 1] + txt[pos:]
                        state.input_pos = pos - 1
                elif key == "delete":
                    if pos < len(txt):
                        state.comment = txt[:pos] + txt[pos + 1:]
                elif key == "space":
                    state.comment = txt[:pos] + " " + txt[pos:]
                    state.input_pos = pos + 1
                elif len(key) == 1 and key.isprintable():
                    state.comment = txt[:pos] + key + txt[pos:]
                    state.input_pos = pos + 1
                else:
                    continue
                _redraw()
                continue

            # --- Q page ---
            q = state.current_q
            if q is None:
                continue
            max_cursor = len(q.choices)  # 0..N-1 = choices, N = Other

            if state.focus == "input":
                # Typing in Other field
                txt = state.other_texts[state.page]
                pos = state.input_pos
                if key == "enter" and pos > 0 and txt[pos - 1] == "\\":
                    state.other_texts[state.page] = (
                        txt[:pos - 1] + "\n" + txt[pos:]
                    )
                    _redraw()
                    continue
                if key == "enter":
                    state.selections[state.page] = -1
                    if state.page < state.total_pages - 1:
                        state.page += 1
                        state.focus = "choices"
                        if state.is_other_page:
                            state.input_pos = len(state.comment)
                        else:
                            state.cursor = state.selections[state.page]
                            if state.cursor == -1:
                                q2 = state.current_q
                                state.cursor = (
                                    len(q2.choices) if q2 else 0
                                )
                        _redraw()
                    else:
                        break
                    continue
                if key in ("escape", "ctrl-c"):
                    return None
                if key == "up":
                    state.focus = "choices"
                    state.cursor = (
                        max_cursor - 1 if max_cursor > 0 else 0
                    )
                    _redraw()
                    continue
                if key == "alt-enter":
                    state.other_texts[state.page] = (
                        txt[:pos] + "\n" + txt[pos:]
                    )
                    state.input_pos = pos + 1
                elif key == "left":
                    state.input_pos = max(0, pos - 1)
                elif key == "right":
                    state.input_pos = min(len(txt), pos + 1)
                elif key == "home":
                    state.input_pos = 0
                elif key == "end":
                    state.input_pos = len(txt)
                elif key in ("\x7f", "\x08"):
                    if pos > 0:
                        state.other_texts[state.page] = (
                            txt[:pos - 1] + txt[pos:]
                        )
                        state.input_pos = pos - 1
                    elif pos == 0 and len(txt) == 0:
                        state.focus = "choices"
                elif key == "delete":
                    if pos < len(txt):
                        state.other_texts[state.page] = (
                            txt[:pos] + txt[pos + 1:]
                        )
                elif key == "space":
                    state.other_texts[state.page] = (
                        txt[:pos] + " " + txt[pos:]
                    )
                    state.input_pos = pos + 1
                    state.selections[state.page] = -1
                elif len(key) == 1 and key.isprintable():
                    state.other_texts[state.page] = (
                        txt[:pos] + key + txt[pos:]
                    )
                    state.input_pos = pos + 1
                    state.selections[state.page] = -1
                else:
                    continue
                _redraw()
                continue

            # --- Choice navigation ---
            if key == "up":
                state.cursor = max(0, state.cursor - 1)
            elif key == "down":
                state.cursor = min(max_cursor, state.cursor + 1)
            elif key == "enter":
                if state.cursor < len(q.choices):
                    state.selections[state.page] = state.cursor
                else:
                    state.selections[state.page] = -1
                if state.page < state.total_pages - 1:
                    state.page += 1
                    state.focus = "choices"
                    if state.is_other_page:
                        state.input_pos = len(state.comment)
                    else:
                        state.cursor = state.selections[state.page]
                        if state.cursor == -1:
                            q2 = state.current_q
                            state.cursor = (
                                len(q2.choices) if q2 else 0
                            )
                else:
                    break
            elif key == "space":
                if state.cursor < len(q.choices):
                    state.selections[state.page] = state.cursor
                else:
                    state.focus = "input"
                    state.input_pos = len(state.other_texts[state.page])
                    state.selections[state.page] = -1
            elif key in {str(i + 1) for i in range(len(q.choices))}:
                idx = int(key) - 1
                state.selections[state.page] = idx
                state.cursor = idx
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                if (
                    state.cursor == max_cursor
                    and len(key) == 1
                    and key.isprintable()
                ):
                    state.focus = "input"
                    state.other_texts[state.page] = key
                    state.input_pos = 1
                    state.selections[state.page] = -1
                else:
                    continue

            _redraw()

    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()

    # Build result
    answers = []
    for i, q_item in enumerate(questions):
        sel = state.selections[i]
        if sel == -1:
            answers.append(f"Other: {state.other_texts[i]}")
        elif 0 <= sel < len(q_item.choices):
            answers.append(q_item.choices[sel])
        else:
            answers.append("(no answer)")
    if state.comment.strip():
        answers.append(f"Comment: {state.comment.strip()}")
    return answers


def _wizard_fallback(
    questions: list[MultiQuestion],
    *,
    con: Console,
) -> list[str] | None:
    """Non-TTY fallback for multi_question_wizard."""
    answers = []
    for i, q in enumerate(questions):
        con.print(f"\n  Q{i + 1}. {q.title}")
        for j, c in enumerate(q.choices, 1):
            con.print(f"    {j}. {c}")
        con.print(
            f"  [dim]Enter 1-{len(q.choices)} or type custom answer,"
            " q to cancel[/dim]"
        )
        try:
            ans = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if ans.lower() == "q":
            return None
        try:
            idx = int(ans) - 1
            if 0 <= idx < len(q.choices):
                answers.append(q.choices[idx])
            else:
                answers.append(ans)
        except ValueError:
            answers.append(ans)

    con.print("\n  [dim]Additional comments (or press Enter to skip):[/dim]")
    try:
        comment = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if comment:
        answers.append(f"Comment: {comment}")
    return answers


# ---------------------------------------------------------------------------
# Checklist — panel builder
# ---------------------------------------------------------------------------

def _build_checklist_panel(
    items: list[str],
    *,
    checked: list[bool],
    selected: int,
    comment: str = "",
    comment_pos: int = 0,
    focus: str = "list",
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    width: int = 80,
) -> Panel:
    """Panel with checkbox items + comment field."""
    from rich.console import Group
    from rich.markdown import Markdown
    from rich.padding import Padding

    parts: list = []

    if subtitle and subtitle.strip():
        parts.append(Padding(Markdown(subtitle), (1, 2, 0, 4)))

    table = _new_table()
    table.add_row(Text())

    for i, item in enumerate(items):
        check = "\u2611" if checked[i] else "\u2610"
        is_sel = (i == selected and focus == "list")
        num = i + 1

        if is_sel:
            row = Text.from_markup(
                f"    [bold {border_style}]\u276f {check} {num}."
                f"[/bold {border_style}][bold] {item}[/bold]"
            )
        elif checked[i]:
            row = Text.from_markup(
                f"    [{border_style}]  {check} {num}."
                f"[/{border_style}] {item}"
            )
        else:
            row = Text.from_markup(
                f"      {check} [{border_style}]{num}."
                f"[/{border_style}][dim] {item}[/dim]"
            )
        table.add_row(row)

    parts.append(table)

    # Comment field
    comment_label = Text()
    if focus == "comment":
        comment_label.append_text(Text.from_markup(
            f"\n    [bold {border_style}]\u276f"
            f"[/bold {border_style}] [bold]Comment:[/bold] "
        ))
        comment_label.append_text(_render_text_with_cursor(
            comment, comment_pos, indent=15,
        ))
    else:
        if comment:
            comment_label.append_text(Text.from_markup(
                f"\n      Comment: {comment}"
            ))
        else:
            comment_label.append_text(Text.from_markup(
                "\n      [dim]Comment: type to enter...[/dim]"
            ))

    parts.append(Padding(comment_label, (0, 2, 0, 2)))

    # Hint
    hints = ["\u2191\u2193 move", "Space toggle", "Tab\u2192comment"]
    if len(items) > 1:
        hints.append(f"1-{len(items)} shortcut")
    hints.append("Enter confirm")
    hints.append("Esc cancel")

    parts.append(Padding(
        Text.from_markup(f"\n    [dim]{('  ').join(hints)}[/dim]"),
        (0, 2, 0, 2),
    ))

    return Panel(
        Group(*parts),
        title=title,
        title_align="left",
        border_style=border_style,
        width=width,
    )


# ---------------------------------------------------------------------------
# Checklist — interactive loop
# ---------------------------------------------------------------------------

def checklist_input(
    items: list[str],
    *,
    title: str = "\u2753 Question for you",
    subtitle: str | None = None,
    border_style: str = "cyan",
    con: Console,
    max_width: int = 80,
) -> tuple[list[bool], str] | None:
    """Checkbox list + comment field.

    Returns (checks, comment) or None on cancel.
    """
    if not sys.stdin.isatty():
        return _checklist_fallback(
            items, title=title, subtitle=subtitle, con=con,
        )

    checked = [False] * len(items)
    selected = 0
    comment = ""
    comment_pos = 0
    focus = "list"
    panel_width = min(con.size.width - 2, max_width)

    def _panel() -> Panel:
        return _build_checklist_panel(
            items,
            checked=checked,
            selected=selected,
            comment=comment,
            comment_pos=comment_pos,
            focus=focus,
            title=title,
            subtitle=subtitle,
            border_style=border_style,
            width=panel_width,
        )

    p = _panel()
    prev_height = _measure_height(p, panel_width)
    restore = _disable_echo()
    con.print(p)

    def _redraw() -> None:
        nonlocal prev_height
        con.file.write(f"\033[{prev_height}A\033[J")
        con.file.flush()
        p = _panel()
        prev_height = _measure_height(p, panel_width)
        con.print(p)

    try:
        while True:
            key = _read_key()

            if focus == "comment":
                if (
                    key == "enter"
                    and comment_pos > 0
                    and comment[comment_pos - 1] == "\\"
                ):
                    comment = (
                        comment[:comment_pos - 1] + "\n" + comment[comment_pos:]
                    )
                    _redraw()
                    continue
                if key == "enter":
                    return (checked, comment.strip())
                if key in ("escape", "ctrl-c"):
                    return None
                if key in ("shift-tab", "up"):
                    focus = "list"
                    selected = len(items) - 1
                    _redraw()
                    continue
                if key == "alt-enter":
                    comment = (
                        comment[:comment_pos] + "\n" + comment[comment_pos:]
                    )
                    comment_pos += 1
                elif key == "left":
                    comment_pos = max(0, comment_pos - 1)
                elif key == "right":
                    comment_pos = min(len(comment), comment_pos + 1)
                elif key == "home":
                    comment_pos = 0
                elif key == "end":
                    comment_pos = len(comment)
                elif key in ("\x7f", "\x08"):
                    if comment_pos > 0:
                        comment = (
                            comment[:comment_pos - 1] + comment[comment_pos:]
                        )
                        comment_pos -= 1
                    elif comment_pos == 0 and len(comment) == 0:
                        focus = "list"
                        selected = len(items) - 1
                elif key == "delete":
                    if comment_pos < len(comment):
                        comment = (
                            comment[:comment_pos] + comment[comment_pos + 1:]
                        )
                elif key == "space":
                    comment = (
                        comment[:comment_pos] + " " + comment[comment_pos:]
                    )
                    comment_pos += 1
                elif len(key) == 1 and key.isprintable():
                    comment = (
                        comment[:comment_pos] + key + comment[comment_pos:]
                    )
                    comment_pos += 1
                else:
                    continue
                _redraw()
                continue

            # --- List mode ---
            if key == "up":
                selected = max(0, selected - 1)
            elif key == "down":
                if selected < len(items) - 1:
                    selected += 1
                else:
                    focus = "comment"
                    comment_pos = len(comment)
            elif key == "tab":
                focus = "comment"
                comment_pos = len(comment)
            elif key == "space":
                checked[selected] = not checked[selected]
            elif key == "enter":
                return (checked, comment.strip())
            elif key in ("escape", "ctrl-c"):
                return None
            elif key in {str(i + 1) for i in range(len(items))}:
                idx = int(key) - 1
                checked[idx] = not checked[idx]
                selected = idx
            else:
                continue

            _redraw()

    except (KeyboardInterrupt, EOFError):
        return None
    finally:
        if restore:
            restore()


def _checklist_fallback(
    items: list[str],
    *,
    title: str,
    subtitle: str | None = None,
    con: Console,
) -> tuple[list[bool], str] | None:
    """Non-TTY fallback for checklist_input."""
    from rich.markdown import Markdown as _Markdown

    con.print(f"\n  {title}", style="bold")
    if subtitle and subtitle.strip():
        con.print(_Markdown(subtitle))
    con.print()
    for i, item in enumerate(items, 1):
        con.print(f"    {i}. {item}")
    con.print(
        "\n  [dim]Enter numbers to toggle (e.g. 1,3,4), q to cancel[/dim]"
    )
    try:
        ans = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if ans.lower() == "q":
        return None
    checked = [False] * len(items)
    for part in ans.split(","):
        try:
            idx = int(part.strip()) - 1
            if 0 <= idx < len(items):
                checked[idx] = True
        except ValueError:
            pass
    con.print("\n  [dim]Comments (or Enter to skip):[/dim]")
    try:
        comment_text = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return (checked, comment_text)
