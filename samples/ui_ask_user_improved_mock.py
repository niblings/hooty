"""Improved ask-user UI mock — multi-Q wizard + checklist + markdown subtitle.

Standalone preview of the proposed UI improvements for the ask_user tool.
Three new interaction patterns:

  1. Markdown subtitle:  Rich Markdown rendering in question panels
  2. Multi-Q wizard:     Tab/Shift+Tab page navigation for Q1/Q2/.../Other
  3. Checklist + comment: Checkbox list with Space toggle + free text comment

Run in a terminal:
    uv run python samples/ui_ask_user_improved_mock.py
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from io import StringIO

from rich.console import Console, Group
from rich.markdown import Markdown
from rich.padding import Padding
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.theme import Theme

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
# Keystroke reader (from ui_confirm_mock.py)
# ---------------------------------------------------------------------------

def _read_key() -> str:
    """Read a single keypress and return a normalized name."""
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


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _new_table() -> Table:
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


def _render_text_with_cursor(txt: str, pos: int, *, indent: int = 0) -> Text:
    """Render text with a cursor indicator, supporting multiline (\\n).

    ``indent`` is the number of spaces to prepend to continuation lines
    (lines after the first \\n) so they align with the input start position.
    """
    # Replace \n with \n + indent spaces for display
    indent_str = " " * indent
    display = txt.replace("\n", "\n" + indent_str)
    # Adjust pos to account for added indent chars
    # Count newlines before pos in original text
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


def _measure_height(panel: Panel, width: int) -> int:
    buf = Console(width=width, file=StringIO(), force_terminal=True)
    buf.print(panel)
    return buf.file.getvalue().count("\n")


def _disable_echo() -> object | None:
    try:
        import termios

        fd = sys.stdin.fileno()
        old_attrs = termios.tcgetattr(fd)
        new_attrs = termios.tcgetattr(fd)
        new_attrs[3] &= ~(termios.ECHO | termios.ICANON)
        new_attrs[6][termios.VMIN] = 1
        new_attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSANOW, new_attrs)
        return lambda: termios.tcsetattr(
            fd, termios.TCSADRAIN, old_attrs
        )
    except (ImportError, OSError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class MultiQuestion:
    """A single question in a multi-Q wizard."""
    title: str
    choices: list[str]
    intro: str = ""


@dataclass
class WizardState:
    """State for the multi-Q wizard."""
    questions: list[MultiQuestion]
    page: int = 0                        # 0..N-1 = Qs, N = Other page
    selections: list[int] = field(default_factory=list)   # selected choice per Q (-1 = Other)
    other_texts: list[str] = field(default_factory=list)  # Other text per Q
    comment: str = ""                     # Other page text
    cursor: int = 0                       # cursor within current page (choice index, or len(choices) = Other row)
    focus: str = "choices"                # "choices" or "input" (when typing in Other field)
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
# Multi-Q Wizard Panel Builder
# ---------------------------------------------------------------------------

def _build_wizard_panel(
    state: WizardState,
    *,
    border_style: str = "cyan",
    width: int = 80,
) -> Panel:
    """Build a wizard panel for the current page."""
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

        # Text input with "Other: " prompt label + cursor (multiline-aware)
        input_line = Text()
        input_line.append_text(Text.from_markup(f"[bold {border_style}]Other:[/bold {border_style}] "))
        # indent=7 aligns continuation lines with text start after "Other: " (7 chars)
        input_line.append_text(_render_text_with_cursor(state.comment, state.input_pos, indent=7))
        parts.append(Padding(input_line, (1, 2, 0, 4)))

        # Hint
        hints = []
        if state.page > 0:
            hints.append("Shift+Tab \u2190prev")
        hints.append("\\+Enter/Alt+Enter newline")
        hints.append("Enter confirm all")
        hints.append("Esc cancel")
        parts.append(Padding(Text(" ".join(hints), style="dim"), (1, 2, 0, 4)))

    else:
        q = state.current_q
        assert q is not None

        # Intro text (only on first page if present)
        if q.intro:
            parts.append(Padding(Markdown(q.intro), (1, 2, 0, 4)))

        # Question title (as markdown for bold etc.)
        parts.append(Padding(Markdown(q.title), (0, 2, 0, 4)))

        # Choice list
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
            else:
                if is_answered:
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
            # Text input mode (multiline-aware)
            other_display.append_text(Text.from_markup(f"    {marker} [bold]Other:[/bold] "))
            # indent=13 aligns with start of text after "    ❯ Other: "
            # Prefix: "    " (4) + "❯" (1) + " " (1) + "Other:" (6) + " " (1) = 13
            other_display.append_text(_render_text_with_cursor(other_text, state.input_pos, indent=13))
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
        table2.add_row(Text.from_markup(f"    [dim]{('  ').join(hints)}[/dim]"))
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
# Multi-Q Wizard Interactive Loop
# ---------------------------------------------------------------------------

def multi_question_wizard(
    questions: list[MultiQuestion],
    *,
    border_style: str = "cyan",
    con: Console,
    max_width: int = 80,
) -> list[str] | None:
    """Paged wizard: Tab switches Q pages, last page is 'Other' free text.

    Returns list of answer strings (one per Q + Other), or None on cancel.
    """
    if not sys.stdin.isatty():
        return _wizard_fallback(questions, con=con)

    state = WizardState(questions=questions)
    panel_width = min(con.size.width - 2, max_width)

    def _panel() -> Panel:
        return _build_wizard_panel(state, border_style=border_style, width=panel_width)

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
                    # \+Enter inserts newline
                    txt = state.comment
                    pos = state.input_pos
                    if pos > 0 and txt[pos - 1] == "\\":
                        state.comment = txt[:pos - 1] + "\n" + txt[pos:]
                        # pos stays same (replaced \ with \n, same index)
                        _redraw()
                        continue
                    break
                if key in ("escape", "ctrl-c"):
                    return None
                # Text editing (multiline: Alt+Enter inserts newline)
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
                    # \+Enter inserts newline
                    state.other_texts[state.page] = txt[:pos - 1] + "\n" + txt[pos:]
                    _redraw()
                    continue
                if key == "enter":
                    # Select Other + advance to next page
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
                                state.cursor = len(q2.choices) if q2 else 0
                        _redraw()
                    else:
                        break  # Last page
                    continue
                if key in ("escape", "ctrl-c"):
                    return None
                if key == "up":
                    # Exit input mode, move cursor up
                    state.focus = "choices"
                    state.cursor = max_cursor - 1 if max_cursor > 0 else 0
                    _redraw()
                    continue
                if key == "alt-enter":
                    state.other_texts[state.page] = txt[:pos] + "\n" + txt[pos:]
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
                        state.other_texts[state.page] = txt[:pos - 1] + txt[pos:]
                        state.input_pos = pos - 1
                    elif pos == 0 and len(txt) == 0:
                        # Backspace on empty: exit input mode
                        state.focus = "choices"
                elif key == "delete":
                    if pos < len(txt):
                        state.other_texts[state.page] = txt[:pos] + txt[pos + 1:]
                elif len(key) == 1 and key.isprintable():
                    state.other_texts[state.page] = txt[:pos] + key + txt[pos:]
                    state.input_pos = pos + 1
                    state.selections[state.page] = -1  # Select Other
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
                # Select current choice and advance to next page
                if state.cursor < len(q.choices):
                    state.selections[state.page] = state.cursor
                else:
                    state.selections[state.page] = -1  # Other
                if state.page < state.total_pages - 1:
                    state.page += 1
                    state.focus = "choices"
                    if state.is_other_page:
                        state.input_pos = len(state.comment)
                    else:
                        state.cursor = state.selections[state.page]
                        if state.cursor == -1:
                            q2 = state.current_q
                            state.cursor = len(q2.choices) if q2 else 0
                else:
                    break  # From last Q page, finalize
            elif key == "space":
                # Select current choice
                if state.cursor < len(q.choices):
                    state.selections[state.page] = state.cursor
                else:
                    # Other row: enter input mode
                    state.focus = "input"
                    state.input_pos = len(state.other_texts[state.page])
                    state.selections[state.page] = -1
            elif key in {str(i + 1): None for i in range(len(q.choices))}:
                # Number shortcut
                idx = int(key) - 1
                state.selections[state.page] = idx
                state.cursor = idx
            elif key in ("escape", "ctrl-c"):
                return None
            else:
                # If on Other row and printable char: enter input mode
                if state.cursor == max_cursor and len(key) == 1 and key.isprintable():
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
    for i, q in enumerate(questions):
        sel = state.selections[i]
        if sel == -1:
            answers.append(f"Other: {state.other_texts[i]}")
        elif 0 <= sel < len(q.choices):
            answers.append(q.choices[sel])
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
        con.print(f"  [dim]Enter 1-{len(q.choices)} or type custom answer, q to cancel[/dim]")
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
# Checklist Panel Builder
# ---------------------------------------------------------------------------

def _build_checklist_panel(
    items: list[str],
    *,
    checked: list[bool],
    selected: int,
    comment: str = "",
    comment_pos: int = 0,
    focus: str = "list",  # "list" or "comment"
    title: str,
    subtitle: str | None = None,
    border_style: str = "cyan",
    width: int = 80,
) -> Panel:
    """Panel with checkbox items + comment field."""
    parts: list = []

    if subtitle:
        parts.append(Padding(Markdown(subtitle), (1, 2, 0, 4)))

    table = _new_table()
    table.add_row(Text())

    for i, item in enumerate(items):
        check = "\u2611" if checked[i] else "\u2610"
        is_sel = (i == selected and focus == "list")
        num = i + 1

        if is_sel:
            row = Text.from_markup(
                f"    [bold {border_style}]\u276f {check} {num}.[/bold {border_style}]"
                f"[bold] {item}[/bold]"
            )
        elif checked[i]:
            row = Text.from_markup(
                f"    [{border_style}]  {check} {num}.[/{border_style}] {item}"
            )
        else:
            row = Text.from_markup(
                f"      {check} [{border_style}]{num}.[/{border_style}]"
                f"[dim] {item}[/dim]"
            )
        table.add_row(row)

    parts.append(table)

    # Comment field
    comment_label = Text()
    if focus == "comment":
        comment_label.append_text(Text.from_markup(f"\n    [bold {border_style}]\u276f[/bold {border_style}] [bold]Comment:[/bold] "))
        # indent=15 aligns with start of text after "    ❯ Comment: "
        comment_label.append_text(_render_text_with_cursor(comment, comment_pos, indent=15))
    else:
        if comment:
            comment_label.append_text(Text.from_markup(f"\n      Comment: {comment}"))
        else:
            comment_label.append_text(Text.from_markup(f"\n      [dim]Comment: type to enter...[/dim]"))

    parts.append(Padding(comment_label, (0, 2, 0, 2)))

    # Hint
    hints = ["\u2191\u2193 move", "Space toggle", "Tab\u2192comment"]
    num = len(items)
    if num > 1:
        hints.append(f"1-{num} shortcut")
    hints.append("\\+Enter/Alt+Enter newline")
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
# Checklist Interactive Loop
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
    """Checkbox list + comment field. Returns (checks, comment) or None on cancel."""
    if not sys.stdin.isatty():
        return _checklist_fallback(items, title=title, subtitle=subtitle, con=con)

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
                # Comment text input mode
                if key == "enter" and comment_pos > 0 and comment[comment_pos - 1] == "\\":
                    # \+Enter inserts newline
                    comment = comment[:comment_pos - 1] + "\n" + comment[comment_pos:]
                    _redraw()
                    continue
                if key == "enter":
                    return (checked, comment.strip())
                if key in ("escape", "ctrl-c"):
                    return None
                if key == "shift-tab" or key == "up":
                    focus = "list"
                    selected = len(items) - 1
                    _redraw()
                    continue
                # Text editing (multiline: Alt+Enter inserts newline)
                if key == "alt-enter":
                    comment = comment[:comment_pos] + "\n" + comment[comment_pos:]
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
                        comment = comment[:comment_pos - 1] + comment[comment_pos:]
                        comment_pos -= 1
                    elif comment_pos == 0 and len(comment) == 0:
                        focus = "list"
                        selected = len(items) - 1
                elif key == "delete":
                    if comment_pos < len(comment):
                        comment = comment[:comment_pos] + comment[comment_pos + 1:]
                elif len(key) == 1 and key.isprintable():
                    comment = comment[:comment_pos] + key + comment[comment_pos:]
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
                    # Move to comment field
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
    con.print(f"\n  {title}", style="bold")
    if subtitle:
        con.print(Markdown(subtitle))
    con.print()
    for i, item in enumerate(items, 1):
        con.print(f"    {i}. {item}")
    con.print(f"\n  [dim]Enter numbers to toggle (e.g. 1,3,4), q to cancel[/dim]")
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
    con.print(f"\n  [dim]Comments (or Enter to skip):[/dim]")
    try:
        comment = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    return (checked, comment)


# ---------------------------------------------------------------------------
# Demo sections
# ---------------------------------------------------------------------------

SAMPLE_QUESTIONS = [
    MultiQuestion(
        title="**Q1. Which CLI library?**",
        choices=["argparse (stdlib, zero deps)", "typer (type hints, auto-complete & help)"],
        intro="3 open questions from the previous plan. Please answer each.",
    ),
    MultiQuestion(
        title="**Q2. Include mock tests with pytest-httpx?**",
        choices=["Yes — create mock tests", "No — minimal tests (or skip)"],
    ),
    MultiQuestion(
        title="**Q3. City selection method?**",
        choices=["Tokyo only (simple)", "--city option for multiple cities (Tokyo default)"],
    ),
]

SAMPLE_CHECKLIST_ITEMS = [
    "Auto-generate unit tests",
    "E2E tests",
    "Lint config (ruff)",
    "CI/CD pipeline",
    "Docker containerization",
]


def section_markdown_subtitle() -> None:
    """Section 1: Compare Text vs Markdown subtitle rendering."""
    console.print()
    console.rule("[bold]Section 1: Markdown Subtitle (Before / After)[/bold]")

    question_md = (
        "3 open questions from the previous plan.\n\n"
        "---\n"
        "**Q1. Which CLI library?**\n"
        "1. argparse (stdlib, zero deps)\n"
        "2. typer (type hints, auto-complete & help)\n\n"
        "---\n"
        "**Q2. Include mock tests with pytest-httpx?**\n"
        "1. Yes  2. No\n"
    )

    pw = min(console.size.width - 4, 80)

    # Before: Text(subtitle)
    console.print()
    console.print("  [bold]Before:[/bold] Text(subtitle) — raw markdown shown")
    console.print()
    console.print(Panel(
        Group(
            Padding(Text(question_md), (1, 2, 0, 4)),
            Padding(Text("Q1=1, Q2=2\u2588", style="dim"), (1, 2, 0, 4)),
            Padding(Text("\u2190\u2192 move  BS del  Enter submit  Esc cancel", style="dim"), (1, 2, 0, 4)),
        ),
        title="\u2753 Question for you",
        title_align="left",
        border_style="cyan",
        width=pw,
    ))

    # After: Markdown(subtitle)
    console.print()
    console.print("  [bold]After:[/bold] Markdown(subtitle) — rendered markdown")
    console.print()
    console.print(Panel(
        Group(
            Padding(Markdown(question_md), (1, 2, 0, 4)),
            Padding(Text("Q1=1, Q2=2\u2588", style="dim"), (1, 2, 0, 4)),
            Padding(Text("\u2190\u2192 move  BS del  Enter submit  Esc cancel", style="dim"), (1, 2, 0, 4)),
        ),
        title="\u2753 Question for you",
        title_align="left",
        border_style="cyan",
        width=pw,
    ))


def section_wizard_static() -> None:
    """Section 2: Static previews of the multi-Q wizard pages."""
    console.print()
    console.rule("[bold]Section 2: Multi-Q Wizard — Static Previews[/bold]")
    console.print()

    pw = min(console.size.width - 4, 80)

    # Page 1/3
    state1 = WizardState(questions=SAMPLE_QUESTIONS, page=0, cursor=0)
    console.print("  [bold]Page 1/3:[/bold]")
    console.print()
    console.print(_build_wizard_panel(state1, width=pw))

    # Page 2/3 (with Q1 already answered)
    state2 = WizardState(questions=SAMPLE_QUESTIONS, page=1, cursor=0)
    state2.selections[0] = 1  # Q1 answered: typer
    console.print()
    console.print("  [bold]Page 2/3:[/bold] (Q1 already answered)")
    console.print()
    console.print(_build_wizard_panel(state2, width=pw))

    # Page 3/3
    state3 = WizardState(questions=SAMPLE_QUESTIONS, page=2, cursor=0)
    state3.selections[0] = 1
    state3.selections[1] = 0
    console.print()
    console.print("  [bold]Page 3/3:[/bold] (Q1, Q2 answered)")
    console.print()
    console.print(_build_wizard_panel(state3, width=pw))

    # Other page
    state_other = WizardState(questions=SAMPLE_QUESTIONS, page=3)
    state_other.selections = [1, 0, 1]
    state_other.comment = "Prefer type safety"
    state_other.input_pos = len(state_other.comment)
    console.print()
    console.print("  [bold]Other page:[/bold] (all Qs answered)")
    console.print()
    console.print(_build_wizard_panel(state_other, width=pw))


def section_wizard_interactive() -> None:
    """Section 3: Interactive multi-Q wizard trial."""
    console.print()
    console.rule("[bold]Section 3: Multi-Q Wizard — Interactive Trial[/bold]")
    console.print()
    console.print("  Tab next→  Shift+Tab ←prev  ↑↓ select  Space/num choose")
    console.print("  Type on Other row to enter text  Enter confirm all  Esc cancel")
    console.print()

    result = multi_question_wizard(SAMPLE_QUESTIONS, con=console)

    console.print()
    if result is None:
        console.print("  → [bold]Cancelled[/bold]")
    else:
        console.print("  → [bold]Answers:[/bold]")
        for i, ans in enumerate(result):
            if i < len(SAMPLE_QUESTIONS):
                console.print(f"    Q{i + 1}: {ans}")
            else:
                console.print(f"    {ans}")


def section_checklist_static() -> None:
    """Section 4: Static preview of checklist."""
    console.print()
    console.rule("[bold]Section 4: Checklist — Static Preview[/bold]")
    console.print()

    pw = min(console.size.width - 4, 80)

    # Unchecked state
    console.print("  [bold]Initial state:[/bold]")
    console.print()
    console.print(_build_checklist_panel(
        SAMPLE_CHECKLIST_ITEMS,
        checked=[False, False, False, False, False],
        selected=0,
        title="\u2753 Question for you",
        subtitle="Which features do you want to enable?",
        width=pw,
    ))

    # Partially checked
    console.print()
    console.print("  [bold]Partially checked + comment:[/bold]")
    console.print()
    console.print(_build_checklist_panel(
        SAMPLE_CHECKLIST_ITEMS,
        checked=[True, False, True, False, True],
        selected=2,
        comment="Use GitHub Actions for CI",
        title="\u2753 Question for you",
        subtitle="Which features do you want to enable?",
        width=pw,
    ))


def section_checklist_interactive() -> None:
    """Section 5: Interactive checklist trial."""
    console.print()
    console.rule("[bold]Section 5: Checklist — Interactive Trial[/bold]")
    console.print()
    console.print("  ↑↓ move  Space toggle  Tab→comment  1-5 shortcut")
    console.print("  Enter confirm  Esc cancel")
    console.print()

    result = checklist_input(
        SAMPLE_CHECKLIST_ITEMS,
        subtitle="Which features do you want to enable?",
        con=console,
    )

    console.print()
    if result is None:
        console.print("  → [bold]Cancelled[/bold]")
    else:
        checks, comment = result
        console.print("  → [bold]Result:[/bold]")
        for i, (item, on) in enumerate(zip(SAMPLE_CHECKLIST_ITEMS, checks)):
            mark = "\u2611" if on else "\u2610"
            console.print(f"    {mark} {item}")
        if comment:
            console.print(f"    Comment: {comment}")


def footer() -> None:
    console.print()
    console.rule("[bold]Legend[/bold]")
    console.print()
    console.print("  [cyan]❓[/cyan] Multi-Q Wizard   [dim]→ Tab/Shift+Tab page nav + ↑↓ select + Other free text[/dim]")
    console.print("  [cyan]❓[/cyan] Checklist        [dim]→ ↑↓ move + Space toggle + Tab→comment[/dim]")
    console.print("  [cyan]❓[/cyan] Markdown subtitle [dim]→ Text() → Markdown() renders bold, lists, rules[/dim]")
    console.print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    console.print()
    console.print(
        Panel.fit(
            "[bold]Hooty Ask-User UI Improvement Mock[/bold]\n"
            "[dim]Multi-Q wizard + Checklist + Markdown subtitle[/dim]",
            border_style="cyan",
        )
    )

    section_markdown_subtitle()
    section_wizard_static()
    section_wizard_interactive()
    section_checklist_static()
    section_checklist_interactive()
    footer()
