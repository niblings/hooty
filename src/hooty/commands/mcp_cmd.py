"""MCP slash commands: /mcp and subcommands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from hooty.commands import CommandContext
    from hooty.config import AppConfig


def cmd_mcp(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /mcp commands."""
    if args:
        sub = args[0].lower()
        if sub == "reload":
            _cmd_mcp_reload(ctx)
            return
        if sub == "list":
            _cmd_mcp_list(ctx)
            return
        if sub == "add":
            _cmd_mcp_add(ctx, args[1:])
            return
        if sub == "remove":
            _cmd_mcp_remove(ctx, args[1:])
            return
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {args[0]}[/error]")
        _print_mcp_help(ctx)
        return

    _cmd_mcp_picker(ctx)


def _print_mcp_help(ctx: CommandContext) -> None:
    ctx.console.print("  [dim]/mcp                                    \u2014 Interactive server picker[/dim]")
    ctx.console.print("  [dim]/mcp list                               \u2014 List MCP servers[/dim]")
    ctx.console.print(
        "  [dim]/mcp add [options] <name> <command|url>  \u2014 Add server[/dim]"
    )
    ctx.console.print(
        "  [dim]/mcp remove [--global] <name>             \u2014 Remove server[/dim]"
    )
    ctx.console.print("  [dim]/mcp reload                             \u2014 Reload mcp.yaml[/dim]")


# -- State management helpers ------------------------------------------------


def _load_mcp_state(config: "AppConfig") -> dict:
    path = config.mcp_state_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_mcp_state(config: "AppConfig", state: dict) -> None:
    from hooty.concurrency import atomic_write_text

    config.project_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config.mcp_state_path, json.dumps(state, indent=2) + "\n")


def load_disabled_mcp_servers(config: "AppConfig") -> set[str]:
    return set(_load_mcp_state(config).get("disabled", []))


def save_disabled_mcp_servers(config: "AppConfig", disabled: set[str]) -> None:
    state = _load_mcp_state(config)
    state["disabled"] = sorted(disabled)
    _save_mcp_state(config, state)


# -- YAML file helpers -------------------------------------------------------


def _mcp_yaml_path(config: "AppConfig", scope: str) -> Path:
    """Return the mcp.yaml path for the given scope."""
    if scope == "global":
        return config.mcp_file_path
    return config.mcp_project_file_path


def _load_mcp_yaml(path: Path) -> dict[str, dict[str, Any]]:
    """Load servers dict from an mcp.yaml file. Returns empty dict if missing."""
    from hooty.config import _load_yaml_file

    if not path.exists():
        return {}
    data = _load_yaml_file(path)
    if isinstance(data, dict) and isinstance(data.get("servers"), dict):
        return data["servers"]
    return {}


def _save_mcp_yaml(path: Path, servers: dict[str, dict[str, Any]]) -> None:
    """Write servers dict to mcp.yaml atomically."""
    from hooty.concurrency import atomic_write_text

    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(
        {"servers": servers},
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    atomic_write_text(path, content)


# -- Add / Remove subcommands -----------------------------------------------


def _parse_add_options(
    args: list[str],
) -> tuple[bool, dict[str, str], dict[str, str], str | None, list[str]]:
    """Parse --global, -e, --header, --transport options from args.

    Returns (is_global, env_dict, headers_dict, transport, remaining_args).
    """
    is_global = False
    env: dict[str, str] = {}
    headers: dict[str, str] = {}
    transport: str | None = None
    rest: list[str] = []
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--global":
            is_global = True
            i += 1
            continue
        if tok in ("-e", "--env") and i + 1 < len(args):
            pair = args[i + 1]
            if "=" in pair:
                key, val = pair.split("=", 1)
                env[key] = val
            i += 2
            continue
        if tok in ("-h", "--header") and i + 1 < len(args):
            raw = args[i + 1]
            if ": " in raw:
                key, val = raw.split(": ", 1)
                headers[key] = val
            else:
                headers[raw] = ""  # will be validated by caller
            i += 2
            continue
        if tok == "--transport" and i + 1 < len(args):
            transport = args[i + 1].lower()
            i += 2
            continue
        rest.append(tok)
        i += 1
    return is_global, env, headers, transport, rest


def _is_url(value: str) -> bool:
    """Check if a value looks like an HTTP(S) URL."""
    return value.startswith("http://") or value.startswith("https://")


_ADD_USAGE = (
    "  [dim]stdio: /mcp add [--global] [-e/--env KEY=VAL ...] <name> <command> [args...][/dim]\n"
    "  [dim]url:   /mcp add [--global] [--transport http|sse] [-h/--header \"Key: Value\" ...] <name> <url>[/dim]"
)


def _cmd_mcp_add(ctx: CommandContext, args: list[str]) -> None:
    """Add an MCP server to mcp.yaml.

    URL auto-detection: if the second positional arg starts with http:// or
    https://, the server is registered as a url-based entry; otherwise as stdio.
    """
    if not args:
        ctx.console.print("  [error]\u2717 Usage:[/error]")
        ctx.console.print(_ADD_USAGE)
        return

    is_global, env, headers, transport, rest = _parse_add_options(args)
    scope = "global" if is_global else "project"

    # Validate --transport value
    if transport is not None and transport not in ("http", "sse"):
        ctx.console.print(
            f"  [error]\u2717 Invalid transport: {transport} (use 'http' or 'sse')[/error]"
        )
        return

    # Validate --header values (must contain ": ")
    for key, val in headers.items():
        if val == "":
            ctx.console.print(
                f"  [error]\u2717 Invalid header format: '{key}' (expected 'Key: Value')[/error]"
            )
            return

    if len(rest) < 2:
        ctx.console.print("  [error]\u2717 <name> and <command|url> are required[/error]")
        ctx.console.print(_ADD_USAGE)
        return

    name = rest[0]
    target = rest[1]

    # Build server entry — URL vs stdio
    if _is_url(target):
        if env:
            ctx.console.print("  [error]\u2717 -e (env) is not supported for url-based servers[/error]")
            return
        if len(rest) > 2:
            ctx.console.print("  [error]\u2717 url-based servers do not accept extra arguments[/error]")
            return
        entry: dict[str, Any] = {"url": target}
        if transport == "sse":
            entry["transport"] = "sse"
        if headers:
            entry["headers"] = dict(headers)
    else:
        if headers:
            ctx.console.print("  [error]\u2717 --header is not supported for stdio servers[/error]")
            return
        if transport is not None:
            ctx.console.print("  [error]\u2717 --transport is not supported for stdio servers[/error]")
            return
        entry = {"command": target}
        cmd_args = rest[2:]
        if cmd_args:
            entry["args"] = cmd_args
        if env:
            entry["env"] = env

    # Load, update, save
    yaml_path = _mcp_yaml_path(ctx.config, scope)
    servers = _load_mcp_yaml(yaml_path)

    overwrite = name in servers
    servers[name] = entry
    _save_mcp_yaml(yaml_path, servers)

    verb = "Updated" if overwrite else "Added"
    ctx.console.print(f"  [success]\u2713 {verb} server '{name}' in {scope} mcp.yaml[/success]")

    # Reload config + agent
    _reload_and_recreate(ctx)


def _cmd_mcp_remove(ctx: CommandContext, args: list[str]) -> None:
    """Remove an MCP server from mcp.yaml.

    Usage: /mcp remove [--global] <name>
    """
    if not args:
        ctx.console.print("  [error]\u2717 Usage: /mcp remove [--global] <name>[/error]")
        return

    is_global = False
    rest: list[str] = []
    for tok in args:
        if tok == "--global":
            is_global = True
        else:
            rest.append(tok)
    scope = "global" if is_global else "project"

    if not rest:
        ctx.console.print("  [error]\u2717 <name> is required[/error]")
        return

    name = rest[0]
    yaml_path = _mcp_yaml_path(ctx.config, scope)
    servers = _load_mcp_yaml(yaml_path)

    if name not in servers:
        ctx.console.print(
            f"  [error]\u2717 Server '{name}' not found in {scope} mcp.yaml[/error]"
        )
        return

    del servers[name]

    if servers:
        _save_mcp_yaml(yaml_path, servers)
    else:
        # Remove file when no servers remain
        yaml_path.unlink(missing_ok=True)

    # Also clean up disabled state if present
    disabled = load_disabled_mcp_servers(ctx.config)
    if name in disabled:
        disabled.discard(name)
        save_disabled_mcp_servers(ctx.config, disabled)

    ctx.console.print(f"  [success]\u2713 Removed server '{name}' from {scope} mcp.yaml[/success]")

    # Reload config + agent
    _reload_and_recreate(ctx)


def _reload_and_recreate(ctx: CommandContext) -> None:
    """Reload MCP config and recreate the agent."""
    _reload_mcp_servers(ctx.config)
    ctx.close_mcp_tools()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())
    ctx.run_mcp_health_check()


# -- Reload (both global + project, applying disabled) -----------------------


def _reload_mcp_servers(config: "AppConfig") -> None:
    """Reload MCP servers from both global and project mcp.yaml files."""
    from hooty.config import _load_yaml_file

    merged: dict[str, dict[str, Any]] = {}
    sources: dict[str, str] = {}

    for path, label in [
        (config.mcp_file_path, "global"),
        (config.mcp_project_file_path, "project"),
    ]:
        if not path.exists():
            continue
        data = _load_yaml_file(path)
        if isinstance(data, dict) and isinstance(data.get("servers"), dict):
            for name, conf in data["servers"].items():
                merged[name] = conf
                sources[name] = label

    config.mcp = merged
    config.mcp_sources = sources

    # Exclude disabled servers
    disabled = load_disabled_mcp_servers(config)
    for name in disabled:
        config.mcp.pop(name, None)
        config.mcp_sources.pop(name, None)


# -- Subcommands -------------------------------------------------------------


def _cmd_mcp_reload(ctx: CommandContext) -> None:
    """Reload mcp.yaml (global + project) and recreate the agent."""
    _reload_mcp_servers(ctx.config)

    ctx.close_mcp_tools()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())

    count = len(ctx.config.mcp)
    ctx.console.print(
        f"  [success]\u2713 Reloaded mcp.yaml ({count} server{'s' if count != 1 else ''})[/success]"
    )

    # Show deferred creation warnings + health check
    ctx.run_mcp_health_check()


def _cmd_mcp_list(ctx: CommandContext) -> None:
    """List configured MCP servers (including disabled)."""
    disabled = load_disabled_mcp_servers(ctx.config)

    # Build full server list (enabled + disabled) for display
    all_servers = _build_full_server_list(ctx.config, disabled)

    if not all_servers:
        ctx.console.print("  [dim]No MCP servers configured[/dim]")
        ctx.console.print(
            f"  [dim]Edit {ctx.config.mcp_file_path} or "
            f"{ctx.config.mcp_project_file_path}[/dim]"
        )
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
    ctx.console.print(f"  MCP servers ({len(all_servers)}):", style="bold")
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
    table.add_column("Server", style="slash_cmd", no_wrap=True)
    table.add_column("Source", style="dim", no_wrap=True)
    table.add_column("Transport", style="dim", no_wrap=True)
    table.add_column("Detail", no_wrap=True, max_width=60, overflow="ellipsis")

    for name, conf, source, is_disabled in all_servers:
        transport, detail = _format_server_parts(conf)
        if is_disabled:
            table.add_row(
                "[dim]\u2717[/dim]", f"[dim]{name}[/dim]",
                f"[dim]{source}[/dim]", f"[dim]{transport}[/dim]",
                f"[dim]{detail}[/dim]",
            )
        else:
            table.add_row("\u2713", name, source, transport, detail)

    ctx.console.print(table)
    ctx.console.print()


def _cmd_mcp_picker(ctx: CommandContext) -> None:
    """Interactive MCP server picker for enable/disable."""
    from hooty.mcp_picker import pick_mcp_servers

    disabled = load_disabled_mcp_servers(ctx.config)
    all_servers = _build_full_server_list(ctx.config, disabled)

    if not all_servers:
        ctx.console.print("  [dim]No MCP servers configured[/dim]")
        ctx.console.print(
            f"  [dim]Edit {ctx.config.mcp_file_path} or "
            f"{ctx.config.mcp_project_file_path}[/dim]"
        )
        return

    # Build picker items: (name, conf, source, enabled)
    items = [
        (name, conf, source, not is_disabled)
        for name, conf, source, is_disabled in all_servers
    ]

    result = pick_mcp_servers(items, ctx.console)
    if result is None:
        ctx.console.print("  [dim]Cancelled.[/dim]")
        return

    # Save disabled state
    new_disabled = {items[i][0] for i, enabled in enumerate(result) if not enabled}
    save_disabled_mcp_servers(ctx.config, new_disabled)

    # Reload (same as /mcp reload)
    _reload_mcp_servers(ctx.config)
    ctx.close_mcp_tools()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(ctx.get_plan_mode())

    enabled_count = sum(1 for r in result if r)
    ctx.console.print(
        f"  [success]\u2713 MCP servers updated ({enabled_count}/{len(items)} enabled)[/success]"
    )


# -- Helpers -----------------------------------------------------------------


def _build_full_server_list(
    config: "AppConfig", disabled: set[str]
) -> list[tuple[str, dict, str, bool]]:
    """Build full list of servers: (name, conf, source, is_disabled).

    Includes both enabled servers (from config.mcp) and disabled servers
    (from mcp.yaml files that are in the disabled set).
    """
    from hooty.config import _load_yaml_file

    # Start with currently enabled servers
    result: dict[str, tuple[dict, str, bool]] = {}
    for name, conf in config.mcp.items():
        source = config.mcp_sources.get(name, "")
        result[name] = (conf, source, False)

    # Add disabled servers by re-reading yaml files
    for path, label in [
        (config.mcp_file_path, "global"),
        (config.mcp_project_file_path, "project"),
    ]:
        if not path.exists():
            continue
        data = _load_yaml_file(path)
        if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
            continue
        for name, conf in data["servers"].items():
            if name in disabled and name not in result:
                result[name] = (conf, label, True)

    return [(name, *vals) for name, vals in result.items()]


def _format_server_parts(conf: dict) -> tuple[str, str]:
    """Return (transport, detail) for display."""
    if "url" in conf:
        transport = conf.get("transport", "http")
        return transport, conf["url"]
    elif "command" in conf:
        cmd_args = " ".join(conf.get("args", []))
        return "stdio", f"{conf['command']} {cmd_args}".strip()
    return "?", "invalid config"
