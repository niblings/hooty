"""Agents slash commands: /agents and subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_agents(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /agents commands."""
    if args:
        sub = args[0].lower()
        if sub == "list":
            _cmd_agents_list(ctx)
            return
        if sub == "info":
            _cmd_agents_info(ctx, args[1:])
            return
        if sub == "reload":
            _cmd_agents_reload(ctx)
            return
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {args[0]}[/error]")
        ctx.console.print("  [dim]/agents              \u2014 List sub-agents[/dim]")
        ctx.console.print("  [dim]/agents info <name>  \u2014 Show agent details[/dim]")
        ctx.console.print("  [dim]/agents reload       \u2014 Reload from disk[/dim]")
        return

    _cmd_agents_list(ctx)


def _cmd_agents_list(ctx: CommandContext) -> None:
    """List all available sub-agents."""
    from hooty.agent_store import load_agents_config

    agents = load_agents_config(ctx.config)
    if not agents:
        ctx.console.print("  [dim]No sub-agents available[/dim]")
        return

    ctx.console.print()
    ctx.console.print(f"  Sub-agents ({len(agents)} available)", style="bold")
    ctx.console.print()
    for name, adef in agents.items():
        source_tag = f" [dim]({adef.source})[/dim]" if adef.source else ""
        ctx.console.print(f"    [cyan]{name}[/cyan]{source_tag}")
        ctx.console.print(f"      {adef.description}")
    ctx.console.print()


def _cmd_agents_info(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Show details for a specific sub-agent."""
    if not args:
        ctx.console.print("  [error]\u2717 Usage: /agents info <name>[/error]")
        return

    from hooty.agent_store import load_agents_config

    agents = load_agents_config(ctx.config)
    name = args[0]
    adef = agents.get(name)
    if not adef:
        available = ", ".join(sorted(agents.keys()))
        ctx.console.print(f"  [error]\u2717 Unknown agent: {name}[/error]")
        ctx.console.print(f"  [dim]Available: {available}[/dim]")
        return

    ctx.console.print()
    ctx.console.print(f"  Agent: [cyan]{adef.name}[/cyan]", style="bold")
    ctx.console.print(f"  Source: {adef.source}")
    ctx.console.print(f"  Description: {adef.description}")
    if adef.disallowed_tools:
        ctx.console.print(f"  Disallowed tools: {', '.join(adef.disallowed_tools)}")
    if adef.model:
        ctx.console.print(f"  Model: {adef.model.provider} / {adef.model.model_id}")
    else:
        ctx.console.print("  Model: [dim](inherited from parent)[/dim]")
    ctx.console.print(f"  Max turns: {adef.max_turns}")
    ctx.console.print(f"  Max output: {adef.max_output_tokens} chars")
    ctx.console.print()
    instr = adef.instructions.strip()
    if len(instr) > 500:
        instr = instr[:497] + "..."
    ctx.console.print("  Instructions:")
    for line in instr.split("\n"):
        ctx.console.print(f"    [dim]{line}[/dim]")
    ctx.console.print()


def _cmd_agents_reload(ctx: CommandContext) -> None:
    """Reload agents configuration and rebuild agent."""
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())

    from hooty.agent_store import load_agents_config

    agents = load_agents_config(ctx.config)
    ctx.console.print(f"  [success]\u2713 Agents reloaded ({len(agents)} available)[/success]")
