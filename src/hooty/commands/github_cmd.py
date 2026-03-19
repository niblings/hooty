"""GitHub tools toggle: /github."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_github(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Toggle GitHub tools on/off."""
    if not os.environ.get("GITHUB_ACCESS_TOKEN"):
        ctx.console.print("  [error]\u2717 GITHUB_ACCESS_TOKEN is not set[/error]")
        return
    ctx.config.github_enabled = not ctx.config.github_enabled
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    state = "ON" if ctx.config.github_enabled else "OFF"
    ctx.console.print(f"  [success]\u2713 GitHub tools {state}[/success]")
