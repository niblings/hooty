"""Project-related slash commands: /project and subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_project(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /project commands."""
    if not args:
        ctx.console.print("  [dim]/project purge  — Purge orphaned project dirs[/dim]")
        return

    sub = args[0].lower()
    if sub == "purge":
        _cmd_project_purge(ctx)
    else:
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {sub}[/error]")
        ctx.console.print("  [dim]/project purge  — Purge orphaned project dirs[/dim]")


def _cmd_project_purge(ctx: CommandContext) -> None:
    """Purge orphaned project directories."""
    from hooty.project_purge_picker import pick_purge_targets
    from hooty.project_store import find_orphaned_projects, purge_projects

    orphaned = find_orphaned_projects(ctx.config)

    if not orphaned:
        ctx.console.print("  [dim]No orphaned projects found[/dim]")
        return

    chosen = pick_purge_targets(orphaned, ctx.console)

    if not chosen:
        ctx.console.print("  [dim]Cancelled[/dim]")
        return

    dirs = [p.dir_path for p in chosen]
    removed = purge_projects(dirs)
    ctx.console.print(
        f"  [success]\u2713 Purged {removed} project director{'y' if removed == 1 else 'ies'}[/success]"
    )
