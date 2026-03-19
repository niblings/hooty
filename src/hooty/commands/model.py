"""Model and reasoning slash commands: /model, /reasoning."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_model(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Open interactive profile picker."""
    from hooty.agent_factory import create_agent
    from hooty.config import validate_config
    from hooty.model_picker import pick_profile

    if not ctx.config.profiles:
        ctx.console.print(f"  Provider: {ctx.config.provider.value}")
        ctx.console.print(f"  Model: {ctx.get_model_id()}")
        ctx.console.print(f"  Max input tokens: {ctx.get_context_limit():,}")
        ctx.console.print("  [dim]No profiles defined. Define profiles in config.yaml to enable switching.[/dim]")
        return

    chosen = pick_profile(ctx.config, ctx.console)
    if chosen is None or chosen == ctx.config.active_profile:
        return

    prev_profile = ctx.config.active_profile
    error = ctx.config.activate_profile(chosen)
    if error:
        ctx.console.print(f"  [error]\u2717 {error}[/error]")
        return

    val_error = validate_config(ctx.config)
    if val_error:
        ctx.config.activate_profile(prev_profile)
        ctx.console.print(f"  [error]\u2717 Cannot switch: {val_error}[/error]")
        return

    old_agent = ctx.get_agent()
    reuse_storage = getattr(old_agent, "db", None)
    reuse_tools = None if ctx.get_plan_mode() else getattr(old_agent, "tools", None)
    reuse_skills = getattr(old_agent, "skills", None)
    ctx.close_agent_model()
    try:
        with ctx.console.status(
            f"  [dim]Switching to {chosen}...[/dim]",
            spinner="star", spinner_style="#E6C200", speed=0.3,
        ):
            new_agent = create_agent(
                ctx.config,
                plan_mode=ctx.get_plan_mode(),
                confirm_ref=ctx.confirm_ref,
                auto_execute_ref=ctx.auto_execute_ref,
                pending_plan_ref=ctx.pending_plan_ref,
                enter_plan_ref=ctx.enter_plan_ref,
                pending_reason_ref=ctx.pending_reason_ref,
                pending_revise_ref=ctx.pending_revise_ref,
                reuse_storage=reuse_storage,
                reuse_tools=reuse_tools,
                reuse_skills=reuse_skills,
            )
    except Exception as e:
        ctx.config.activate_profile(prev_profile)
        from rich.markup import escape
        ctx.console.print(f"  [error]\u2717 Cannot switch: {escape(str(e))}[/error]")
        return
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    ctx.console.print(
        f"  [success]\u2713 Switched to {chosen}[/success]"
        f" ({ctx.config.provider.value} / {ctx.get_model_id()})"
    )


def cmd_reasoning(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /reasoning command."""
    from hooty.config import Provider, supports_thinking

    if not args:
        cycle = {"off": "auto", "auto": "on", "on": "off"}
        ctx.config.reasoning.mode = cycle[ctx.config.reasoning.mode]
    elif args[0].lower() in ("on", "off", "auto"):
        ctx.config.reasoning.mode = args[0].lower()
    else:
        ctx.console.print("  [error]\u2717 Usage: /reasoning [on|off|auto][/error]")
        return

    mode = ctx.config.reasoning.mode
    active = supports_thinking(ctx.config) and mode in ("on", "auto")
    ctx.config._reasoning_active = active

    if mode == "off":
        ctx.console.print("  [success]\u2713 Reasoning disabled[/success]")
    elif active:
        if ctx.config.provider == Provider.AZURE_OPENAI:
            from hooty.config import REASONING_EFFORT_MAP

            efforts = "/".join(REASONING_EFFORT_MAP.values())
            ctx.console.print(
                f"  [success]\u2713 Reasoning {mode}[/success]"
                f" (effort: {efforts})"
            )
        else:
            from hooty.config import REASONING_LEVEL_BUDGETS

            budgets = "/".join(
                f"{b:,}" for b in REASONING_LEVEL_BUDGETS.values()
            )
            ctx.console.print(
                f"  [success]\u2713 Reasoning {mode}[/success]"
                f" (budget: {budgets} tokens)"
            )
    else:
        ctx.console.print(
            f"  [success]\u2713 Reasoning {mode}[/success]"
            " [dim](inactive \u2014 not supported by current model)[/dim]"
        )
