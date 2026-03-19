"""UI mock for /review — file picker + review findings picker.

Run in a terminal:
    uv run python samples/review_mock.py
"""

from __future__ import annotations

import os
import sys

# Allow running from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from rich.console import Console


def demo_file_picker(console: Console) -> None:
    """Demo the file picker starting from the project root."""
    from hooty.file_picker import pick_file

    console.print("\n[bold cyan]═══ File Picker Demo ═══[/bold cyan]\n")
    root = os.path.join(os.path.dirname(__file__), "..", "src", "hooty")
    result = pick_file(os.path.abspath(root), con=console)
    if result is None:
        console.print("  [dim]Cancelled.[/dim]")
    else:
        console.print(f"  Selected: [bold]{result}[/bold]")
    console.print()


def demo_review_picker(console: Console) -> None:
    """Demo the review findings picker with mock data."""
    from hooty.review_picker import pick_review_findings

    console.print("[bold cyan]═══ Review Findings Picker Demo ═══[/bold cyan]\n")

    mock_findings = [
        {
            "id": 1,
            "severity": "Critical",
            "file": "src/hooty/repl.py",
            "line": 851,
            "title": "Buffer overflow in handler",
            "suggestion": "Add input length validation",
        },
        {
            "id": 2,
            "severity": "Warning",
            "file": "src/hooty/config.py",
            "line": 64,
            "title": "Missing validation for port range",
            "suggestion": "Add range check for port value",
        },
        {
            "id": 3,
            "severity": "Warning",
            "file": "src/hooty/tools/__init__.py",
            "line": 32,
            "title": "Unused import may mask errors",
            "suggestion": "Remove unused import or add noqa comment",
        },
        {
            "id": 4,
            "severity": "Suggestion",
            "file": "src/hooty/repl.py",
            "line": 400,
            "title": "Extract method recommended",
            "suggestion": "Split _handle_slash_command into smaller methods",
        },
        {
            "id": 5,
            "severity": "Suggestion",
            "file": "src/hooty/providers.py",
            "line": 12,
            "title": "Magic number in timeout",
            "suggestion": "Extract timeout to a named constant",
        },
    ]

    result = pick_review_findings(mock_findings, console)
    if result is None:
        console.print("  [dim]Cancelled.[/dim]")
    else:
        console.print(f"  Selected {len(result)} finding(s) for fix:")
        for req in result:
            f = req.finding
            console.print(f"    - #{f['id']} {f['title']}")
            if req.custom_instruction:
                console.print(f"      Custom: {req.custom_instruction}")
    console.print()


def main() -> None:
    console = Console()
    console.print("[bold]Hooty /review UI Mock[/bold]")
    console.print("[dim]This demo lets you try both the file picker and findings picker.[/dim]\n")

    demo_file_picker(console)
    demo_review_picker(console)


if __name__ == "__main__":
    main()
