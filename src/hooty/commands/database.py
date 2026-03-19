"""Database-related slash commands: /database and subcommands."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_database(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /database commands."""
    if not args:
        _cmd_database_status(ctx)
        return

    sub = args[0].lower()
    if sub == "list":
        _cmd_database_list(ctx)
    elif sub == "connect":
        if len(args) < 2:
            ctx.console.print("  [error]\u2717 Please specify a database name[/error]")
            ctx.console.print("  [dim]Usage: /database connect <name>[/dim]")
            return
        _cmd_database_connect(ctx, args[1])
    elif sub == "disconnect":
        _cmd_database_disconnect(ctx)
    elif sub == "add":
        if len(args) < 3:
            ctx.console.print("  [error]\u2717 Please specify a name and URL[/error]")
            ctx.console.print("  [dim]Usage: /database add <name> <dialect://user:password@host:port/database>[/dim]")
            return
        _cmd_database_add(ctx, args[1], args[2])
    elif sub == "remove":
        if len(args) < 2:
            ctx.console.print("  [error]\u2717 Please specify a database name[/error]")
            ctx.console.print("  [dim]Usage: /database remove <name>[/dim]")
            return
        _cmd_database_remove(ctx, args[1])
    else:
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {sub}[/error]")
        ctx.console.print("  [dim]/database list          \u2014 List databases[/dim]")
        ctx.console.print("  [dim]/database connect <n>   \u2014 Connect[/dim]")
        ctx.console.print("  [dim]/database disconnect    \u2014 Disconnect[/dim]")
        ctx.console.print("  [dim]/database add <n> <url> \u2014 Add database[/dim]")
        ctx.console.print("  [dim]/database remove <n>    \u2014 Remove database[/dim]")


def _cmd_database_status(ctx: CommandContext) -> None:
    """Show current database connection status."""
    if ctx.config.active_db:
        url = ctx.config.databases.get(ctx.config.active_db, "unknown")
        ctx.console.print(f"  Database: [success]{ctx.config.active_db}[/success] ({url})")
    else:
        ctx.console.print("  [dim]Not connected to any database[/dim]")
        if ctx.config.databases:
            ctx.console.print("  [dim]Use /database list to see registered databases[/dim]")
        else:
            ctx.console.print("  [dim]Use /database add <name> <url> to register one (e.g. /database add mydb postgresql://user:pass@host:5432/db)[/dim]")


def _cmd_database_list(ctx: CommandContext) -> None:
    """List registered databases."""
    if not ctx.config.databases:
        ctx.console.print("  [dim]No registered databases[/dim]")
        ctx.console.print("  [dim]Use /database add <name> <url> to add one[/dim]")
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
    ctx.console.print(f"  Registered databases ({len(ctx.config.databases)}):", style="bold")
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
    table.add_column("", width=1, no_wrap=True)
    table.add_column("Name", style="slash_cmd", no_wrap=True)
    table.add_column("URL", no_wrap=True, max_width=60, overflow="ellipsis")

    for name, url in ctx.config.databases.items():
        is_active = name == ctx.config.active_db
        marker = "\u25c0" if is_active else ""
        table.add_row(
            f"[success]{marker}[/success]", name, url,
        )

    ctx.console.print(table)
    ctx.console.print()


def _dispose_and_recreate(ctx: CommandContext) -> None:
    """Dispose SQL engine and recreate the agent."""
    from hooty.tools.sql_tools import dispose_sql_tools

    dispose_sql_tools(ctx.get_agent())
    ctx.close_agent_model()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())


def _cmd_database_connect(ctx: CommandContext, name: str) -> None:
    """Connect to a named database."""
    from hooty.tools.sql_tools import SQLToolsError

    if name not in ctx.config.databases:
        ctx.console.print(f"  [error]\u2717 Database '{name}' is not registered[/error]")
        ctx.console.print("  [dim]Use /database list to see registered databases[/dim]")
        return

    if ctx.config.active_db == name:
        ctx.console.print(f"  [dim]Already connected to {name}[/dim]")
        return

    prev_active = ctx.config.active_db
    ctx.config.active_db = name
    try:
        _dispose_and_recreate(ctx)
    except SQLToolsError as e:
        ctx.config.active_db = prev_active
        ctx.console.print(f"  [error]\u2717 {e}[/error]")
        return
    ctx.console.print(f"  [success]\u2713 Connected to '{name}'[/success]")


def _cmd_database_disconnect(ctx: CommandContext) -> None:
    """Disconnect from the current database."""
    if not ctx.config.active_db:
        ctx.console.print("  [dim]Not connected to any database[/dim]")
        return

    old_name = ctx.config.active_db
    ctx.config.active_db = None
    _dispose_and_recreate(ctx)
    ctx.console.print(f"  [success]\u2713 Disconnected from '{old_name}'[/success]")


def _cmd_database_add(ctx: CommandContext, name: str, db_url: str) -> None:
    """Add a new database connection to databases.yaml."""
    from hooty.config import save_databases

    if name in ctx.config.databases:
        ctx.console.print(f"  [error]\u2717 Database '{name}' already exists[/error]")
        return

    ctx.config.databases[name] = db_url
    save_databases(ctx.config)
    ctx.console.print(f"  [success]\u2713 Added database '{name}'[/success]")
    ctx.console.print(f"  [dim]Use /database connect {name} to connect[/dim]")


def _cmd_database_remove(ctx: CommandContext, name: str) -> None:
    """Remove a database connection from databases.yaml."""
    from hooty.config import save_databases

    if name not in ctx.config.databases:
        ctx.console.print(f"  [error]\u2717 Database '{name}' is not registered[/error]")
        return

    if ctx.config.active_db == name:
        ctx.config.active_db = None
        _dispose_and_recreate(ctx)

    del ctx.config.databases[name]
    save_databases(ctx.config)
    ctx.console.print(f"  [success]\u2713 Removed database '{name}'[/success]")
