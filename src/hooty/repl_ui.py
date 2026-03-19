"""UI components for the Hooty REPL.

Extracted from repl.py — contains ThinkingIndicator, _BSUWriter,
ScrollableMarkdown, HOOTY_THEME, and banner/summary helpers.
"""

from __future__ import annotations

import typing

from rich.text import Text
from rich.theme import Theme


def _skills_summary(skills: list) -> str:
    """Build a compact summary string like '2 loaded, 1 manual'."""
    loaded = sum(1 for s in skills if s.enabled and not s.disable_model_invocation)
    manual = sum(1 for s in skills if s.disable_model_invocation)
    parts = [f"{loaded} loaded"]
    if manual:
        parts.append(f"{manual} manual")
    return ", ".join(parts)


class ThinkingIndicator:
    """Animated thinking indicator with brightness wave."""

    _SHADES_GOLD = [
        "#9E8600", "#a89000", "#b29a00", "#bca400", "#c6ae00",
        "#E6C200", "#c6ae00", "#bca400", "#b29a00", "#a89000",
    ]
    _SHADES_CYAN = [
        "#007a7a", "#008888", "#009696", "#00a4a4", "#00b2b2",
        "#00cccc", "#00b2b2", "#00a4a4", "#009696", "#008888",
    ]
    _SHADES_GREEN = [
        "#007a3d", "#008844", "#00964c", "#00a453", "#00b25b",
        "#00cc66", "#00b25b", "#00a453", "#00964c", "#008844",
    ]

    def __init__(self, text: str = "Thinking...", *, plan_mode: bool = False, safe_mode: bool = True) -> None:
        self._text = text
        self._suffix = ""
        self._plan_mode = plan_mode
        self._safe_mode = safe_mode
        self._start_time: float | None = None
        if plan_mode:
            color = "#00cccc"
        elif safe_mode:
            color = "#00cc66"
        else:
            color = "#E6C200"
        from rich.spinner import Spinner

        self._spinner = Spinner("dots", style=color)

    def set_start_time(self, t: float) -> None:
        """Set the start time for elapsed display."""
        self._start_time = t

    def set_tool(self, tool_name: str) -> None:
        """Set the tool name suffix."""
        self._suffix = f" ({tool_name})"

    def clear_tool(self) -> None:
        """Clear the tool name suffix."""
        self._suffix = ""

    def __rich_console__(
        self, console: object, options: object
    ) -> typing.Generator:
        import time

        t = time.monotonic()
        result = Text()
        result.append_text(self._spinner.render(t))
        result.append(" ")
        if self._plan_mode:
            shades = self._SHADES_CYAN
        elif self._safe_mode:
            shades = self._SHADES_GREEN
        else:
            shades = self._SHADES_GOLD
        n = len(shades)
        for i, ch in enumerate(self._text):
            idx = int(t * 6 + i) % n
            result.append(ch, style=shades[idx])
        if self._start_time is not None:
            elapsed = t - self._start_time
            if elapsed >= 60:
                mins = int(elapsed) // 60
                secs = int(elapsed) % 60
                result.append(f" {mins}m {secs}s", style="#666666")
            else:
                result.append(f" {int(elapsed)}s", style="#666666")
        if self._suffix:
            result.append(self._suffix, style="#888888")
        yield result

    def __rich_measure__(
        self, console: object, options: object
    ) -> typing.Any:
        from rich.measure import Measurement

        w = len(self._text) + len(self._suffix) + 6 + 8
        return Measurement(w, w)


class _BSUWriter:
    """Wraps file writes with DEC Synchronized Output (mode 2026).

    Terminals that support this protocol buffer rendering between the
    Begin/End markers and paint the frame in one go, eliminating flicker
    caused by partial redraws — especially visible on WSL via ConPTY.
    Unsupported terminals silently ignore the escape sequences.

    Supports *frame batching*: call :meth:`begin_frame` before a group
    of writes and :meth:`end_frame` after.  While batching, individual
    ``write()`` calls are buffered and emitted as a single BSU/ESU
    pair so that cursor-up + erase + new content is atomic.
    """

    _BSU = "\033[?2026h"
    _ESU = "\033[?2026l"
    _CURSOR_HIDE = "\033[?25l"
    _CURSOR_SHOW = "\033[?25h"

    def __init__(self, wrapped: typing.IO[str]) -> None:
        self._wrapped = wrapped
        self._batch: list[str] | None = None

    def hide_cursor(self) -> None:
        """Hide cursor (call once at Live start)."""
        self._wrapped.write(self._CURSOR_HIDE)
        self._wrapped.flush()

    def show_cursor(self) -> None:
        """Show cursor (call once at Live end)."""
        self._wrapped.write(self._CURSOR_SHOW)
        self._wrapped.flush()

    def begin_frame(self) -> None:
        """Start buffering writes for atomic output."""
        self._batch = []

    def end_frame(self) -> None:
        """Flush buffered writes as a single BSU/ESU pair."""
        batch = self._batch
        self._batch = None
        if batch:
            self._wrapped.write(f"{self._BSU}{''.join(batch)}{self._ESU}")
            self._wrapped.flush()

    def write(self, s: str) -> int:
        if self._batch is not None:
            self._batch.append(s)
        else:
            self._wrapped.write(f"{self._BSU}{s}{self._ESU}")
        return len(s)

    def flush(self) -> None:
        if self._batch is None:
            self._wrapped.flush()

    def __getattr__(self, name: str) -> typing.Any:
        return getattr(self._wrapped, name)


class ScrollableMarkdown:
    """Markdown renderable that auto-scrolls to the bottom on overflow.

    When rendered content exceeds the available height, only the most
    recent lines are shown (oldest lines are silently trimmed).  No
    overflow indicator or decoration is emitted — any visible character
    gets burned into ConPTY scrollback on each refresh frame.

    The instance is mutable: call :meth:`set_text` to update the content
    without creating a new object.  Parsed/rendered lines are cached and
    only recomputed when the text or available width changes.
    """

    def __init__(self, text: str = "") -> None:
        self._text = text
        self._cached_text: str | None = None
        self._cached_width: int | None = None
        self._cached_lines: list | None = None

    def set_text(self, text: str) -> None:
        self._text = text

    def reset(self) -> None:
        """Clear text and cache (for tool call transitions)."""
        self._text = ""
        self._cached_text = None
        self._cached_width = None
        self._cached_lines = None

    def __rich_console__(
        self, console: object, options: object
    ) -> typing.Generator:
        from rich.markdown import Markdown
        from rich.segment import Segment

        max_width: int = getattr(options, "max_width", 80)
        max_height: int = getattr(options, "max_height", None) or console.height  # type: ignore[union-attr]

        # Only re-parse when text or width changed
        if (
            self._cached_text != self._text
            or self._cached_width != max_width
            or self._cached_lines is None
        ):
            md = Markdown(self._text)
            unconstrained = options.reset_height()  # type: ignore[union-attr]
            self._cached_lines = console.render_lines(md, unconstrained, pad=True)  # type: ignore[union-attr]
            self._cached_text = self._text
            self._cached_width = max_width

        all_lines = self._cached_lines
        visible = all_lines[-max_height:] if len(all_lines) > max_height else all_lines

        for line in visible:
            yield from line
            yield Segment.line()

    def __rich_measure__(
        self, console: object, options: object
    ) -> typing.Any:
        from rich.measure import Measurement

        return Measurement(1, getattr(options, "max_width", 80))


class StreamingView:
    """Composite renderable: ScrollableMarkdown + ThinkingIndicator.

    Shows streaming content with the thinking spinner always visible at
    the bottom.  This ensures the user gets continuous visual feedback
    (animated spinner + elapsed seconds) even when content tokens stop
    arriving while the LLM generates tool-call arguments.

    The total height is kept constant once overflow begins: max_height
    lines = (max_height - 1) content + 1 indicator.  This avoids the
    height transitions that cause ConPTY scrollback artefacts.
    """

    def __init__(
        self,
        scrollable: ScrollableMarkdown,
        indicator: ThinkingIndicator,
    ) -> None:
        self._scrollable = scrollable
        self._indicator = indicator

    def __rich_console__(
        self, console: object, options: object
    ) -> typing.Generator:
        from rich.segment import Segment

        max_height: int = getattr(options, "max_height", None) or console.height  # type: ignore[union-attr]
        # Reserve 1 line for the indicator at the bottom.
        content_height = max(max_height - 1, 1)

        # Build a constrained options for the scrollable portion.
        try:
            content_options = options.update_height(content_height)  # type: ignore[union-attr]
        except Exception:
            content_options = options

        # Render scrollable content.
        yield from self._scrollable.__rich_console__(console, content_options)

        # Render indicator on the last line.
        yield from self._indicator.__rich_console__(console, options)
        yield Segment.line()

    def __rich_measure__(
        self, console: object, options: object
    ) -> typing.Any:
        from rich.measure import Measurement

        return Measurement(1, getattr(options, "max_width", 80))


def _erase_live_area(file: typing.IO[str], height: int) -> None:
    """Erase ``height`` lines above cursor (explicit cleanup for ConPTY)."""
    if not isinstance(height, int) or height <= 0:
        return
    seq = "".join("\033[A\033[2K" for _ in range(height))
    file.write(seq)
    file.flush()


# Custom theme for Hooty color scheme
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
