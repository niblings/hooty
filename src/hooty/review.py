"""Data types, prompt builders, and JSON parser for /review."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass


@dataclass
class ReviewType:
    """Review type definition."""

    key: str
    label: str
    focus: str


REVIEW_TYPES: list[ReviewType] = [
    ReviewType(
        key="general",
        label="General — comprehensive review",
        focus=(
            "Review from all perspectives: bugs, security, performance, "
            "code quality, architecture, and refactoring opportunities."
        ),
    ),
    ReviewType(
        key="security",
        label="Security — vulnerabilities & credentials",
        focus=(
            "Focus on injection vulnerabilities, credential exposure, unsafe operations, "
            "and input validation. Use grep() to search for sensitive patterns "
            "(password, secret, token, key)."
        ),
    ),
    ReviewType(
        key="performance",
        label="Performance — bottlenecks & efficiency",
        focus=(
            "Focus on N+1 queries, unnecessary allocations, blocking operations, "
            "algorithm complexity, and caching strategies."
        ),
    ),
    ReviewType(
        key="architecture",
        label="Architecture — design & structure",
        focus=(
            "Focus on module coupling, separation of concerns, dependency direction, "
            "abstraction levels, and extensibility. Use find() to survey module structure."
        ),
    ),
    ReviewType(
        key="bug_hunt",
        label="Bug Hunt — logic errors & edge cases",
        focus=(
            "Focus on off-by-one errors, unhandled null/None, race conditions, "
            "uncaught exceptions, type mismatches, and boundary conditions."
        ),
    ),
]


def custom_review_type(user_focus: str) -> ReviewType:
    """Build a ReviewType from free-form user input.

    Wraps the raw input with baseline instructions so the LLM
    treats it as a review focus rather than an arbitrary prompt.
    """
    focus = (
        f"The user requested a review with the following focus: {user_focus}\n"
        "Interpret this as the primary review perspective. "
        "Investigate the codebase accordingly, and report only findings "
        "that are relevant to this focus. "
        "If the focus is broad or ambiguous, also cover bugs and security issues."
    )
    return ReviewType(key="custom", label="Custom", focus=focus)


@dataclass
class FixRequest:
    """A review finding selected for fixing, with optional custom instruction."""

    finding: dict
    custom_instruction: str | None = None


def describe_scope(target: str, working_dir: str) -> str:
    """Convert an absolute path to a human-readable scope description.

    Files show as relative paths, directories get a trailing slash,
    and working_dir itself shows as '.'.
    """
    abs_target = os.path.abspath(target)
    abs_wd = os.path.abspath(working_dir)

    if abs_target == abs_wd:
        return "."

    rel = os.path.relpath(abs_target, abs_wd)
    if os.path.isdir(abs_target):
        return rel.rstrip("/") + "/"
    return rel


def build_review_prompt(
    target: str,
    scope: str,
    working_dir: str,
    review_type: ReviewType,
) -> str:
    """Build the review prompt sent to the agent."""
    abs_target = os.path.abspath(target)
    is_dir = os.path.isdir(abs_target)

    if is_dir:
        scope_instruction = (
            f"Directory: {scope}\n"
            "First use find()/ls() to understand the directory structure, "
            "then read_file() to read and analyse important files."
        )
    else:
        scope_instruction = (
            f"File: {scope}\n"
            "Use read_file() to read the entire file and analyse it."
        )

    return f"""\
Review the following source code.

## Review target
{scope_instruction}

## Steps
1. Understand the file structure of the target (find()/ls())
2. Read and analyse important files with read_file()
3. Search for related patterns and problem areas with grep()

## Review focus
{review_type.focus}

## Output format

### Markdown review
Write each finding with a number. Assign a severity level:
- 🔴 Critical: bugs or security issues that must be fixed immediately
- 🟡 Warning: performance or quality issues that should be improved
- 🔵 Suggestion: concrete refactoring proposals

Note: trivial code-smell findings (naming preferences, missing comments, formatting, etc.) are NOT needed.
Focus on substantive bugs, security risks, performance issues, and design problems.

### Structured summary (required)
At the end of the review, output a JSON summary of all findings in this format:

```json:findings
[
  {{
    "id": 1,
    "severity": "Critical",
    "file": "src/hooty/repl.py",
    "line": 851,
    "title": "Short finding title",
    "suggestion": "Brief description of the fix approach"
  }}
]
```"""


_FINDINGS_RE = re.compile(
    r"```json:findings\s*\n(.*?)```",
    re.DOTALL,
)


def parse_findings(response_text: str) -> list[dict]:
    """Extract findings JSON from agent response.

    Looks for ```json:findings ... ``` block in the response text.
    Returns empty list if not found or parse fails (graceful degradation).
    """
    if not response_text:
        return []

    m = _FINDINGS_RE.search(response_text)
    if not m:
        return []

    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        return []

    if not isinstance(data, list):
        return []

    # Validate each finding has required fields
    required = {"id", "severity", "file", "title"}
    return [f for f in data if isinstance(f, dict) and required.issubset(f.keys())]


def build_fix_prompt(fix_requests: list[FixRequest]) -> str:
    """Build fix prompt from selected findings."""
    sections: list[str] = []

    for i, req in enumerate(fix_requests, 1):
        f = req.finding
        severity = f.get("severity", "Info")
        icon = {"Critical": "🔴", "Warning": "🟡"}.get(severity, "🔵")
        file_ref = f.get("file", "")
        line = f.get("line")
        loc = f"{file_ref}:{line}" if line else file_ref
        title = f.get("title", "")
        suggestion = f.get("suggestion", "")

        section = f"### {i}. {icon} {severity} — {loc}: {title}"
        if suggestion:
            section += f"\nFix approach: {suggestion}"
        if req.custom_instruction:
            section += f"\nCustom instruction: {req.custom_instruction}"

        sections.append(section)

    return f"""\
Implement fixes for the following review findings.

## Findings to fix

{chr(10).join(sections)}

## Steps
1. Read each file with read_file() to confirm the issue
2. Apply minimal fixes with edit_file()
3. After all fixes, report a summary of each change"""
