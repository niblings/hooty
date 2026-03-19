"""Skills-related slash commands: /skills and subcommands."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_skills(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /skills commands."""
    if args:
        sub = args[0].lower()
        if sub == "list":
            _cmd_skills_list(ctx)
            return
        if sub == "info":
            _cmd_skills_info(ctx, args[1:])
            return
        if sub == "invoke":
            _cmd_skills_invoke(ctx, args[1:])
            return
        if sub == "reload":
            _cmd_skills_reload(ctx)
            return
        if sub == "on":
            _cmd_skills_on(ctx)
            return
        if sub == "off":
            _cmd_skills_off(ctx)
            return
        if sub == "add":
            _cmd_skills_add(ctx, args[1:])
            return
        if sub == "remove":
            _cmd_skills_remove(ctx, args[1:])
            return
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {args[0]}[/error]")
        ctx.console.print("  [dim]/skills              \u2014 Interactive skill picker[/dim]")
        ctx.console.print("  [dim]/skills list         \u2014 List all skills[/dim]")
        ctx.console.print("  [dim]/skills info <n>     \u2014 Show skill details[/dim]")
        ctx.console.print("  [dim]/skills invoke <n> [args] \u2014 Invoke skill manually[/dim]")
        ctx.console.print("  [dim]/skills add <path>   \u2014 Add external skill directory[/dim]")
        ctx.console.print("  [dim]/skills remove <path> \u2014 Remove external skill directory[/dim]")
        ctx.console.print("  [dim]/skills reload       \u2014 Reload from disk[/dim]")
        ctx.console.print("  [dim]/skills on|off       \u2014 Enable/disable globally[/dim]")
        return

    _cmd_skills_picker(ctx)


def _cmd_skills_picker(ctx: CommandContext) -> None:
    """Interactive skill picker."""
    if not ctx.config.skills.enabled:
        ctx.console.print("  [dim]Skills are disabled. Use /skills on to enable.[/dim]")
        return

    from hooty.skill_picker import pick_skills
    from hooty.skill_store import discover_skills, save_disabled_skills

    skills = discover_skills(ctx.config)
    if not skills:
        ctx.console.print("  [dim]No skills found[/dim]")
        return

    result = pick_skills(skills, ctx.console)
    if result is None:
        ctx.console.print("  [dim]Cancelled[/dim]")
        return

    disabled: set[str] = set()
    for i, skill in enumerate(skills):
        if not result[i] and not skill.disable_model_invocation:
            disabled.add(skill.name)

    save_disabled_skills(ctx.config, disabled)

    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())

    enabled_count = sum(
        1 for i, s in enumerate(skills)
        if result[i] and not s.disable_model_invocation
    )
    ctx.console.print(f"  [success]\u2713 Skills updated ({enabled_count} enabled)[/success]")


def _cmd_skills_list(ctx: CommandContext) -> None:
    """List all discovered skills."""
    if not ctx.config.skills.enabled:
        ctx.console.print("  [dim]Skills are disabled. Use /skills on to enable.[/dim]")
        return

    from hooty.skill_store import discover_skills

    skills = discover_skills(ctx.config)
    if not skills:
        ctx.console.print("  [dim]No skills found[/dim]")
        return

    from rich.box import Box
    from rich.table import Table

    _HEADER_ONLY = Box(
        "    \n"
        "    \n"
        " ── \n"
        "    \n"
        "    \n"
        "    \n"
        "    \n"
        "    \n"
    )

    ctx.console.print()
    ctx.console.print(f"  Skills ({len(skills)}):", style="bold")
    ctx.console.print()

    table = Table(
        show_header=True,
        show_edge=False,
        show_lines=False,
        pad_edge=False,
        box=_HEADER_ONLY,
        border_style="dim",
        padding=(0, 1),
        expand=False,
        header_style="dim",
    )
    table.add_column("State", no_wrap=True)
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Description", no_wrap=True, max_width=50, overflow="ellipsis")

    for s in skills:
        if s.disable_model_invocation:
            state = "[dim]\u2298 manual[/dim]"
        elif s.enabled:
            state = "[bold #E6C200]ON[/bold #E6C200]"
        else:
            state = "[dim]OFF[/dim]"

        source = s.source
        for full, short in [
            ("project (.claude)", ".claude"),
            ("project (.github)", ".github"),
            ("project (.hooty)", ".hooty"),
        ]:
            if source == full:
                source = short
                break

        table.add_row(state, s.name, source, s.description)

    ctx.console.print(table)
    ctx.console.print()


def _cmd_skills_info(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Show detailed info about a skill."""
    if not args:
        ctx.console.print("  [error]\u2717 Usage: /skills info <name>[/error]")
        return

    from hooty.skill_store import discover_skills

    name = args[0]
    skills = discover_skills(ctx.config)
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        ctx.console.print(f"  [error]\u2717 Skill not found: {name}[/error]")
        available = ", ".join(s.name for s in skills)
        if available:
            ctx.console.print(f"  [dim]Available: {available}[/dim]")
        return

    ctx.console.print()
    ctx.console.print(f"  [bold cyan]{skill.name}[/bold cyan]")
    ctx.console.print(f"  Source: {skill.source}")
    ctx.console.print(f"  Path:   {skill.source_path}")
    if skill.description:
        ctx.console.print(f"  Description: {skill.description}")

    state_parts = []
    if skill.disable_model_invocation:
        state_parts.append("manual-only")
    if not skill.user_invocable:
        state_parts.append("auto-only")
    if skill.enabled:
        state_parts.append("enabled")
    else:
        state_parts.append("disabled")
    ctx.console.print(f"  State: {', '.join(state_parts)}")

    if skill.scripts:
        ctx.console.print(f"  Scripts: {', '.join(skill.scripts)}")
    if skill.references:
        ctx.console.print(f"  References: {', '.join(skill.references)}")

    if skill.instructions:
        lines = skill.instructions.split("\n")[:5]
        ctx.console.print()
        ctx.console.print("  Instructions (preview):", style="bold")
        for line in lines:
            ctx.console.print(f"    {line}")
        if len(skill.instructions.split("\n")) > 5:
            ctx.console.print("    [dim]...[/dim]")
    ctx.console.print()


def _cmd_skills_invoke(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Manually invoke a skill (sends instructions to agent)."""
    if not args:
        ctx.console.print("  [error]\u2717 Usage: /skills invoke <name> [args][/error]")
        return

    from hooty.skill_store import discover_skills, load_skill_instructions

    name = args[0]
    invoke_args = " ".join(args[1:]) if len(args) > 1 else ""

    skills = discover_skills(ctx.config)
    skill = next((s for s in skills if s.name == name), None)
    if skill is None:
        ctx.console.print(f"  [error]\u2717 Skill not found: {name}[/error]")
        return

    instructions = load_skill_instructions(skill, invoke_args)
    ctx.console.print(f"  [success]\u2713 Invoking skill: {name}[/success]")
    ctx.set_pending_skill_message(instructions)


def _cmd_skills_reload(ctx: CommandContext) -> None:
    """Reload skills from disk and recreate agent."""
    if not ctx.config.skills.enabled:
        ctx.console.print("  [dim]Skills are disabled. Use /skills on to enable.[/dim]")
        return

    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())

    from hooty.repl_ui import _skills_summary
    from hooty.skill_store import discover_skills

    skills = discover_skills(ctx.config)
    ctx.console.print(f"  [success]\u2713 Skills reloaded ({_skills_summary(skills)})[/success]")
    ctx.refresh_skill_commands()


def _cmd_skills_on(ctx: CommandContext) -> None:
    """Enable skills globally."""
    ctx.config.skills.enabled = True
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())

    from hooty.repl_ui import _skills_summary
    from hooty.skill_store import discover_skills

    skills = discover_skills(ctx.config)
    ctx.console.print(f"  [success]\u2713 Skills ON ({_skills_summary(skills)})[/success]")
    ctx.refresh_skill_commands()


def _cmd_skills_off(ctx: CommandContext) -> None:
    """Disable skills globally."""
    ctx.config.skills.enabled = False
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    ctx.console.print("  [success]\u2713 Skills OFF[/success]")
    ctx.refresh_skill_commands()


def _cmd_skills_add(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Add an external skill directory."""
    if not args:
        ctx.console.print("  [error]\u2717 Usage: /skills add [--global] <path>[/error]")
        return

    is_global = "--global" in args
    remaining = [a for a in args if a != "--global"]

    if not remaining:
        ctx.console.print("  [error]\u2717 Usage: /skills add [--global] <path>[/error]")
        return

    target = Path(remaining[0]).resolve()
    if not target.is_dir():
        ctx.console.print(f"  [error]\u2717 Directory not found: {target}[/error]")
        return

    from hooty.skill_store import (
        load_extra_paths,
        load_global_extra_paths,
        save_extra_paths,
        save_global_extra_paths,
    )

    resolved = str(target)
    if is_global:
        paths = load_global_extra_paths(ctx.config)
        if resolved in paths:
            ctx.console.print(f"  [dim]Already registered (global): {target}[/dim]")
            return
        paths.append(resolved)
        save_global_extra_paths(ctx.config, paths)
        scope = "global"
    else:
        paths = load_extra_paths(ctx.config)
        if resolved in paths:
            ctx.console.print(f"  [dim]Already registered (project): {target}[/dim]")
            return
        paths.append(resolved)
        save_extra_paths(ctx.config, paths)
        scope = "project"

    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    ctx.console.print(f"  [success]\u2713 Added skill path ({scope}): {target}[/success]")


def _cmd_skills_remove(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Remove an external skill directory."""
    if not args:
        ctx.console.print("  [error]\u2717 Usage: /skills remove [--global] <path>[/error]")
        return

    is_global = "--global" in args
    remaining = [a for a in args if a != "--global"]

    if not remaining:
        ctx.console.print("  [error]\u2717 Usage: /skills remove [--global] <path>[/error]")
        return

    target = Path(remaining[0]).resolve()

    from hooty.skill_store import (
        load_extra_paths,
        load_global_extra_paths,
        save_extra_paths,
        save_global_extra_paths,
    )

    resolved = str(target)
    if is_global:
        paths = load_global_extra_paths(ctx.config)
        if resolved not in paths:
            ctx.console.print(f"  [error]\u2717 Not registered (global): {target}[/error]")
            return
        paths.remove(resolved)
        save_global_extra_paths(ctx.config, paths)
        scope = "global"
    else:
        paths = load_extra_paths(ctx.config)
        if resolved not in paths:
            ctx.console.print(f"  [error]\u2717 Not registered (project): {target}[/error]")
            return
        paths.remove(resolved)
        save_extra_paths(ctx.config, paths)
        scope = "project"

    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    ctx.console.print(f"  [success]\u2713 Removed skill path ({scope}): {target}[/success]")
