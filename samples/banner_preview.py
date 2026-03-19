"""Banner color preview script for Hooty mascot.

Three owl expressions: open / wink (right half-closed) / half-closed.
"""

from rich.console import Console

console = Console()

EYE_OPEN_STYLE = "#E6C200"
EYE_HALF_STYLE = "#9E8600"


def banner_variant(
    label: str,
    left_eye: str,
    right_eye: str,
    left_style: str,
    right_style: str,
) -> None:
    """White owl with specified eye characters and colors."""
    console.print()
    console.print(f"  === {label} ===", style="bold")
    console.print()
    console.print("   ,___,", style="bright_white")
    console.print(
        f"   ([bold {left_style}]{left_eye}[/bold {left_style}]"
        f",[bold {right_style}]{right_eye}[/bold {right_style}])"
        "    [cyan]Hooty v0.1.0[/cyan]"
    )
    console.print(
        "[bright_white]   /)  )[/bright_white]"
        "    [dim]Provider: AWS Bedrock (claude-4.6-sonnet)[/dim]"
    )
    console.print(
        '[bright_white]  --""--[/bright_white]'
        "    [dim]Working directory: ~/my-project[/dim]"
    )
    console.print()


if __name__ == "__main__":
    # 1. open eyes
    console.print("\n")
    console.print("  ====== 1. 両目オープン (o,o) ======", style="bold magenta")
    banner_variant("両目オープン", "o", "o", EYE_OPEN_STYLE, EYE_OPEN_STYLE)
    console.print("─" * 50)

    # 2. squinting
    console.print("\n")
    console.print("  ====== 2. しょぼしょぼ (=,=) ======", style="bold magenta")
    banner_variant("しょぼしょぼ", "=", "=", EYE_HALF_STYLE, EYE_HALF_STYLE)
    console.print("─" * 50)

    # 3. both eyes half-closed
    console.print("\n")
    console.print("  ====== 3. 両目半目 (ᴗ,ᴗ) ======", style="bold magenta")
    banner_variant("両目半目", "ᴗ", "ᴗ", EYE_HALF_STYLE, EYE_HALF_STYLE)
    console.print("─" * 50)
