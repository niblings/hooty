"""Memory-related slash commands: /memory and subcommands."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_memory(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /memory commands."""
    if not args:
        _cmd_memory_status(ctx)
        return

    sub = args[0].lower()
    if sub == "list":
        is_global = "--global" in args
        _cmd_memory_list(ctx, is_global)
    elif sub == "search":
        keyword = " ".join(args[1:])
        if not keyword:
            ctx.console.print("  [error]\u2717 Please specify a keyword[/error]")
            ctx.console.print("  [dim]Usage: /memory search <keyword>[/dim]")
            return
        _cmd_memory_search(ctx, keyword)
    elif sub == "edit":
        is_global = "--global" in args
        _cmd_memory_manage(ctx, is_global)
    else:
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {sub}[/error]")
        ctx.console.print("  [dim]/memory             \u2014 Show status[/dim]")
        ctx.console.print("  [dim]/memory list        \u2014 List project memories[/dim]")
        ctx.console.print("  [dim]/memory list --global \u2014 List global memories[/dim]")
        ctx.console.print("  [dim]/memory search <kw> \u2014 Search memories[/dim]")
        ctx.console.print("  [dim]/memory edit        \u2014 Delete / move project memories[/dim]")
        ctx.console.print("  [dim]/memory edit --global \u2014 Delete / move global memories[/dim]")


def _cmd_memory_status(ctx: CommandContext) -> None:
    """Show memory status summary."""
    from hooty.memory_store import count_memories, get_last_updated

    ctx.console.print()

    proj_count = 0
    proj_db = ctx.config.project_memory_db_path
    if os.path.exists(proj_db):
        try:
            proj_count = count_memories(proj_db)
        except Exception:
            pass
    ctx.console.print(
        f"  Project memory: {proj_count} entries  "
        f"[dim]({proj_db})[/dim]"
    )

    global_count = 0
    global_db = ctx.config.global_memory_db_path
    if os.path.exists(global_db):
        try:
            global_count = count_memories(global_db)
        except Exception:
            pass
    ctx.console.print(
        f"  Global memory:  {global_count} entries  "
        f"[dim]({global_db})[/dim]"
    )

    last_updated = None
    for db_path in [proj_db, global_db]:
        if os.path.exists(db_path):
            try:
                ts = get_last_updated(db_path)
                if ts and (last_updated is None or ts > last_updated):
                    last_updated = ts
            except Exception:
                pass

    if last_updated:
        from hooty.memory_store import _relative_time

        ctx.console.print(f"  Last updated:   {_relative_time(last_updated)}")

    ctx.console.print()


def _cmd_memory_list(ctx: CommandContext, is_global: bool = False) -> None:
    """List memories in table format."""
    from hooty.config import project_dir_name
    from hooty.memory_store import format_memory_for_display, list_memories

    if is_global:
        db_path = ctx.config.global_memory_db_path
        label = "Global"
    else:
        db_path = ctx.config.project_memory_db_path
        proj_name = project_dir_name(Path(ctx.config.working_directory))
        label = f"Project ({proj_name})"

    if not os.path.exists(db_path):
        ctx.console.print(f"  [dim]No {label.lower()} memories[/dim]")
        return

    try:
        memories = list_memories(db_path)
    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Failed to list memories: {e}[/error]")
        return

    if not memories:
        ctx.console.print(f"  [dim]No {label.lower()} memories[/dim]")
        return

    from rich.box import Box
    from rich.padding import Padding
    from rich.table import Table

    ctx.console.print()
    ctx.console.print(f"  {label} memories:", style="bold")
    ctx.console.print()

    # Minimal box: only a ─ line under the header
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
    table.add_column("ID", style="magenta", no_wrap=True, min_width=10)
    table.add_column("Topics", style="dim", max_width=20, overflow="ellipsis", no_wrap=True)
    table.add_column("Memory", max_width=36, overflow="ellipsis", no_wrap=True)
    table.add_column("Updated", style="dim", no_wrap=True)

    for m in memories:
        info = format_memory_for_display(m)
        table.add_row(
            info["short_id"],
            info["topics"],
            info["memory_text"],
            info["updated_at"],
        )

    ctx.console.print(Padding(table, (0, 0, 0, 2)))

    ctx.console.print()


def _cmd_memory_search(ctx: CommandContext, keyword: str) -> None:
    """Search memories across project and global stores."""
    from hooty.memory_store import format_memory_for_display, search_memories

    results: list[tuple[str, dict[str, str]]] = []

    proj_db = ctx.config.project_memory_db_path
    if os.path.exists(proj_db):
        try:
            for m in search_memories(proj_db, keyword):
                results.append(("project", format_memory_for_display(m)))
        except Exception:
            pass

    global_db = ctx.config.global_memory_db_path
    if os.path.exists(global_db):
        try:
            for m in search_memories(global_db, keyword):
                results.append(("global", format_memory_for_display(m)))
        except Exception:
            pass

    if not results:
        ctx.console.print(f"  [dim]No memories matching '{keyword}'[/dim]")
        return

    from rich.box import Box
    from rich.padding import Padding
    from rich.table import Table

    ctx.console.print()
    ctx.console.print(f"  Found {len(results)} memor{'y' if len(results) == 1 else 'ies'}:", style="bold")
    ctx.console.print()

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
    table.add_column("Scope", style="dim", no_wrap=True)
    table.add_column("ID", style="magenta", no_wrap=True, min_width=10)
    table.add_column("Topics", style="dim", max_width=18, overflow="ellipsis", no_wrap=True)
    table.add_column("Memory", max_width=36, overflow="ellipsis", no_wrap=True)
    table.add_column("Updated", style="dim", no_wrap=True)

    for scope, info in results:
        table.add_row(
            scope,
            info["short_id"],
            info["topics"],
            info["memory_text"],
            info["updated_at"],
        )

    ctx.console.print(Padding(table, (0, 0, 0, 2)))


def _cmd_memory_manage(ctx: CommandContext, is_global: bool = False) -> None:
    """Interactive memory management: delete or move between scopes."""
    from hooty.memory_picker import pick_memory_targets
    from hooty.memory_store import delete_memories, list_memories, move_memories

    src_db = ctx.config.global_memory_db_path if is_global else ctx.config.project_memory_db_path
    scope = "global" if is_global else "project"

    if not os.path.exists(src_db):
        ctx.console.print(f"  [dim]No {scope} memories[/dim]")
        return

    try:
        memories = list_memories(src_db)
    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Failed to list memories: {e}[/error]")
        return

    if not memories:
        ctx.console.print(f"  [dim]No {scope} memories[/dim]")
        return

    result = pick_memory_targets(memories, ctx.console, is_global=is_global)

    if not result:
        ctx.console.print("  [dim]Cancelled[/dim]")
        return

    action, chosen_ids = result

    try:
        if action == "delete":
            deleted = delete_memories(src_db, chosen_ids)
            ctx.console.print(
                f"  [success]\u2713 Deleted {deleted}"
                f" memor{'y' if deleted == 1 else 'ies'}[/success]"
            )
        elif action == "move":
            dst_db = ctx.config.project_memory_db_path if is_global else ctx.config.global_memory_db_path
            dst_label = "project" if is_global else "global"
            moved = move_memories(src_db, dst_db, chosen_ids)
            ctx.console.print(
                f"  [success]\u2713 Moved {moved}"
                f" memor{'y' if moved == 1 else 'ies'}"
                f" {scope} \u2192 {dst_label}[/success]"
            )
        ctx.console.print("  [dim]Changes take effect from the next session[/dim]")
    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Failed to {action} memories: {e}[/error]")


