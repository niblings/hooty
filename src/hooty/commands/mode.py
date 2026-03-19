"""Mode switching slash commands: /plan, /code, /auto."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_auto(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Toggle auto mode transitions."""
    ctx.auto_ref[0] = not ctx.auto_ref[0]
    state = "enabled" if ctx.auto_ref[0] else "disabled"
    ctx.console.print(f"  [success]\u2713 Auto mode transitions {state}[/success]")


def cmd_plan(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Switch to plan mode."""
    _set_plan_mode(ctx, True)


def cmd_code(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Switch to coding mode."""
    _set_plan_mode(ctx, False)


def _set_plan_mode(ctx: CommandContext, enabled: bool) -> None:
    """Set plan or execute mode, recreating the agent."""
    if ctx.get_plan_mode() == enabled:
        mode_name = "PLANNING" if enabled else "CODING"
        ctx.console.print(f"  [dim]Already in {mode_name.capitalize()} mode[/dim]")
        return
    ctx.set_plan_mode(enabled)
    ctx.auto_execute_ref[0] = False
    ctx.close_agent_model()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(enabled)
    mode_name = "PLANNING" if enabled else "CODING"
    ctx.console.print(f"  [success]\u2713 Switched to {mode_name.capitalize()} mode[/success]")
