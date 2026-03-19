"""Ask-user tool — lets the LLM ask the human a question mid-conversation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from agno.tools import Toolkit

from hooty.tools.confirm import _active_live, _non_interactive
from hooty.ui import (
    MultiQuestion,
    _active_console,
    checklist_input,
    multi_question_wizard,
    number_select,
    text_input,
)

NO_RESPONSE = "(no response)"


def _parse_choices(raw: str) -> list[str]:
    """Split a choices string (comma- or newline-separated) into a list."""
    items = re.split(r"[,\n]", raw)
    return [c.strip() for c in items if c.strip()]


# ---------------------------------------------------------------------------
# Multi-Q parser
# ---------------------------------------------------------------------------

# Pattern: **Q1.**, **Q2.**, ## Q1, ## Q2, Q1., Q2., etc.
_Q_HEADER_RE = re.compile(
    r"(?:^|\n)"                   # start of text or newline
    r"\s*"                        # optional leading whitespace
    r"(?:\*{1,2}|#{1,2}\s*)?"    # optional bold markers or heading
    r"Q(\d+)"                     # "Q" + number (capture group 1)
    r"[.\s:：]"                   # separator after number
    r"\s*"
    r"(.*?)(?=\n|$)"             # rest of line = question title
)

_NUMBERED_ITEM_RE = re.compile(
    r"^\s*(\d+)[.)]\s+(.+)$", re.MULTILINE,
)


def _parse_multi_questions(question: str) -> list[MultiQuestion] | None:
    """Parse a question text containing Q1/Q2/Q3... into structured questions.

    Returns None if the text doesn't match the multi-Q pattern.
    """
    headers = list(_Q_HEADER_RE.finditer(question))
    if len(headers) < 1:
        return None

    results: list[MultiQuestion] = []
    intro = question[:headers[0].start()].strip()

    for idx, match in enumerate(headers):
        title_line = match.group(0).strip()
        # Extract the section text between this header and the next
        start = match.end()
        end = headers[idx + 1].start() if idx + 1 < len(headers) else len(question)
        section = question[start:end]

        # Extract numbered choices from the section
        choices = [m.group(2).strip() for m in _NUMBERED_ITEM_RE.finditer(section)]

        mq = MultiQuestion(
            title=title_line,
            choices=choices,
            intro=intro if idx == 0 else "",
        )
        results.append(mq)

    return results if len(results) >= 1 else None


# ---------------------------------------------------------------------------
# Checklist parser
# ---------------------------------------------------------------------------

# Pattern for checklist items: lines like "- [ ] item" or "- [x] item" or
# numbered items after a leading question, where all items are toggleable.
_CHECKLIST_ITEM_RE = re.compile(
    r"^\s*[-*]\s*\[([xX ]?)\]\s+(.+)$", re.MULTILINE,
)

# Alternative: numbered Yes/No items (e.g. "1. Enable X  2. Enable Y")
_YN_ITEM_RE = re.compile(
    r"^\s*(\d+)[.)]\s+(.+)$", re.MULTILINE,
)


@dataclass
class _ChecklistParseResult:
    """Result of parsing a checklist question."""
    subtitle: str
    items: list[str]
    defaults: list[bool]


def _parse_checklist(question: str) -> _ChecklistParseResult | None:
    """Parse a question containing checkbox items (- [ ] / - [x]).

    Returns None if fewer than 2 checkbox items found.
    """
    matches = list(_CHECKLIST_ITEM_RE.finditer(question))
    if len(matches) < 2:
        return None

    items = [m.group(2).strip() for m in matches]
    defaults = [m.group(1).lower() == "x" for m in matches]

    # Subtitle = text before the first checkbox item
    subtitle = question[:matches[0].start()].strip()

    return _ChecklistParseResult(subtitle=subtitle, items=items, defaults=defaults)


# ---------------------------------------------------------------------------
# Answer formatters
# ---------------------------------------------------------------------------

def _format_multi_answers(
    questions: list[MultiQuestion],
    answers: list[str],
) -> str:
    """Format wizard answers into a readable string for the LLM."""
    parts: list[str] = []
    for i, q in enumerate(questions):
        # Strip markdown bold from title for clean output
        clean_title = q.title.replace("**", "").strip()
        if i < len(answers):
            parts.append(f"{clean_title} → {answers[i]}")
        else:
            parts.append(f"{clean_title} → (no answer)")
    # Append any extra answers (e.g. "Comment: ...")
    for ans in answers[len(questions):]:
        parts.append(ans)
    return "\n".join(parts)


def _format_checklist_answers(
    result: _ChecklistParseResult,
    checked: list[bool],
    comment: str,
) -> str:
    """Format checklist answers into a readable string for the LLM."""
    parts: list[str] = []
    for i, item in enumerate(result.items):
        mark = "Yes" if checked[i] else "No"
        parts.append(f"- {item}: {mark}")
    if comment:
        parts.append(f"Comment: {comment}")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Prompt logic
# ---------------------------------------------------------------------------

def _do_prompt(question: str, choices: list[str] | None) -> str:
    """Display a question and collect user input via Rich Panel selectors."""
    con = _active_console[0]
    if con is None:
        from rich.console import Console

        con = Console()

    # 1. Explicit choices → number_select with Other support
    if choices:
        result = number_select(
            choices,
            title="\u2753 Question for you",
            subtitle=question,
            border_style="cyan",
            con=con,
            max_width=80,
            allow_other=True,
        )
        if result is None:
            return NO_RESPONSE
        if isinstance(result, str):
            return result  # Other free-text
        return choices[result]

    # 2. Multi-Q parse → wizard UI
    multi = _parse_multi_questions(question)
    if multi:
        answers = multi_question_wizard(multi, con=con, max_width=80)
        if answers is None:
            return NO_RESPONSE
        return _format_multi_answers(multi, answers)

    # 3. Checklist parse → checklist UI
    cl = _parse_checklist(question)
    if cl:
        result = checklist_input(
            cl.items,
            title="\u2753 Question for you",
            subtitle=cl.subtitle or None,
            con=con,
            max_width=80,
        )
        if result is None:
            return NO_RESPONSE
        checked, comment = result
        # Apply defaults for untouched items (if user didn't interact)
        return _format_checklist_answers(cl, checked, comment)

    # 4. Fallback → existing text_input
    answer = text_input(
        title="\u2753 Question for you",
        subtitle=question,
        border_style="cyan",
        con=con,
        max_width=80,
    )
    return answer if answer else NO_RESPONSE


def _ask_user_prompt(question: str, choices: list[str] | None) -> str:
    """Pause Rich Live, collect input, then resume."""
    if _non_interactive[0]:
        return NO_RESPONSE

    live: Any = _active_live[0]
    if live:
        live.stop()
        # Erase residual spinner content for ConPTY
        from hooty.repl_ui import _erase_live_area

        lr = getattr(live, "_live_render", None)
        shape = getattr(lr, "_shape", None)
        height = shape[1] if shape else 1
        _erase_live_area(live.console.file, height)

    try:
        return _do_prompt(question, choices)
    except KeyboardInterrupt:
        raise
    finally:
        if live:
            live.start()


class AskUserTools(Toolkit):
    """Toolkit that lets the LLM ask the user a question."""

    def __init__(self) -> None:
        super().__init__(
            name="ask_user_tools",
            instructions=(
                "Use ask_user() to ask the human a question when you need "
                "clarification or want the user to choose between options.\n\n"
                "DECISION TREE — pick the right format:\n\n"
                "1. **Fixed choices** (Y/N, A/B/C, named options) → "
                "MUST use the `choices` parameter (comma-separated). "
                "Do NOT embed numbered lists in `question` text for this; "
                "use `choices` instead. The UI automatically adds an 'Other' "
                "row for free-form input, so do NOT include 'Other' or "
                "'その他' in your choices list.\n\n"
                "2. **Multiple sub-questions** → Use `**Q1. …**` headers, "
                "each followed by numbered choices (`1. …`, `2. …`). "
                "Works for 1 or more questions. Example:\n"
                '  "**Q1. CLI library?**\\n1. argparse\\n2. typer"\n\n'
                "3. **Toggle list** → Use `- [ ] item` / `- [x] item` "
                "checkbox lines for on/off toggles.\n\n"
                "4. **Free text** → Plain `question` with no special "
                "format; shows a text input box.\n\n"
                "All selector formats include an 'Other' free-input option, "
                "so the user can always provide a custom answer.\n\n"
                "Markdown is rendered in all question panels."
            ),
            add_instructions=True,
        )
        self.register(self.ask_user)

    def ask_user(self, question: str, choices: str | None = None) -> str:
        """Ask the user a question and return their answer.

        The question text supports Markdown and is rendered in a Rich panel.

        Special patterns detected automatically:

        - **Multi-Q**: Use ``**Q1. title**`` / ``**Q2. title**`` headers each
          followed by numbered choices (``1. option``, ``2. option``).
          The user sees a paged wizard with Tab/Shift+Tab navigation.

        - **Checklist**: Use ``- [ ] item`` / ``- [x] item`` lines.
          The user sees a checkbox list with Space to toggle.

        If neither pattern matches, a free-text input is shown.

        :param question: The question to present (Markdown supported).
        :param choices: Optional comma- or newline-separated list of fixed
            choices.  When provided, a numbered selector is shown directly
            and the auto-detection above is skipped.
        :return: The user's answer.
        """
        parsed_choices = _parse_choices(choices) if choices else None
        return _ask_user_prompt(question, parsed_choices)
