"""Miscellaneous slash commands: /help, /quit, /safe, /unsafe, /rescan."""

from __future__ import annotations

import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext

_GOODBYE_MESSAGES = [
    "Goodbye! \U0001f989",
    "See you later! \U0001f989",
    "Happy coding! \U0001f989",
    "Hoot hoot, bye! \U0001f989",
    "Until next time! \U0001f989",
]


def cmd_help(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Show help information."""
    ctx.console.print()
    ctx.console.print("  Hooty Commands:", style="bold")
    ctx.console.print()
    commands = [
        ("/add-dir [path]", "Add working directory for read/write"),
        ("/agents", "List available sub-agents"),
        ("/agents info <name>", "Show sub-agent details"),
        ("/agents reload", "Reload agents.yaml"),
        ("/auto", "Toggle auto mode transitions"),
        ("/code", "Switch to coding mode"),
        ("/compact", "Compact session history"),
        ("/context", "Show context files & window usage"),
        ("/copy", "Copy last response to clipboard"),
        ("/database", "Show current DB connection"),
        ("/diff", "Show file changes made in this session"),
        ("/database add <name> <url>", "Add database (e.g. /database add mydb postgresql://user:pass@host:5432/db)"),
        ("/database connect <name>", "Connect to a database"),
        ("/database disconnect", "Disconnect from database"),
        ("/database list", "List registered databases"),
        ("/database remove <name>", "Remove a database"),
        ("/fork", "Fork current session"),
        ("/github", "Toggle GitHub tools on/off"),
        ("/help", "Show this help"),
        ("/hooks", "Manage lifecycle hooks"),
        ("/hooks list", "List registered hooks"),
        ("/hooks on|off", "Enable/disable hooks globally"),
        ("/hooks reload", "Reload hooks.yaml"),
        ("/list-dirs", "Show allowed working directories"),
        ("/mcp", "List MCP servers"),
        ("/mcp reload", "Reload mcp.yaml and reconnect"),
        ("/memory", "Show memory status"),
        ("/memory list [--global]", "List memories"),
        ("/memory search <keyword>", "Search memories"),
        ("/memory edit [--global]", "Delete / move memories"),
        ("/model", "Switch model profile"),
        ("/new", "Start a new session"),
        ("/plan", "Switch to planning mode"),
        ("/plans", "Browse plans (view + delete)"),
        ("/plans search <keyword>", "Search plans by keyword"),
        ("/project purge", "Purge orphaned project dirs"),
        ("/quit", "Exit Hooty"),
        ("/reasoning", "Toggle reasoning mode (off \u2192 on \u2192 auto)"),
        ("/reasoning on|off|auto", "Set reasoning mode"),
        ("/rescan", "Rescan PATH for available commands"),
        ("/review", "Review source code (interactive)"),
        ("/rewind", "Revert file changes and conversation history"),
        ("/safe", "Enable safe mode"),
        ("/session", "Show current session ID"),
        ("/session agents", "Sub-agent run breakdown"),
        ("/session list", "List saved sessions"),
        ("/session purge [days]", "Purge old sessions (default: 90 days)"),
        ("/session resume <id>", "Restore a session"),
        ("/skills", "Manage agent skills (picker)"),
        ("/skills list", "List all skills"),
        ("/skills info <name>", "Show skill details"),
        ("/skills invoke <name>", "Manually invoke a skill"),
        ("/skills add <path>", "Add external skill directory"),
        ("/skills remove <path>", "Remove external skill directory"),
        ("/skills on / off", "Enable/disable skills globally"),
        ("/skills reload", "Reload skills from disk"),
        ("/unsafe", "Disable safe mode"),
        ("/websearch", "Toggle web search tools on/off"),
    ]
    for cmd, desc in commands:
        ctx.console.print(f"  [slash_cmd]{cmd:<25}[/slash_cmd] [slash_desc]{desc}[/slash_desc]")
    ctx.console.print()
    ctx.console.print("  Shell Escape:", style="bold")
    ctx.console.print()
    ctx.console.print(f"  [slash_cmd]{'!<command>':<25}[/slash_cmd] [slash_desc]Run shell command directly (e.g. !git status)[/slash_desc]")
    ctx.console.print()
    ctx.console.print("  Keyboard:", style="bold")
    ctx.console.print(f"  [slash_cmd]{'Shift+Tab':<25}[/slash_cmd] [slash_desc]Toggle planning/coding mode[/slash_desc]")
    ctx.console.print(f"  [slash_cmd]{'Ctrl+C':<25}[/slash_cmd] [slash_desc]Cancel current response[/slash_desc]")
    ctx.console.print(f"  [slash_cmd]{'Ctrl+D':<25}[/slash_cmd] [slash_desc]Exit Hooty (press twice)[/slash_desc]")
    ctx.console.print()


def cmd_quit(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Exit Hooty."""
    # NOTE: Do NOT call shutdown_loop() here.  The finally block in
    # Repl.run() handles _fire_session_end() first, then _shutdown_loop().
    # Calling shutdown_loop() early closes the event loop before the
    # SessionEnd hook can run, causing ProactorEventLoop errors on Windows.
    ctx.console.print()
    # Show resume hint before goodbye message
    if ctx.get_session_dir_created():
        sid = ctx.get_session_id()
        ctx.console.print(
            f"  [dim]Resume this session with:[/dim] "
            f"[bold]hooty --resume {sid}[/bold]"
        )
    msg = random.choice(_GOODBYE_MESSAGES)
    ctx.console.print(f"  [dim]{msg}[/dim]")
    ctx.console.print()
    ctx.set_running(False)


def cmd_safe(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Enable safe mode."""
    ctx.confirm_ref[0] = True
    ctx.console.print("  [success]\u2713 Safe mode enabled[/success]")


def cmd_unsafe(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Disable safe mode."""
    ctx.confirm_ref[0] = False
    ctx.console.print("  [success]\u2713 Safe mode disabled[/success]")


def cmd_copy(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Copy last LLM response to clipboard."""
    n = 1
    if args:
        try:
            n = int(args[0])
        except ValueError:
            ctx.console.print("  [warning]Usage: /copy [N][/warning]")
            return
    if n < 1:
        ctx.console.print("  [warning]N must be >= 1[/warning]")
        return

    if n == 1:
        text = ctx.get_last_response_text()
    else:
        from hooty.conversation_log import load_recent_history

        entries = load_recent_history(ctx.config.project_dir, ctx.get_session_id(), n)
        if len(entries) < n:
            text = ""
        else:
            text = entries[-n].get("output", "")

    if not text:
        ctx.console.print("  [warning]No response to copy.[/warning]")
        return

    from hooty.clipboard import write_clipboard

    ok, err = write_clipboard(text)
    if ok:
        label = "" if n == 1 else f" (#{n})"
        ctx.console.print(f"  [success]✓ Copied{label} to clipboard[/success] [dim]({len(text)} chars)[/dim]")
    else:
        ctx.console.print(f"  [error]✗ {err}[/error]")


def cmd_rescan(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Clear command cache and recreate agent with fresh PATH scan."""
    from hooty.tools.coding_tools import clear_command_cache

    clear_command_cache()
    try:
        from hooty.tools.powershell_tools import _detect_powershell

        _detect_powershell.cache_clear()
    except (ImportError, AttributeError):
        pass
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.console.print("  [success]\u2713 PATH rescanned[/success]")
