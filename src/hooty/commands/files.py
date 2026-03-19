"""File-related slash commands: /diff, /rewind, /review, /add-dir, /list-dirs."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext

logger = logging.getLogger("hooty")


def cmd_diff(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Show file changes made in this session."""
    store = ctx.get_snapshot_store()
    if store is None:
        ctx.console.print(
            "  [dim]Snapshot tracking is disabled. "
            "Use --snapshot or set snapshot.enabled: true in config.yaml[/dim]"
        )
        return

    changes = store.get_changes()
    if not changes:
        ctx.console.print("  [dim]No file changes in this session.[/dim]")
        return

    import difflib

    from rich.syntax import Syntax

    created = sum(1 for c in changes if c.status == "created")
    modified = sum(1 for c in changes if c.status == "modified")
    deleted = sum(1 for c in changes if c.status == "deleted")

    ctx.console.print()
    for change in changes:
        status_style = {
            "created": "bold green",
            "modified": "bold yellow",
            "deleted": "bold red",
        }.get(change.status, "bold")
        ctx.console.print(f"  [{status_style}]{change.status}[/{status_style}] {change.path}")

        if change.externally_modified:
            ctx.console.print("    [bold yellow]\u26a0 externally modified[/bold yellow]")

        if change.original is None and change.current is None:
            ctx.console.print("    [dim](binary)[/dim]")
            continue

        original_lines = (change.original or "").splitlines(keepends=True)
        current_lines = (change.current or "").splitlines(keepends=True)

        diff_lines = list(difflib.unified_diff(
            original_lines,
            current_lines,
            fromfile=f"a/{Path(change.path).name}",
            tofile=f"b/{Path(change.path).name}",
        ))

        if diff_lines:
            diff_text = "".join(diff_lines)
            syntax = Syntax(diff_text, "diff", theme="monokai", padding=1)
            ctx.console.print(syntax)

    parts = []
    if created:
        parts.append(f"[green]{created} created[/green]")
    if modified:
        parts.append(f"[yellow]{modified} modified[/yellow]")
    if deleted:
        parts.append(f"[red]{deleted} deleted[/red]")
    ext_count = sum(1 for c in changes if c.externally_modified)
    ctx.console.print(f"  {', '.join(parts)}")
    if ext_count:
        ctx.console.print(f"  [bold yellow]\u26a0 {ext_count} file externally modified[/bold yellow]")
    ctx.console.print()


def cmd_rewind(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Revert file changes and conversation history."""
    store = ctx.get_snapshot_store()
    if store is None:
        ctx.console.print(
            "  [dim]Snapshot tracking is disabled. "
            "Use --snapshot or set snapshot.enabled: true in config.yaml[/dim]"
        )
        return

    changes = store.get_changes()
    if not changes:
        ctx.console.print("  [dim]No file changes to revert.[/dim]")
        return

    from hooty.ui import hotkey_select, number_select

    ctx.console.print()
    for i, change in enumerate(changes, 1):
        ext_warn = " [bold yellow]\u26a0[/bold yellow]" if change.externally_modified else ""
        ctx.console.print(f"  {i}. [{change.status}] {change.path}{ext_warn}")
    ctx.console.print()

    key = hotkey_select(
        [("A", "Revert all"), ("S", "Select files"), ("Q", "Cancel")],
        title="\u25cf Rewind",
        subtitle=f"{len(changes)} file(s) changed",
        con=ctx.console,
    )

    if key == "Q":
        ctx.console.print("  [dim]Cancelled.[/dim]")
        return

    if key == "S":
        options = [
            f"[{c.status}] {Path(c.path).name}" + (" \u26a0" if c.externally_modified else "")
            for c in changes
        ]
        idx = number_select(
            options,
            title="\u25cf Select file to revert",
            con=ctx.console,
        )
        if idx is None:
            ctx.console.print("  [dim]Cancelled.[/dim]")
            return
        selected = [changes[idx]]
    else:
        selected = list(changes)

    ext_modified = [c for c in selected if c.externally_modified]
    if ext_modified:
        ctx.console.print()
        for c in ext_modified:
            ctx.console.print(
                f"  [bold yellow]\u26a0 {Path(c.path).name} was modified outside this session[/bold yellow]"
            )
        confirm = hotkey_select(
            [("Y", "Yes, revert anyway"), ("N", "Cancel")],
            title="\u25cf Externally modified files",
            subtitle="Continue with revert?",
            con=ctx.console,
        )
        if confirm != "Y":
            ctx.console.print("  [dim]Cancelled.[/dim]")
            return

    restored = 0
    for change in selected:
        if store.restore(change.path):
            restored += 1

    if restored == 0:
        ctx.console.print("  [dim]No files were reverted.[/dim]")
        return

    try:
        from agno.db.base import SessionType
        from agno.session.summary import SessionSummaryManager

        agent = ctx.get_agent()
        session_id = ctx.get_session_id()
        session = agent.db.get_session(
            session_id=session_id,
            session_type=SessionType.AGENT,
        )
        if session and session.runs:
            manager = SessionSummaryManager(model=agent.model)
            manager.create_session_summary(session=session)
            session.runs = []
            agent.db.upsert_session(session)
            new_agent = ctx.create_agent()
            ctx.set_agent(new_agent)
            ctx.set_agent_plan_mode(ctx.get_plan_mode())
    except Exception as e:
        logger.debug("rewind: failed to compact history: %s", e)

    ctx.console.print(
        f"  [success]\u2713 Reverted {restored} file(s) + conversation history reset[/success]"
    )


def cmd_review(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Start a code review for the specified scope."""
    from hooty.review import (
        REVIEW_TYPES,
        build_fix_prompt,
        build_review_prompt,
        custom_review_type,
        describe_scope,
        parse_findings,
    )
    from hooty.ui import number_select

    from hooty.file_picker import pick_file

    target = pick_file(
        ctx.config.working_directory,
        con=ctx.console,
    )
    if target is None:
        ctx.console.print("  [dim]Review cancelled.[/dim]")
        return

    labels = [rt.label for rt in REVIEW_TYPES] + ["Custom \u2014 enter your own focus"]
    idx = number_select(
        labels,
        title="\u25cf Review Type",
        border_style="cyan",
        con=ctx.console,
    )
    if idx is None:
        ctx.console.print("  [dim]Review cancelled.[/dim]")
        return

    if idx < len(REVIEW_TYPES):
        review_type = REVIEW_TYPES[idx]
    else:
        from hooty.ui import text_input

        while True:
            custom_focus = text_input(
                title="\u25cf Review focus",
                con=ctx.console,
            )
            if custom_focus is None:
                ctx.console.print("  [dim]Review cancelled.[/dim]")
                return
            if custom_focus:
                break
            ctx.console.print("  [dim]Please enter a review focus.[/dim]")
        review_type = custom_review_type(custom_focus)

    scope = describe_scope(target, ctx.config.working_directory)
    ctx.console.print(f"  [dim]Reviewing: {scope} ({review_type.key})[/dim]")
    prompt = build_review_prompt(
        target, scope, ctx.config.working_directory, review_type,
    )
    ctx.send_to_agent(prompt)

    findings = parse_findings(ctx.get_last_response_text())
    if not findings:
        return

    from hooty.review_picker import pick_review_findings

    fix_requests = pick_review_findings(findings, ctx.console)
    if not fix_requests:
        ctx.console.print("  [dim]No findings selected for fix.[/dim]")
        return

    if ctx.get_plan_mode():
        from hooty.ui import hotkey_select

        key = hotkey_select(
            [("Y", "Yes, switch to coding"), ("N", "No, keep review only")],
            title="\u25cf Switch to coding mode to apply fixes?",
            border_style="cyan",
            con=ctx.console,
        )
        if key != "Y":
            ctx.console.print("  [dim]Staying in planning mode. No fixes applied.[/dim]")
            return
        _set_plan_mode_with_msg(ctx, False)

    fix_prompt = build_fix_prompt(fix_requests)
    ctx.send_to_agent(fix_prompt)


def _set_plan_mode_with_msg(ctx: CommandContext, enabled: bool) -> None:
    """Set plan mode, recreate agent, and print status."""
    if ctx.get_plan_mode() == enabled:
        return
    ctx.set_plan_mode(enabled)
    ctx.auto_execute_ref[0] = False
    ctx.close_agent_model()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.set_agent_plan_mode(enabled)
    mode_name = "PLANNING" if enabled else "CODING"
    ctx.console.print(f"  [success]\u2713 Switched to {mode_name.capitalize()} mode[/success]")


def cmd_add_dir(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Add a working directory for file read/write."""
    if args:
        raw_path = " ".join(args)
        dir_path = Path(raw_path).expanduser().resolve()
    else:
        from hooty.file_picker import pick_directory

        picked = pick_directory(
            ctx.config.working_directory,
            title="\u25cf Add Directory",
            con=ctx.console,
        )
        if not picked:
            ctx.console.print("  [dim]Cancelled.[/dim]")
            return
        dir_path = Path(picked).resolve()

    if not dir_path.is_dir():
        ctx.console.print(f"  [error]\u2717 Not a directory: {dir_path}[/error]")
        return

    base = Path(ctx.config.working_directory).resolve()
    if dir_path == base:
        ctx.console.print("  [dim]Already the primary working directory.[/dim]")
        return

    if str(dir_path) in ctx.config.add_dirs:
        ctx.console.print("  [dim]Directory already added.[/dim]")
        return

    if str(dir_path) == "/" or dir_path == Path.home():
        from hooty.ui import hotkey_select

        key = hotkey_select(
            [("Y", "Yes, add anyway"), ("N", "No, cancel")],
            title="\u26a0 Warning",
            subtitle=f"Adding '{dir_path}' grants broad file access",
            border_style="yellow",
            con=ctx.console,
        )
        if key != "Y":
            ctx.console.print("  [dim]Cancelled.[/dim]")
            return

    ctx.config.add_dirs.append(str(dir_path))
    ct = ctx.get_coding_tools()
    if ct:
        ct.additional_base_dirs.append(dir_path)
        if dir_path not in ct.extra_read_dirs:
            ct.extra_read_dirs.append(dir_path)

    ctx.close_agent_model()
    new_agent = ctx.create_agent()
    ctx.set_agent(new_agent)
    ctx.console.print(f"  [success]\u2713 Added directory: {dir_path}[/success]")


def cmd_list_dirs(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Show current working directories."""
    ctx.console.print()
    ctx.console.print(f"  [bold]Primary:[/bold] {ctx.config.working_directory}")
    ct = ctx.get_coding_tools()
    add_dirs = ct.additional_base_dirs if ct else []
    if add_dirs:
        ctx.console.print("  [bold]Additional (read+write):[/bold]")
        for d in add_dirs:
            ctx.console.print(f"    - {d}")
    else:
        ctx.console.print("  [dim]No additional directories.[/dim]")
    ctx.console.print()
