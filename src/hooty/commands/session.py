"""Session-related slash commands: /session, /new, /fork, /context, /compact."""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.commands import CommandContext


def cmd_session(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Handle /session commands."""
    if not args:
        _cmd_session_status(ctx)
        return

    sub = args[0].lower()
    if sub == "agents":
        _cmd_session_agents(ctx)
    elif sub == "list":
        _cmd_session_list(ctx)
    elif sub in ("resume", "load"):
        if len(args) < 2:
            from hooty.session_picker import pick_session

            chosen = pick_session(ctx.config, ctx.console)
            if chosen is None:
                return
            if chosen == "":
                cmd_new(ctx)
                return
            _cmd_session_resume(ctx, chosen)
            return
        _cmd_session_resume(ctx, args[1])
    elif sub == "purge":
        days = 90
        if len(args) >= 2:
            try:
                days = int(args[1])
                if days < 0:
                    raise ValueError
            except ValueError:
                ctx.console.print("  [error]\u2717 Days must be a non-negative integer[/error]")
                ctx.console.print("  [dim]Usage: /session purge [days]  (minimum: 0)[/dim]")
                return
        _cmd_session_purge(ctx, days)
    else:
        ctx.console.print(f"  [error]\u2717 Unknown subcommand: {sub}[/error]")
        ctx.console.print("  [dim]/session list        \u2014 List sessions[/dim]")
        ctx.console.print("  [dim]/session resume <id> \u2014 Restore session[/dim]")
        ctx.console.print("  [dim]/session purge [days] \u2014 Purge old sessions[/dim]")
        ctx.console.print("  [dim]/session agents      \u2014 Sub-agent run breakdown[/dim]")


def _cmd_session_status(ctx: CommandContext) -> None:
    """Show current session info."""
    session_id = ctx.get_session_id()
    ctx.console.print()
    ctx.console.print(f"  Session: [session_id]{session_id}[/session_id]")
    from hooty.config import project_dir_name

    proj_name = project_dir_name(Path(ctx.config.working_directory))
    ctx.console.print(
        f"  Project: [white]{ctx.config.working_directory}[/white]  [dim]({proj_name})[/dim]",
        highlight=False,
    )
    try:
        agent = ctx.get_agent()
        metrics = agent.get_session_metrics(session_id=session_id)
        if metrics:
            ctx.console.print(
                f"  Tokens:  [dim]in:{metrics.input_tokens:,}"
                f"  out:{metrics.output_tokens:,}"
                f"  total:{metrics.total_tokens:,}[/dim]"
            )
            if metrics.cost is not None:
                ctx.console.print(f"  Cost:    [dim]${metrics.cost:.4f}[/dim]")
    except Exception:
        pass

    s = ctx.get_session_stats()
    if s.total_runs > 0 or s.has_persisted:
        from hooty.session_stats import format_duration
        elapsed_session = time.monotonic() - s.session_start
        stats_parts = [f"session:{format_duration(elapsed_session)}"]
        if s.has_persisted:
            stats_parts.append(f"runs:{s.total_runs} ({s.grand_total_runs})")
            stats_parts.append(
                f"LLM:{format_duration(s.total_elapsed)}"
                f" ({format_duration(s.grand_total_elapsed)})"
            )
            stats_parts.append(
                f"avg:{format_duration(s.avg_elapsed)}"
                f" ({format_duration(s.grand_avg_elapsed)})"
            )
            grand_ttft = s.grand_avg_ttft
            if grand_ttft is not None:
                cur_ttft = s.avg_ttft
                cur_str = f"{cur_ttft:.2f}s" if cur_ttft is not None else "-"
                stats_parts.append(f"TTFT:{cur_str} ({grand_ttft:.2f}s)")
        else:
            stats_parts.append(f"runs:{s.total_runs}")
            stats_parts.append(f"LLM:{format_duration(s.total_elapsed)}")
            stats_parts.append(f"avg:{format_duration(s.avg_elapsed)}")
            if s.avg_ttft is not None:
                stats_parts.append(f"TTFT:{s.avg_ttft:.2f}s")
        ctx.console.print(f"  Stats:   [dim]{'  '.join(stats_parts)}[/dim]")

    if s.total_sub_agent_runs > 0:
        from hooty.session_stats import format_duration as _fmt_dur
        sa_parts = [f"runs:{s.total_sub_agent_runs}"]
        sa_parts.append(f"tools:{s.total_sub_agent_tool_calls}")
        sa_parts.append(f"time:{_fmt_dur(s.total_sub_agent_elapsed)}")
        sa_parts.append(f"in:{s.total_sub_agent_input_tokens:,}")
        sa_parts.append(f"out:{s.total_sub_agent_output_tokens:,}")
        if s.sub_agent_errors > 0:
            sa_parts.append(f"errors:{s.sub_agent_errors}")
        ctx.console.print(f"  Agents:  [dim]{'  '.join(sa_parts)}[/dim]")
    ctx.console.print()


def _cmd_session_agents(ctx: CommandContext) -> None:
    """Show per-agent breakdown of sub-agent runs."""
    s = ctx.get_session_stats()
    if s.total_sub_agent_runs == 0:
        ctx.console.print("\n  [dim]No sub-agent runs in this session.[/dim]\n")
        return

    from collections import defaultdict

    from hooty.session_stats import format_duration

    agg: dict[str, dict] = defaultdict(lambda: {
        "runs": 0, "tools": 0, "elapsed": 0.0,
        "in": 0, "out": 0, "errors": 0,
    })
    for r in s.sub_agent_runs:
        a = agg[r.agent_name]
        a["runs"] += 1
        a["tools"] += r.tool_calls
        a["elapsed"] += r.elapsed
        a["in"] += r.input_tokens
        a["out"] += r.output_tokens
        if r.error:
            a["errors"] += 1

    ctx.console.print()
    ctx.console.print("  Sub-agent runs:", style="bold")
    ctx.console.print()
    ctx.console.print(
        f"  {'Agent':<14} {'Runs':>4}  {'Tools':>5}  {'Time':>8}"
        f"  {'In tokens':>10}  {'Out tokens':>10}"
    )

    for name, a in sorted(agg.items(), key=lambda x: x[1]["runs"], reverse=True):
        err = f" [red]({a['errors']} err)[/red]" if a["errors"] else ""
        ctx.console.print(
            f"  [dim]{name:<14} {a['runs']:>4}  {a['tools']:>5}  "
            f"{format_duration(a['elapsed']):>8}  "
            f"{a['in']:>10,}  {a['out']:>10,}[/dim]{err}"
        )

    ctx.console.print(f"  {'─' * 60}")
    ctx.console.print(
        f"  {'Total':<14} {s.total_sub_agent_runs:>4}  "
        f"{s.total_sub_agent_tool_calls:>5}  "
        f"{format_duration(s.total_sub_agent_elapsed):>8}  "
        f"{s.total_sub_agent_input_tokens:>10,}  "
        f"{s.total_sub_agent_output_tokens:>10,}"
    )
    ctx.console.print()


def _cmd_session_list(ctx: CommandContext) -> None:
    """List saved sessions."""
    import os

    from hooty.session_store import format_session_for_display, list_sessions

    try:
        sessions, total = list_sessions(ctx.config, limit=10)
    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Failed to list sessions: {e}[/error]")
        return

    if not sessions:
        ctx.console.print("  [dim]No saved sessions[/dim]")
        return

    session_id = ctx.get_session_id()
    norm_cwd = os.path.normcase(os.path.normpath(ctx.config.working_directory))
    sessions_base = ctx.config.config_dir / "sessions"

    from rich.box import Box
    from rich.padding import Padding
    from rich.table import Table

    from hooty.text_utils import truncate_display
    from hooty.workspace import load_workspace

    ctx.console.print()
    ctx.console.print(f"  Saved sessions ({total}):", style="bold")
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
    table.add_column("ID", style="session_id", no_wrap=True, min_width=10)
    table.add_column("Forked", style="dim", no_wrap=True)
    table.add_column("Updated", style="dim", no_wrap=True)
    table.add_column("Runs", no_wrap=True, justify="right")
    table.add_column("Project", no_wrap=True, max_width=16, overflow="ellipsis")
    table.add_column("First message", no_wrap=True, max_width=50, overflow="ellipsis")

    for session_raw in sessions:
        info = format_session_for_display(session_raw)
        is_current = session_raw.get("session_id") == session_id
        marker = " [success]\u25c0[/success]" if is_current else ""
        forked = info.get("forked_from", "")
        fork_col = f"\u2462 {forked[:8]}" if forked else "\u2014"
        project = info.get("project", "\u2014")
        project = truncate_display(project, 14)

        sid = info["session_id"]
        wd: str | None = None
        session_dir = sessions_base / sid
        if session_dir.exists():
            wd = load_workspace(session_dir)
        if not wd:
            wd = info.get("working_directory", "")
        is_mismatch = bool(wd and os.path.normcase(os.path.normpath(wd)) != norm_cwd)
        project_display = f"🚫 {project}" if is_mismatch else project

        table.add_row(
            f"{info['short_id']}{marker}",
            fork_col,
            info["updated_at"],
            info["run_count"],
            project_display,
            info["preview"],
        )

    ctx.console.print(Padding(table, (0, 0, 0, 2)))

    ctx.console.print()
    ctx.console.print("  [dim]/session resume <id> to restore a session[/dim]")
    ctx.console.print()


def cmd_new(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Start a brand-new session (old session stays in DB)."""
    new_id = str(uuid.uuid4())
    if not ctx.switch_session(new_id):
        ctx.console.print("  [error]\u2717 Could not acquire lock for new session[/error]")
        return
    ctx.console.print(f"  [success]\u2713 Started new session [session_id]{new_id[:8]}...[/session_id][/success]")


def cmd_fork(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Fork current session into a new one with the same summary."""
    import logging

    try:
        _do_fork(ctx)
    except Exception as e:
        logging.getLogger("hooty").debug("Fork failed: %s", e)
        ctx.console.print(f"  [error]\u2717 Fork failed: {e}[/error]")


def _do_fork(ctx: CommandContext) -> None:
    """Internal fork logic."""
    from agno.db.base import SessionType
    from agno.session.agent import AgentSession
    from agno.session.summary import SessionSummaryManager

    import logging
    logger = logging.getLogger("hooty")

    old_id = ctx.get_session_id()
    agent = ctx.get_agent()

    session = agent.db.get_session(
        session_id=old_id,
        session_type=SessionType.AGENT,
    )
    if session is None:
        ctx.console.print("  [error]\u2717 Current session not found in database[/error]")
        return

    has_runs = bool(session.runs)
    has_summary = session.summary is not None
    if not has_runs and not has_summary:
        ctx.console.print("  [dim]Nothing to fork \u2014 session is empty[/dim]")
        return

    summary = session.summary
    if summary is None:
        ctx.console.print("  [dim]Generating session summary...[/dim]")
        try:
            manager = SessionSummaryManager(model=agent.model)
            manager.create_session_summary(session=session)
            summary = session.summary
        except Exception as e:
            logger.debug("Summary generation failed: %s", e)
            ctx.console.print(
                f"  [warning]\u26a0 Summary generation failed: {e}[/warning]"
            )
            ctx.console.print("  [dim]Forking without summary...[/dim]")

    new_id = str(uuid.uuid4())
    now = int(time.time())
    new_meta = dict(session.metadata) if session.metadata else {}
    new_meta["forked_from"] = old_id
    new_session = AgentSession(
        session_id=new_id,
        agent_id=session.agent_id,
        user_id=session.user_id,
        session_data=dict(session.session_data) if session.session_data else None,
        metadata=new_meta,
        agent_data=dict(session.agent_data) if session.agent_data else None,
        runs=[],
        summary=summary,
        created_at=now,
        updated_at=now,
    )
    agent.db.upsert_session(new_session)

    if not ctx.switch_session(new_id):
        ctx.console.print("  [error]\u2717 Could not acquire lock for forked session[/error]")
        return

    ctx.console.print(
        f"  [success]\u2713 Forked session [session_id]{old_id[:8]}...[/session_id]"
        f" \u2192 [session_id]{new_id[:8]}...[/session_id][/success]"
    )


def _cmd_session_resume(ctx: CommandContext, session_id_prefix: str) -> None:
    """Resume a session by ID or prefix."""
    resolved_id = _resolve_session_id(ctx, session_id_prefix)
    if resolved_id is None:
        ctx.console.print(f"  [error]\u2717 Session '{session_id_prefix}' not found[/error]")
        return

    if resolved_id == ctx.get_session_id():
        ctx.console.print("  [dim]This session is already active[/dim]")
        return

    from hooty.session_lock import is_locked

    if is_locked(ctx.config, resolved_id):
        ctx.console.print(
            f"  [error]\u2717 Session {resolved_id[:8]}... is locked by another process[/error]"
        )
        return

    if not ctx.switch_session(resolved_id):
        ctx.console.print(
            f"  [error]\u2717 Could not acquire lock for session {resolved_id[:8]}...[/error]"
        )
        return

    ctx.console.print(
        f"  [success]\u2713 Restored session [session_id]{resolved_id[:8]}...[/session_id][/success]"
    )


def _cmd_session_purge(ctx: CommandContext, days: int = 90) -> None:
    """Purge sessions older than *days* days via interactive picker."""
    from hooty.session_lock import is_locked
    from hooty.session_store import (
        cleanup_orphan_dirs,
        find_purgeable_sessions,
        list_sessions,
        purge_sessions,
    )

    session_id = ctx.get_session_id()
    exclude: set[str] = {session_id}
    try:
        sessions_all, _ = list_sessions(ctx.config, limit=10000)
        for s in sessions_all:
            sid = s.get("session_id", "")
            if is_locked(ctx.config, sid):
                exclude.add(sid)
    except Exception:
        pass

    try:
        purgeable = find_purgeable_sessions(ctx.config, days=days, exclude_ids=exclude)
    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Failed to find purgeable sessions: {e}[/error]")
        return

    orphan_count = 0
    sessions_base = ctx.config.config_dir / "sessions"
    if sessions_base.exists():
        from agno.db.base import SessionType

        from hooty.session_store import _create_storage

        with _create_storage(ctx.config) as storage:
            for entry in sessions_base.iterdir():
                if not entry.is_dir():
                    continue
                session = storage.get_session(
                    session_id=entry.name,
                    session_type=SessionType.AGENT,
                    deserialize=False,
                )
                if session is None:
                    orphan_count += 1

    if not purgeable and orphan_count == 0:
        ctx.console.print(f"  [dim]No sessions older than {days} days to purge[/dim]")
        return

    from hooty.purge_picker import pick_purge_targets

    chosen_ids = pick_purge_targets(
        purgeable, ctx.console, orphan_count=orphan_count, days=days,
    )

    if chosen_ids is None or (not chosen_ids and orphan_count == 0):
        ctx.console.print("  [dim]Cancelled[/dim]")
        return

    total_work = len(chosen_ids) + (1 if orphan_count > 0 else 0)
    removed = 0
    orphans_removed = 0

    if total_work <= 2:
        if chosen_ids:
            removed = purge_sessions(ctx.config, chosen_ids)
        if orphan_count > 0:
            orphans_removed = cleanup_orphan_dirs(ctx.config)
    else:
        from rich.progress import BarColumn, Progress, TextColumn

        with Progress(
            TextColumn("  [dim]{task.description}[/dim]"),
            BarColumn(bar_width=30, style="#444444", complete_style="#E6C200"),
            TextColumn("[dim]{task.completed}/{task.total}[/dim]"),
            console=ctx.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Purging...", total=total_work)

            if chosen_ids:
                from hooty.session_store import _create_storage

                sessions_base = ctx.config.config_dir / "sessions"
                import shutil

                with _create_storage(ctx.config) as storage:
                    for sid in chosen_ids:
                        try:
                            storage.delete_session(session_id=sid)
                            removed += 1
                        except Exception:
                            pass
                        session_dir = sessions_base / sid
                        if session_dir.exists():
                            shutil.rmtree(session_dir, ignore_errors=True)
                        progress.advance(task)

            if orphan_count > 0:
                orphans_removed = cleanup_orphan_dirs(ctx.config)
                progress.advance(task)

    ctx.console.print(
        f"  [success]\u2713 Purged {removed} session(s), "
        f"removed {orphans_removed} orphan dir(s)[/success]"
    )


def _resolve_session_id(ctx: CommandContext, prefix: str) -> str | None:
    """Resolve a session ID prefix to a full session ID."""
    from hooty.session_store import list_sessions, session_exists

    if len(prefix) >= 32:
        if session_exists(ctx.config, prefix):
            return prefix
        return None

    sessions, _ = list_sessions(ctx.config, limit=100)
    matches = [s["session_id"] for s in sessions if s["session_id"].startswith(prefix)]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        ctx.console.print(
            f"  [warning]\u26a0 Multiple sessions match '{prefix}'. "
            "Please specify a longer ID[/warning]"
        )
        return None
    return None


def cmd_compact(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Compact session history by summarizing and clearing old runs."""
    from agno.db.base import SessionType
    from agno.session.summary import SessionSummaryManager

    ctx.console.print("  [dim]Compacting session history...[/dim]")

    try:
        agent = ctx.get_agent()
        session_id = ctx.get_session_id()
        session = agent.db.get_session(
            session_id=session_id,
            session_type=SessionType.AGENT,
        )
        if session is None:
            ctx.console.print("  [error]\u2717 Session not found[/error]")
            return

        runs = session.runs or []
        if not runs:
            ctx.console.print("  [dim]No history to compact[/dim]")
            return

        total_messages = sum(len(r.messages or []) for r in runs)

        manager = SessionSummaryManager(model=agent.model)
        manager.create_session_summary(session=session)

        session.runs = []
        agent.db.upsert_session(session)

        new_agent = ctx.create_agent()
        ctx.set_agent(new_agent)
        ctx.set_agent_plan_mode(ctx.get_plan_mode())

        ctx.console.print(
            f"  [success]\u2713 Compacted {len(runs)} runs ({total_messages} messages) into summary[/success]"
        )

    except Exception as e:
        ctx.console.print(f"  [error]\u2717 Compaction failed: {e}[/error]")


def cmd_context(ctx: CommandContext, args: list[str] | None = None) -> None:
    """Show loaded context files."""
    from hooty.context import load_context

    _, info = load_context(
        config_dir=ctx.config.config_dir,
        project_root=Path(ctx.config.working_directory),
    )

    ctx.console.print()
    _print_current_model(ctx)
    ctx.console.print("  Context:", style="bold")

    if info.global_path:
        size_kb = info.global_size / 1024
        ctx.console.print(
            f"    Global instructions: {info.global_path} ({size_kb:.1f} KB, {info.global_lines} LoC)"
        )
    else:
        ctx.console.print("    Global instructions: [dim]none[/dim]")

    if info.project_path:
        size_kb = info.project_size / 1024
        ctx.console.print(
            f"    Project instructions: {info.project_path.name} ({size_kb:.1f} KB, {info.project_lines} LoC)"
        )
    else:
        ctx.console.print("    Project instructions: [dim]none[/dim]")

    ctx.console.print()
    _print_context_window_state(ctx)


def _print_current_model(ctx: CommandContext) -> None:
    """Print current model information section."""
    from hooty.config import supports_thinking, supports_vision

    config = ctx.config

    ctx.console.print("  Current Model:", style="bold")
    ctx.console.print(f"    Provider:  {config.provider.value}")
    ctx.console.print(f"    Model ID:  {ctx.get_model_id()}")

    if config.active_profile:
        ctx.console.print(f"    Profile:   {config.active_profile}")

    # Streaming
    if config.stream:
        ctx.console.print("    Streaming: [green]✓[/green]")
    else:
        ctx.console.print("    Streaming: [dim]✗[/dim]")

    # Reasoning
    if supports_thinking(config):
        mode = config.reasoning.mode
        ctx.console.print(f"    Reasoning: [green]✓[/green] ({mode})")
    else:
        ctx.console.print("    Reasoning: [dim]✗[/dim]")

    # Vision
    if supports_vision(config):
        ctx.console.print("    Vision:    [green]✓[/green]")
    else:
        ctx.console.print("    Vision:    [dim]✗[/dim]")

    ctx.console.print()


def _print_context_window_state(ctx: CommandContext) -> None:
    """Print context window usage visualisation."""
    try:
        from agno.db.base import SessionType

        limit = ctx.get_context_limit()
        bar_width = 20
        agent = ctx.get_agent()
        session_id = ctx.get_session_id()

        input_tokens = 0
        token_source = ""
        last_run = None
        try:
            last_run = agent.get_last_run_output(session_id=session_id)
            if last_run and last_run.metrics and last_run.metrics.input_tokens:
                input_tokens = last_run.metrics.input_tokens
                token_source = "run"
        except Exception:
            pass
        # Prefer per-request value for accurate context usage
        per_request = ctx.get_last_request_input_tokens()
        if per_request is not None and per_request > 0:
            input_tokens = per_request
            token_source = "request"

        # Add cache tokens to get true context window usage.
        # Anthropic API reports cache_read/cache_creation separately from input_tokens,
        # but all of them occupy the context window.
        cache_read = 0
        cache_write = 0
        try:
            if last_run and last_run.messages:
                for msg in reversed(last_run.messages):
                    if msg.role == "assistant" and msg.metrics:
                        cache_read = getattr(msg.metrics, "cache_read_tokens", 0) or 0
                        cache_write = getattr(msg.metrics, "cache_write_tokens", 0) or 0
                        break
        except Exception:
            pass
        input_tokens += cache_read + cache_write

        ctx.console.print("  Context window:", style="bold")
        if input_tokens:
            pct = input_tokens / limit * 100
            filled = int(round(pct / 100 * bar_width))
            filled = min(filled, bar_width)
            bar_fill = "\u2588" * filled
            bar_empty = "\u2591" * (bar_width - filled)
            if pct >= 80:
                color = "bold red"
            elif pct >= 50:
                color = "yellow"
            else:
                color = "#E6C200"
            ctx.console.print(
                f"    [{color}]{bar_fill}[/{color}][dim]{bar_empty}[/dim]"
                f" {pct:.0f}% ({input_tokens:,} / {limit:,} tokens)"
            )
        else:
            bar_empty = "\u2591" * bar_width
            ctx.console.print(
                f"    [dim]{bar_empty}[/dim] -- ({limit:,} tokens available)"
            )

        if token_source:
            source_label = "last request" if token_source == "request" else "last run (sum)"
            ctx.console.print(f"    Source:          [dim]{source_label}[/dim]")

        session = None
        try:
            session = agent.db.get_session(
                session_id=session_id,
                session_type=SessionType.AGENT,
            )
        except Exception:
            pass

        runs = (session.runs or []) if session else []
        num_runs = len(runs)
        num_history_runs = getattr(agent, "num_history_runs", 3)

        summary = session.summary if session else None
        has_summary = bool(summary and summary.summary)

        if num_runs == 0:
            ctx.console.print()
            if has_summary:
                ctx.console.print("    History:         [dim]compacted into summary[/dim]")
            else:
                ctx.console.print("    History:         [dim]no runs yet[/dim]")
        else:
            total_msgs = sum(len(r.messages or []) for r in runs)
            history_note = ""
            if num_runs > num_history_runs:
                history_note = f" (last {num_history_runs} in context)"
            ctx.console.print()
            ctx.console.print(
                f"    History:         {num_runs} runs, {total_msgs} messages{history_note}"
            )

        if has_summary:
            summary_len = len(summary.summary)
            ctx.console.print(f"    Session summary: active ({summary_len:,} chars)")
        else:
            ctx.console.print("    Session summary: [dim]none[/dim]")

        compressed_count = 0
        for run in runs:
            for msg in run.messages or []:
                if msg.role == "tool" and msg.compressed_content is not None:
                    compressed_count += 1
        if compressed_count > 0:
            ctx.console.print(f"    Compressed:      {compressed_count} tool results")

        ctx.console.print()
    except Exception:
        pass
