"""Web search toggle: /websearch."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_websearch(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Toggle web search tools (DuckDuckGo)."""
    ctx.config.web_search = not ctx.config.web_search
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    state = "ON" if ctx.config.web_search else "OFF"
    ctx.console.print(f"  [success]\u2713 Web search tools {state}[/success]")
