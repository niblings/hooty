"""Text utilities — display-width-aware truncation for CJK-safe output."""

from __future__ import annotations

import unicodedata


def _char_width(ch: str) -> int:
    """Return the display width of a single character.

    East Asian Wide/Fullwidth characters occupy 2 columns; all others 1.
    """
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


def truncate_display(text: str, max_width: int, suffix: str = "...") -> str:
    """Truncate *text* so its display width fits within *max_width* columns.

    If truncation is needed, *suffix* is appended and its width is accounted
    for.  This avoids splitting CJK characters mid-glyph and keeps the result
    within the intended terminal column budget.

    If *text* already fits, it is returned unchanged.
    """
    # Fast path: pure ASCII short string
    if len(text) <= max_width and text.isascii():
        return text

    suffix_width = sum(_char_width(c) for c in suffix)
    budget = max_width - suffix_width

    width = 0
    for i, ch in enumerate(text):
        cw = _char_width(ch)
        if width + cw > max_width:
            # Need truncation — rewind to fit within budget
            trunc_width = 0
            for j, tc in enumerate(text):
                tw = _char_width(tc)
                if trunc_width + tw > budget:
                    return text[:j] + suffix
                trunc_width += tw
            # Entire text fits within budget (shouldn't reach here normally)
            return text + suffix
        width += cw

    return text
