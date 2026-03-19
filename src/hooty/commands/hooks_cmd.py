"""Hooks slash commands: /hooks and subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_hooks(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /hooks commands."""
    if args:
        sub = args[0].lower()
        if sub == "list":
            _cmd_hooks_list(ctx)
            return
        if sub == "on":
            _cmd_hooks_on(ctx)
            return
        if sub == "off":
            _cmd_hooks_off(ctx)
            return
        if sub == "reload":
            _cmd_hooks_reload(ctx)
            return
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {args[0]}[/error]")
        ctx.console.print("  [dim]/hooks              \u2014 Interactive hook picker[/dim]")
        ctx.console.print("  [dim]/hooks list         \u2014 List registered hooks[/dim]")
        ctx.console.print("  [dim]/hooks reload       \u2014 Reload from disk[/dim]")
        ctx.console.print("  [dim]/hooks on|off       \u2014 Enable/disable globally[/dim]")
        return

    _cmd_hooks_picker(ctx)


def _cmd_hooks_picker(ctx: CommandContext) -> None:
    """Interactive hook picker."""
    if not ctx.config.hooks_enabled:
        ctx.console.print("  [dim]Hooks are disabled. Use /hooks on to enable.[/dim]")
        return

    from hooty.hooks import save_disabled_hooks
    from hooty.hooks_picker import pick_hooks

    hooks_config = ctx.get_hooks_config()
    items: list[tuple[str, object]] = []
    for event_name, entries in hooks_config.items():
        for entry in entries:
            items.append((event_name, entry))

    if not items:
        ctx.console.print("  [dim]No hooks registered[/dim]")
        return

    result = pick_hooks(items, ctx.console)
    if result is None:
        ctx.console.print("  [dim]Cancelled.[/dim]")
        return

    disabled: set[str] = set()
    for i, (event_name, entry) in enumerate(items):
        entry.enabled = result[i]
        if not result[i]:
            disabled.add(f"{event_name}:{entry.key}")

    save_disabled_hooks(ctx.config, disabled)
    enabled_count = sum(1 for r in result if r)
    ctx.console.print(f"  [success]\u2713 Hooks updated ({enabled_count}/{len(items)} enabled)[/success]")


def _cmd_hooks_list(ctx: CommandContext) -> None:
    """List all registered hooks."""
    if not ctx.config.hooks_enabled:
        ctx.console.print("  [dim]Hooks are disabled. Use /hooks on to enable.[/dim]")
        return

    hooks_config = ctx.get_hooks_config()
    total = sum(len(entries) for entries in hooks_config.values())
    if total == 0:
        ctx.console.print("  [dim]No hooks registered[/dim]")
        return

    ctx.console.print()
    ctx.console.print(f"  Hooks ({total} registered, enabled)", style="bold")
    ctx.console.print()

    for event_name, entries in hooks_config.items():
        ctx.console.print(f"  [cyan]{event_name}[/cyan]")
        for entry in entries:
            mark = "\u2713" if entry.enabled else "\u2717"
            style = "dim" if not entry.enabled else ""
            extras: list[str] = []
            if entry.source:
                extras.append(entry.source)
            if entry.matcher:
                extras.append(entry.matcher)
            if entry.blocking:
                extras.append("blocking")
            extras.append(f"timeout: {entry.timeout}s")
            suffix = "  ".join(extras)
            cmd = entry.command.strip().split("\n")[0]
            if len(cmd) > 50:
                cmd = cmd[:47] + "..."
            line = Text(f"    {mark} {cmd}  {suffix}")
            if style == "dim":
                line.stylize("dim")
            ctx.console.print(line)
        ctx.console.print()


def _cmd_hooks_on(ctx: CommandContext) -> None:
    """Enable hooks globally."""
    ctx.config.hooks_enabled = True
    ctx.load_hooks_config()
    hooks_config = ctx.get_hooks_config()
    total = sum(len(e) for e in hooks_config.values())
    ctx.console.print(f"  [success]\u2713 Hooks ON ({total} registered)[/success]")


def _cmd_hooks_off(ctx: CommandContext) -> None:
    """Disable hooks globally."""
    ctx.config.hooks_enabled = False
    ctx.set_hooks_config({})
    ctx.console.print("  [success]\u2713 Hooks OFF[/success]")


def _cmd_hooks_reload(ctx: CommandContext) -> None:
    """Reload hooks configuration from disk."""
    ctx.load_hooks_config()
    hooks_config = ctx.get_hooks_config()
    total = sum(len(e) for e in hooks_config.values())
    ctx.console.print(f"  [success]\u2713 Hooks reloaded ({total} registered)[/success]")
