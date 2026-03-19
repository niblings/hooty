"""Plans slash commands: /plans and subcommands."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_plans(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /plans commands."""
    if not args:
        _cmd_plans_picker(ctx)
        return

    sub = args[0].lower()
    if sub == "search":
        keyword = " ".join(args[1:])
        if not keyword:
            ctx.console.print("  [error]\u2717 Please specify a keyword[/error]")
            ctx.console.print("  [dim]Usage: /plans search <keyword>[/dim]")
            return
        _cmd_plans_search(ctx, keyword)
    else:
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {sub}[/error]")
        ctx.console.print("  [dim]/plans              \u2014 Browse plans (view + delete)[/dim]")
        ctx.console.print("  [dim]/plans search <kw>  \u2014 Search plans by keyword[/dim]")


def _cmd_plans_picker(ctx: CommandContext) -> None:
    """Unified plan picker with view and delete."""
    from hooty.plan_picker import pick_plans
    from hooty.plan_store import delete_plans, list_plans

    while True:
        plans = list_plans(ctx.config)
        if not plans:
            ctx.console.print("  [dim]No saved plans[/dim]")
            return

        action = pick_plans(plans, ctx.console)
        if action is None:
            return

        verb, ids = action
        if verb == "view":
            _cmd_plans_view(ctx, ids[0])
            continue
        if verb == "delete":
            deleted = delete_plans(ctx.config, ids)
            ctx.console.print(f"  [success]\u2713 Deleted {deleted} plan(s)[/success]")
            continue


def _cmd_plans_search(ctx: CommandContext, keyword: str) -> None:
    """Search plans by keyword."""
    from hooty.plan_store import format_plan_for_display, search_plans

    results = search_plans(ctx.config, keyword)
    if not results:
        ctx.console.print(f"  [dim]No plans matching '{keyword}'[/dim]")
        return

    ctx.console.print()
    ctx.console.print(f"  Search results for '{keyword}' ({len(results)}):", style="bold")
    ctx.console.print()
    for idx, plan in enumerate(results, 1):
        info = format_plan_for_display(plan)
        ctx.console.print(
            f"  {idx:>3}  "
            f"{info['status_icon']} "
            f"[magenta]{info['short_id']}[/magenta]  "
            f"[dim]{info['created_at']}[/dim]  "
            f"{info['size']:>6}  "
            f"{info['summary']}"
        )
    ctx.console.print()


def _cmd_plans_view(ctx: CommandContext, id_prefix: str) -> None:
    """View a plan by ID prefix."""
    from rich.markdown import Markdown

    from hooty.plan_store import get_plan

    plan = get_plan(ctx.config, id_prefix)
    if not plan:
        ctx.console.print(f"  [error]\u2717 No plan matching '{id_prefix}'[/error]")
        return

    try:
        text = plan.file_path.read_text(encoding="utf-8")
    except Exception:
        ctx.console.print("  [error]\u2717 Could not read plan file[/error]")
        return

    text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.DOTALL)

    ctx.console.print()
    from hooty.plan_store import PLAN_STATUS_ICONS
    status_icon = PLAN_STATUS_ICONS.get(plan.status, "?")
    info = f"{status_icon} [magenta]{plan.short_id}[/magenta]  [dim]{plan.created_at.strftime('%Y-%m-%d %H:%M')}[/dim]"
    if plan.summary:
        info += f"  {plan.summary}"
    ctx.console.print(f"  {info}")
    ctx.console.print()
    ctx.console.print(Markdown(text))
    ctx.console.print()
