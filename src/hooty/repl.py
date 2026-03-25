"""Interactive REPL loop for Hooty."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import sys
try:
    import termios
except ImportError:
    termios = None  # Windows
import time
import typing
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    from prompt_toolkit.formatted_text import HTML

    from hooty.attachment import AttachmentStack

from hooty import __version__
from hooty.agent_factory import create_agent
from hooty.config import AppConfig, owl_eyes
from hooty.model_catalog import get_context_limit
from hooty.repl_ui import (
    HOOTY_THEME,
    ScrollableMarkdown,
    StreamingView,
    ThinkingIndicator,
    _BSUWriter,
)

logger = logging.getLogger("hooty")


# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Windows: stale CTRL_C_EVENT suppression via SetConsoleCtrlHandler
# ---------------------------------------------------------------------------
# On Windows, stale CTRL_C_EVENT signals of unknown origin are observed
# during and shortly after subprocess execution.  The root cause is not
# conclusively identified — possible factors include ConPTY behaviour,
# console input-buffer races, or process-group signal delivery.
#
# If these stale events reach Python's default handler they raise
# KeyboardInterrupt in the event loop, which corrupts the
# ProactorEventLoop's internal I/O state (self-pipe) and makes the loop
# unusable.
#
# As a workaround we install a native Windows console-ctrl handler that
# BLOCKS CTRL_C_EVENT *before* Python sees it while a tool is running or
# within a short grace period after tool completion.  Events outside this
# window pass through normally so genuine Ctrl+C works immediately.
_WIN_STALE_WINDOW = 5.0  # seconds after tool completion

# Mutable tool-execution state (written from _async_stream_response).
_tool_running: bool = False
_last_tool_completed: float = 0.0

# How many CTRL_C_EVENTs have been suppressed in the current window.
_win_suppressed: int = 0

# References to the active async task and event loop, used by the Windows
# console-ctrl handler to cancel the main task via call_soon_threadsafe.
_win_active_task: asyncio.Task | None = None
_win_active_loop: asyncio.AbstractEventLoop | None = None


def _win_deferred_cancel() -> None:
    """Event-loop callback: cancel the main task only if still requested.

    Called via ``call_soon_threadsafe`` from the Windows console-ctrl
    handler.  Interactive dialogs clear ``_win_cancel_requested`` before
    this callback runs (since the event loop is blocked during tool
    execution), so a CTRL-C pressed during a dialog is harmlessly
    discarded.
    """
    from hooty.tools.confirm import _win_cancel_requested

    if _win_cancel_requested[0] and _win_active_task is not None:
        _win_active_task.cancel()
    _win_cancel_requested[0] = False


def _in_stale_window() -> bool:
    """Return True if we are within the stale-interrupt time window."""
    if _tool_running:
        return True
    return (time.monotonic() - _last_tool_completed) < _WIN_STALE_WINDOW


def _install_win_ctrl_handler() -> None:
    """Install a native Windows console-ctrl handler.

    The handler intercepts CTRL_C_EVENT and suppresses it when a tool is
    running or recently completed, preventing stale signals from corrupting
    the ProactorEventLoop.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes

        _CTRL_C_EVENT = 0

        @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint)  # type: ignore[misc]
        def _handler(event: int) -> int:
            global _win_suppressed  # noqa: PLW0603
            if event == _CTRL_C_EVENT and _in_stale_window():
                _win_suppressed += 1
                if _tool_running:
                    # Genuine Ctrl+C during tool execution — propagate the
                    # cancellation intent via events rather than letting
                    # KeyboardInterrupt corrupt the ProactorEventLoop.
                    try:
                        from hooty.tools.sub_agent_runner import cancel_event
                        cancel_event.set()
                    except Exception:
                        pass
                    try:
                        from hooty.tools.shell_runner import _interrupt_event
                        _interrupt_event.set()
                    except Exception:
                        pass
                    # Schedule deferred task cancellation.  Use a flag +
                    # callback instead of calling task.cancel() directly so
                    # that interactive dialogs can clear the flag and prevent
                    # a stale CTRL-C from poisoning execution after the user
                    # makes a deliberate choice (Y/N).
                    try:
                        from hooty.tools.confirm import _win_cancel_requested
                        _win_cancel_requested[0] = True
                    except Exception:
                        pass
                    _loop = _win_active_loop
                    if _loop is not None:
                        try:
                            _loop.call_soon_threadsafe(_win_deferred_cancel)
                        except Exception:
                            pass
                logger.debug(
                    "[win-ctrl] Suppressed CTRL_C_EVENT #%d "
                    "(tool_running=%s)",
                    _win_suppressed, _tool_running,
                )
                return 1  # TRUE → handled, don't propagate
            return 0  # FALSE → pass to next handler (Python default)

        # prevent GC of the callback
        _install_win_ctrl_handler._ref = _handler  # type: ignore[attr-defined]
        ctypes.windll.kernel32.SetConsoleCtrlHandler(_handler, True)  # type: ignore[union-attr]
        logger.debug("[win-ctrl] Console ctrl handler installed")
    except Exception:
        logger.debug("[win-ctrl] Failed to install handler", exc_info=True)


# Slash command definitions: (command, description) — sorted alphabetically
SLASH_COMMANDS = [
    ("/add-dir [path]", "Add working directory for read/write"),
    ("/agents", "List available sub-agents"),
    ("/agents info <name>", "Show sub-agent details"),
    ("/agents reload", "Reload agents.yaml"),
    ("/attach [path]", "Attach file to next message"),
    ("/attach capture [target]", "Screen capture (Win/WSL2)"),
    ("/attach clear", "Clear all attachments"),
    ("/attach list", "Manage attachments (interactive)"),
    ("/attach paste", "Attach from clipboard (image/files)"),
    ("/auto", "Toggle auto mode transitions"),
    ("/code", "Switch to coding mode"),
    ("/compact", "Compact session history"),
    ("/context", "Show context files & window usage"),
    ("/copy", "Copy last response to clipboard"),
    ("/copy N", "Copy Nth most recent response"),
    ("/database", "Show current DB connection"),
    ("/database add <name> <url>", "Add a database (name url)"),
    ("/diff", "Show file changes made in this session"),
    ("/database connect <name>", "Connect to a database"),
    ("/database disconnect", "Disconnect from database"),
    ("/database list", "List registered databases"),
    ("/database remove <name>", "Remove a database"),
    ("/exit", "Exit Hooty"),
    ("/fork", "Fork current session"),
    ("/github", "Toggle GitHub tools on/off"),
    ("/help", "Show this help"),
    ("/hooks", "Manage lifecycle hooks (interactive picker)"),
    ("/hooks list", "List registered hooks"),
    ("/hooks off", "Disable hooks globally"),
    ("/hooks on", "Enable hooks globally"),
    ("/hooks reload", "Reload hooks.yaml"),
    ("/list-dirs", "Show allowed working directories"),
    ("/mcp", "Interactive MCP server picker"),
    ("/mcp add", "Add MCP server"),
    ("/mcp list", "List MCP servers"),
    ("/mcp reload", "Reload mcp.yaml"),
    ("/mcp remove", "Remove MCP server"),
    ("/memory", "Show memory status"),
    ("/memory list", "List project memories"),
    ("/memory list --global", "List global memories"),
    ("/memory search <keyword>", "Search memories"),
    ("/memory edit", "Delete / move project memories"),
    ("/memory edit --global", "Delete / move global memories"),
    ("/model", "Switch model profile"),
    ("/new", "Start a new session"),
    ("/plan", "Switch to planning mode"),
    ("/plans", "Browse plans (view + delete)"),
    ("/plans search <keyword>", "Search plans by keyword"),
    ("/project purge", "Purge orphaned project directories"),
    ("/quit", "Exit Hooty"),
    ("/reasoning", "Toggle reasoning mode (off → on → auto)"),
    ("/reasoning on|off|auto", "Set reasoning mode"),
    ("/rescan", "Rescan PATH for available commands"),
    ("/review", "Review source code (interactive)"),
    ("/rewind", "Revert file changes and conversation history"),
    ("/safe", "Enable safe mode"),
    ("/session", "Show current session ID"),
    ("/session agents", "Sub-agent run breakdown"),
    ("/session list", "List saved sessions"),
    ("/session purge [days]", "Purge old sessions"),
    ("/session resume <id>", "Restore a session"),
    ("/skills", "Manage agent skills (interactive picker)"),
    ("/skills add <path>", "Add external skill directory (project)"),
    ("/skills add --global <path>", "Add external skill directory (global)"),
    ("/skills info <name>", "Show skill details"),
    ("/skills invoke <name> [args]", "Manually invoke a skill"),
    ("/skills list", "List all skills"),
    ("/skills off", "Disable skills globally"),
    ("/skills on", "Enable skills globally"),
    ("/skills reload", "Reload skills from disk"),
    ("/skills remove <path>", "Remove external skill directory (project)"),
    ("/skills remove --global <path>", "Remove external skill directory (global)"),
    ("/unsafe", "Disable safe mode"),
    ("/websearch", "Toggle web search tools on/off"),
]


class REPL:
    """Interactive REPL for Hooty CLI."""

    def __init__(self, config: AppConfig, *, attach_files: list[str] | None = None):
        self.config = config
        self._initial_attach_files = attach_files or []
        self.console = Console(theme=HOOTY_THEME)
        self.plan_mode: bool = False
        self._agent_plan_mode: bool = False
        self.confirm_ref: list[bool] = [not config.unsafe]
        self.auto_ref: list[bool] = [False]
        self.auto_execute_ref: list[bool] = [False]
        self.pending_plan_ref: list[str | None] = [None]
        self.enter_plan_ref: list[bool] = [False]
        self.pending_reason_ref: list[str | None] = [None]
        self.pending_revise_ref: list[bool] = [False]
        self.pending_plan_id_ref: list[str | None] = [None]
        self._pending_execute: bool = False
        self._pending_plan_start: bool = False
        self._pending_plan_input: str | None = None
        self._pending_plan_revise_file: str | None = None
        self._pending_plan_context: str | None = None
        self._last_plan_file: str | None = None
        self._pending_skill_message: str | None = None
        self._hooks_config: dict[str, list] = {}
        self._hook_pending_context: str = ""
        self.session_id = config.session_id or str(uuid.uuid4())
        config.session_id = self.session_id
        self.session_id_ref: list[str] = [self.session_id]
        self._session_dir_created = bool(config.session_dir and config.session_dir.exists())
        self._workspace_needs_rebind = False  # set True when mismatch detected; cleared on save
        self.running = True
        self._last_eof_time: float = 0.0
        self._last_response_text: str = ""
        self._last_final_text: str = ""
        self._last_request_input_tokens: int = 0
        self._attachment_stack: AttachmentStack | None = None
        self._loop = asyncio.new_event_loop()

        from hooty.session_stats import SessionStats, load_persisted_stats
        self.session_stats = SessionStats()
        if config.session_dir and config.session_dir.exists():
            self.session_stats.persisted = load_persisted_stats(config.session_dir)

        # Share the console with UI primitives used by tools
        from hooty.ui import _active_console
        _active_console[0] = self.console

        # Share hook refs with confirm.py (updated after _load_hooks_config)
        from hooty.tools.confirm import _hooks_ref
        _hooks_ref[0] = self._hooks_config
        _hooks_ref[1] = self.session_id
        _hooks_ref[2] = self.config.working_directory
        _hooks_ref[3] = self._loop

        # Share sub-agent event callback and session stats with sub_agent_tools
        from hooty.tools.sub_agent_tools import _on_event as _sub_agent_on_event
        from hooty.tools.sub_agent_tools import _session_stats_ref
        _sub_agent_on_event[0] = self._sub_agent_event_handler
        _session_stats_ref[0] = self.session_stats

        # Skill slash-command cache (populated by _refresh_skill_commands)
        self._skill_command_cache: list[tuple[str, str]] = []
        self._refresh_skill_commands()

        # Build CommandContext for slash command handlers
        self._cmd_ctx = self._build_command_context()

    def _build_command_context(self):
        """Build the CommandContext that is passed to all command handlers."""
        from hooty.commands import CommandContext

        return CommandContext(
            config=self.config,
            console=self.console,
            # Session
            get_session_id=lambda: self.session_id,
            set_session_id=self._set_session_id,
            # Agent lifecycle
            get_agent=lambda: self.agent,
            set_agent=self._set_agent,
            create_agent=self._create_agent,
            close_agent_model=self._close_agent_model,
            close_mcp_tools=self._close_mcp_tools,
            run_mcp_health_check=self._run_mcp_health_check,
            # Mode management
            get_plan_mode=lambda: self.plan_mode,
            set_plan_mode=self._set_plan_mode_raw,
            get_agent_plan_mode=lambda: self._agent_plan_mode,
            set_agent_plan_mode=self._set_agent_plan_mode,
            # Refs
            confirm_ref=self.confirm_ref,
            auto_ref=self.auto_ref,
            auto_execute_ref=self.auto_execute_ref,
            pending_plan_ref=self.pending_plan_ref,
            enter_plan_ref=self.enter_plan_ref,
            pending_reason_ref=self.pending_reason_ref,
            pending_revise_ref=self.pending_revise_ref,
            # Session stats
            get_session_stats=lambda: self.session_stats,
            set_session_stats=self._set_session_stats,
            # Streaming / agent interaction
            send_to_agent=self._send_to_agent,
            set_pending_skill_message=self._set_pending_skill_message,
            # REPL control
            set_running=self._set_running,
            shutdown_loop=self._shutdown_loop,
            ensure_session_dir=self._ensure_session_dir,
            # Tools access
            get_coding_tools=self._get_coding_tools,
            get_snapshot_store=self._get_snapshot_store,
            # Last response text
            get_last_response_text=lambda: self._last_response_text,
            get_last_final_text=lambda: self._last_final_text,
            # Hooks
            fire_mode_switch=self._fire_mode_switch,
            fire_session_start=self._fire_session_start,
            fire_session_end=self._fire_session_end,
            load_hooks_config=self._load_hooks_config,
            get_hooks_config=lambda: self._hooks_config,
            set_hooks_config=self._set_hooks_config,
            update_hooks_ref=self._update_hooks_ref,
            # Plan file tracking
            get_last_plan_file=lambda: self._last_plan_file,
            set_last_plan_file=self._set_last_plan_file,
            # Session switch
            switch_session=self._switch_session,
            # Context limit
            get_context_limit=self._get_context_limit,
            # Model ID
            get_model_id=lambda: self._model_id,
            # Session dir created
            get_session_dir_created=lambda: self._session_dir_created,
            set_session_dir_created=self._set_session_dir_created,
            # Last per-request input tokens
            get_last_request_input_tokens=lambda: self._last_request_input_tokens,
            # Attachment stack
            get_attachment_stack=self._get_attachment_stack,
            # Skill command cache refresh
            refresh_skill_commands=self._refresh_skill_commands,
        )

    # ── Setters for CommandContext callbacks ──

    def _set_session_id(self, sid: str) -> None:
        self.session_id = sid
        self.config.session_id = sid
        self.session_id_ref[0] = sid

    def _set_agent(self, agent: object) -> None:
        self.agent = agent

    def _set_plan_mode_raw(self, enabled: bool) -> None:
        self.plan_mode = enabled

    def _set_agent_plan_mode(self, enabled: bool) -> None:
        self._agent_plan_mode = enabled

    def _set_session_stats(self, stats) -> None:
        self.session_stats = stats
        from hooty.tools.sub_agent_tools import _session_stats_ref
        _session_stats_ref[0] = stats

    def _set_pending_skill_message(self, msg: str) -> None:
        self._pending_skill_message = msg

    def _set_running(self, running: bool) -> None:
        self.running = running

    def _set_hooks_config(self, config: dict) -> None:
        self._hooks_config = config

    def _set_last_plan_file(self, path: str | None) -> None:
        self._last_plan_file = path

    def _set_session_dir_created(self, created: bool) -> None:
        self._session_dir_created = created

    def _get_attachment_stack(self) -> AttachmentStack:
        if self._attachment_stack is None:
            from hooty.attachment import AttachmentStack as _AS
            self._attachment_stack = _AS()
        return self._attachment_stack

    def _preload_attachments(self, paths: list[str]) -> None:
        """Pre-populate attachment stack from --attach CLI paths."""
        from pathlib import Path

        from hooty.commands.attach import _format_attachment_line
        from hooty.model_catalog import get_context_limit as _gcl

        stack = self._get_attachment_stack()
        self._ensure_session_dir()
        attachments_dir = None
        if self.config.session_dir:
            attachments_dir = self.config.session_dir / "attachments"

        ctx_limit = _gcl(self.config)

        for file_path in paths:
            p = Path(file_path)
            if not p.is_absolute():
                p = Path(self.config.working_directory) / p

            result = stack.add(
                p,
                config=self.config,
                attachments_dir=attachments_dir,
                context_limit=ctx_limit,
            )
            if isinstance(result, str):
                self.console.print(f"  {result}")
            else:
                line = _format_attachment_line(result, stack.count)
                self.console.print(line)
                if (
                    result.kind == "text"
                    and result.estimated_tokens > self.config.attachment.large_file_tokens
                ):
                    self.console.print(
                        f"  \u26a0\ufe0f  Large file (~{result.estimated_tokens} tokens). "
                        f"Consider trimming before attaching."
                    )

    def _ensure_session_dir(self) -> None:
        """Create the per-session directory on first use (idempotent)."""
        if self._session_dir_created:
            return
        if self.config.session_tmp_dir:
            self.config.session_tmp_dir.mkdir(parents=True, exist_ok=True)
            self._session_dir_created = True
            # Bind workspace to current working directory (skip if rebind is pending —
            # deferred rebind writes workspace.yaml on first actual interaction instead)
            if not self._workspace_needs_rebind:
                from hooty.workspace import save_workspace
                if self.config.session_dir:
                    save_workspace(self.config.session_dir, self.config.working_directory)

    def _setup_prompt(self) -> None:
        """Initialize prompt_toolkit session (separated to avoid terminal conflicts with Rich Live)."""
        from prompt_toolkit import PromptSession
        from prompt_toolkit.completion import Completer, Completion
        from prompt_toolkit.formatted_text import HTML
        from prompt_toolkit.history import FileHistory
        from prompt_toolkit.key_binding import KeyBindings
        from prompt_toolkit.styles import Style as PtStyle

        self._HTML = HTML
        history_path = str(self.config.config_dir / "history")

        repl_ref = self  # capture for inner class

        class _SlashCommandCompleter(Completer):
            """Tab-complete slash commands."""

            def get_completions(self, document: object, complete_event: object) -> Completion:
                text = document.text_before_cursor  # type: ignore[attr-defined]
                if not text.startswith("/"):
                    return
                for cmd, desc in list(SLASH_COMMANDS) + repl_ref._skill_command_cache:
                    if cmd.startswith(text) and cmd != text:
                        insert = cmd.split("<")[0] if "<" in cmd else cmd
                        yield Completion(
                            insert,
                            start_position=-len(text),
                            display=cmd,
                            display_meta=desc,
                        )

        # Ignore Enter on empty input so the prompt stays in place
        kb = KeyBindings()

        @kb.add("enter")
        def _handle_enter(event: object) -> None:
            buf = event.current_buffer  # type: ignore[attr-defined]
            doc = buf.document
            line = doc.current_line_before_cursor
            if line.endswith("\\"):
                buf.delete_before_cursor(1)  # remove trailing \
                buf.insert_text("\n")
            elif buf.text.strip():
                buf.validate_and_handle()

        @kb.add("escape", "escape")
        def _handle_double_escape(event: object) -> None:
            buf = event.current_buffer  # type: ignore[attr-defined]
            if buf.text:
                buf.reset()

        @kb.add("c-l")
        def _handle_ctrl_l(event: object) -> None:
            event.app.renderer.clear()  # type: ignore[attr-defined]

        @kb.add("c-x", "c-e")
        def _handle_editor(event: object) -> None:
            buf = event.current_buffer  # type: ignore[attr-defined]
            buf.open_in_editor(event.app)  # type: ignore[attr-defined]

        @kb.add("c-d")
        def _handle_ctrl_d(event: object) -> None:
            buf = event.current_buffer  # type: ignore[attr-defined]
            if buf.text and buf.text != "!":
                return
            now = time.monotonic()
            if now - self._last_eof_time < 1.0:
                event.app.exit(exception=EOFError())  # type: ignore[attr-defined]
            else:
                self._last_eof_time = now
                event.app.invalidate()  # type: ignore[attr-defined]

        @kb.add("s-tab")
        def _handle_shift_tab(event: object) -> None:
            if event.current_buffer.text.startswith("!"):  # type: ignore[attr-defined]
                return
            self.plan_mode = not self.plan_mode

        from prompt_toolkit.layout.processors import Processor, Transformation
        from prompt_toolkit.lexers import Lexer as PtLexer

        class _HideBangPrefix(Processor):
            """Hide the leading '!' on the first line when in bang mode."""

            def apply_transformation(self, transformation_input):
                lineno = transformation_input.lineno
                fragments = transformation_input.fragments
                if lineno == 0 and fragments:
                    text = transformation_input.document.text
                    if text.startswith("!"):
                        new_frags = []
                        removed = False
                        for style, frag_text, *rest in fragments:
                            if not removed and frag_text.startswith("!"):
                                frag_text = frag_text[1:]
                                removed = True
                            if frag_text:
                                new_frags.append((style, frag_text, *rest))
                        return Transformation(
                            new_frags,
                            source_to_display=lambda i: max(0, i - 1),
                            display_to_source=lambda i: i + 1,
                        )
                return Transformation(fragments)

        def _dynamic_prompt() -> HTML:
            """Switch prompt indicator based on input content."""
            try:
                app = self._prompt_session.app
                if app and app.current_buffer.text.startswith("!"):
                    return HTML("<b><style fg='#e8943a'>!</style></b> ")
            except AttributeError:
                pass
            stack = self._attachment_stack
            if stack and stack.count > 0:
                return HTML(f"<b><style fg='#80b0d0'>[📎 {stack.count}]</style></b> <b>❯</b> ")
            return HTML("<b>❯</b> ")

        self._dynamic_prompt = _dynamic_prompt

        class _BangLexer(PtLexer):
            """Colour input text orange when in bang-command mode."""

            def lex_document(self, document: object) -> object:
                lines = document.lines  # type: ignore[attr-defined]
                is_bang = document.text.startswith("!")  # type: ignore[attr-defined]

                def get_line(lineno: int) -> list:
                    line = lines[lineno]
                    if is_bang:
                        return [("class:bang-input", line)]
                    return [("", line)]

                return get_line

        self._prompt_session: PromptSession[str] = PromptSession(
            history=FileHistory(history_path),
            completer=_SlashCommandCompleter(),
            key_bindings=kb,
            lexer=_BangLexer(),
            input_processors=[_HideBangPrefix()],
            multiline=True,
            prompt_continuation="  ",
            bottom_toolbar=self._get_toolbar,
            style=PtStyle.from_dict({
                "bang-input": "#e8943a",
                "bottom-toolbar": "noreverse",
                # Completion menu: no background fill, text colors only
                "completion-menu": "bg: noinherit",
                "completion-menu.completion": "bg: noinherit #888888",
                "completion-menu.completion.current": "bg: noinherit bold #E6C200",
                "completion-menu.meta.completion": "bg: noinherit #666666",
                "completion-menu.meta.completion.current": "bg: noinherit #E6C200",
                # Scrollbar
                "scrollbar.background": "bg:#333333",
                "scrollbar.button": "bg:#666666",
            }),
        )

    def _ensure_packages(self) -> None:
        """Check for required packages and offer to download if missing."""
        from hooty.pkg_manager import missing_packages

        missing = missing_packages()
        if not missing:
            return

        cfg = self.config
        if cfg.pkg_auto_download is None:
            # First run: show dialog with package list and source
            from hooty.pkg_manager import _REGISTRY
            from hooty.ui import hotkey_select

            lines = ["The following packages will be installed:"]
            for name, display in missing:
                info = _REGISTRY.get(name)
                repo_url = f"github.com/{info.repo}" if info else ""
                lines.append(f"  - {display}  ({repo_url})")
            subtitle = "\n".join(lines)

            choice = hotkey_select(
                [("Y", "Yes — download now"), ("N", "No — use fallback")],
                title="Download required packages?",
                subtitle=subtitle,
                border_style="#E6C200",
                con=self.console,
            )
            approved = choice == "Y"
            cfg.save_pkg_auto_download(approved)
            if approved:
                self._download_packages(missing)
        elif cfg.pkg_auto_download:
            self._download_packages(missing)
        # else: user declined — do nothing

    def _download_packages(self, packages: list[tuple[str, str]]) -> None:
        """Download a list of missing packages with progress output."""
        from hooty.pkg_manager import ensure_pkg

        for name, display in packages:
            self.console.print(f"  [dim]Downloading {display}...[/dim]")
            result = ensure_pkg(name)
            if result:
                self.console.print(f"  [dim]{display} installed.[/dim]")
            else:
                self.console.print(f"  [dim]{display} download failed — using fallback.[/dim]")
        self.console.print()

    def start(self) -> None:
        """Start the REPL loop."""
        from agno.utils.log import logger as agno_logger

        if self.config.debug:
            # Only enable debug for hooty and agno loggers, not globally
            # (botocore, markdown_it, asyncio etc. are extremely noisy)
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(levelname)-8s %(name)s: %(message)s"))
            handler.setLevel(logging.DEBUG)

            logger.setLevel(logging.DEBUG)
            logger.addHandler(handler)
            logger.propagate = False

            agno_logger.setLevel(logging.DEBUG)
            for h in agno_logger.handlers:
                h.setLevel(logging.DEBUG)

            # Anthropic SDK retry/request logging
            sdk_logger = logging.getLogger("anthropic")
            sdk_logger.setLevel(logging.DEBUG)
            sdk_logger.addHandler(handler)
            sdk_logger.propagate = False
        else:
            agno_logger.setLevel(logging.CRITICAL)
            for h in agno_logger.handlers:
                h.setLevel(logging.CRITICAL)
            logger.setLevel(logging.WARNING)

        # Silent startup maintenance
        try:
            from hooty.session_lock import cleanup_stale_locks
            cleanup_stale_locks(self.config)
        except Exception:
            pass
        try:
            from hooty.session_store import cleanup_orphan_dirs
            cleanup_orphan_dirs(self.config)
        except Exception:
            pass

        # Acquire lock for new sessions (--continue/--resume already locked in main.py)
        if not self.config.continue_session and not self.config.resume:
            from hooty.session_lock import acquire_lock
            acquire_lock(self.config, self.session_id)

        # CLI resume (--resume / --continue): workspace mismatch warning only.
        # Rebind is deferred to _ensure_session_dir() (triggered on first agent run),
        # so quitting immediately after the warning does NOT overwrite workspace.yaml.
        if self.config.resume or self.config.continue_session:
            if self.config.session_dir and self.config.session_dir.exists():
                from hooty.workspace import check_workspace_mismatch
                stored_wd = check_workspace_mismatch(
                    self.config.session_dir, self.config.working_directory
                )
                if stored_wd:
                    self._workspace_needs_rebind = True
                    self.console.print(
                        f"\n  [bold yellow]🚫 Workspace mismatch[/bold yellow]"
                        f"\n  [dim]Session directory:[/dim]  [white]{stored_wd}[/white]"
                        f"\n  [dim]Current directory:[/dim]  [white]{self.config.working_directory}[/white]"
                        f"\n  [dim]Session will rebind on next interaction.[/dim]\n"
                    )

        # Ensure required packages are available (download if user approved)
        self._ensure_packages()

        # Phase 1: Heavy initialization (agno imports + agent creation) with spinner
        import random

        startup_msg = random.choice([
            "Starting Hooty...",
            "Waking up the hooty...",
            "Warming the wings...",
            "Finding a perch...",
            "Ruffling feathers...",
        ])
        with self.console.status(f"  [dim]{startup_msg}[/dim]", spinner="star", spinner_style="#E6C200", speed=0.3):
            self.agent = self._create_agent()
            self._skill_fingerprint = self._compute_skill_fingerprint()
            self._context_fingerprint = self._compute_context_fingerprint()
            self._load_hooks_config()

        # Save terminal state before REPL starts so we can restore it after
        # Ctrl+C interrupts (the async coroutine cleanup may not complete in
        # time to run _suppress_input()'s finally block).
        self._initial_termios = None
        if termios is not None:
            with contextlib.suppress(termios.error, ValueError, OSError):
                self._initial_termios = termios.tcgetattr(sys.stdin.fileno())

        # Phase 2: prompt_toolkit setup (after spinner to avoid terminal conflicts)
        self._setup_prompt()

        # Install Windows console-ctrl handler to suppress stale CTRL_C_EVENT
        _install_win_ctrl_handler()

        self._print_banner()
        self._run_mcp_health_check()
        self._fire_session_start()

        if self.config.resume or self.config.continue_session:
            self._show_resume_history()

        # Pre-populate attachment stack from --attach CLI option
        if self._initial_attach_files:
            self._preload_attachments(self._initial_attach_files)

        try:
            while self.running:
                try:
                    self._print_rule()
                    user_input = self._prompt_session.prompt(
                        self._dynamic_prompt,
                        refresh_interval=0.5,
                    )
                    self._print_separator()
                    if user_input.strip().startswith("!"):
                        self._handle_bang_command(user_input.strip())
                        continue
                    if user_input.strip().startswith("/"):
                        self._handle_slash_command(user_input.strip())
                        # /skills invoke sets a pending message to send to agent
                        if self._pending_skill_message is not None:
                            msg = self._pending_skill_message
                            self._pending_skill_message = None
                            self._send_to_agent(msg)
                        continue
                    self._send_to_agent(user_input)
                    # Process pending transitions (plan↔code chains)
                    while self._pending_execute or self._pending_plan_start:
                        if self._pending_execute:
                            self._pending_execute = False
                            plan = getattr(self, "_pending_plan", None) or ""
                            plan_file = getattr(self, "_pending_plan_file", None)
                            self._pending_plan = None
                            self._pending_plan_file = None
                            if plan_file:
                                self._send_to_agent(
                                    f"Implement the following plan. "
                                    f"The full design document is saved at:\n"
                                    f"  {plan_file}\n"
                                    f"Read it with read_file() before starting implementation. "
                                    f"Do not re-read source files already analyzed in the plan.\n\n"
                                    f"Plan summary: {plan}"
                                )
                            else:
                                self._send_to_agent(
                                    f"Implement the following plan. Proceed directly — "
                                    f"do not re-read files already analyzed.\n\n{plan}"
                                )
                        if self._pending_plan_start:
                            self._pending_plan_start = False
                            reason = self._pending_plan_input or ""
                            revise_file = self._pending_plan_revise_file
                            coding_ctx = self._pending_plan_context or ""
                            self._pending_plan_input = None
                            self._pending_plan_revise_file = None
                            self._pending_plan_context = None

                            ctx_block = ""
                            if coding_ctx:
                                ctx_block = (
                                    f"\n\n<prior_coding_context>\n"
                                    f"{coding_ctx}\n"
                                    f"</prior_coding_context>\n\n"
                                    f"IMPORTANT: If the prior context contains questions or "
                                    f"open decisions for the user, use ask_user() to confirm "
                                    f"before finalizing the plan. Do NOT assume answers."
                                )

                            if revise_file:
                                self._send_to_agent(
                                    f"Revise the current plan.\n"
                                    f"The current plan is saved at:\n  {revise_file}\n"
                                    f"Read it with read_file() first.\n\n"
                                    f"Reason for revision: {reason}"
                                    f"{ctx_block}\n\n"
                                    f"Produce an updated implementation plan."
                                )
                            else:
                                self._send_to_agent(
                                    f"The previous coding session identified the following issue:\n\n"
                                    f"{reason}"
                                    f"{ctx_block}\n\n"
                                    f"Investigate the codebase and produce an implementation plan."
                                )
                except KeyboardInterrupt:
                    self.console.print("\n  [dim]Use [/dim][slash_cmd]/quit[/slash_cmd][dim] or Ctrl+D twice to exit[/dim]")
                except EOFError:
                    from hooty.commands.misc import cmd_quit
                    cmd_quit(self._cmd_ctx)
        finally:
            self._fire_session_end()
            from hooty.session_lock import release_lock
            release_lock(self.config, self.session_id)
            # Skip MCP / event-loop cleanup — os._exit(0) below will
            # tear down everything.  Calling run_until_complete or
            # loop.close on a (possibly broken) ProactorEventLoop can
            # hang for seconds.
            # Restore terminal state before force-exit so the parent
            # shell's echo / canonical mode is not left broken.
            with contextlib.suppress(Exception):
                self._restore_terminal()
            # Show resume hint if session was persisted
            # (skip if cmd_quit already printed it — running is False after /quit)
            if self._session_dir_created and self.running:
                with contextlib.suppress(Exception):
                    self.console.print(
                        f"\n  [dim]Resume this session with:[/dim] "
                        f"[bold]hooty --resume {self.session_id}[/bold]"
                    )
            # Force-exit to prevent hanging on non-daemon background
            # threads (ProactorEventLoop IOCP, HTTP client pools, etc.).
            with contextlib.suppress(Exception):
                sys.stdout.flush()
            with contextlib.suppress(Exception):
                sys.stderr.flush()
            os._exit(0)

    @property
    def _model_id(self) -> str:
        """Return the current model ID."""
        if self.config.provider.value == "anthropic":
            return self.config.anthropic.model_id
        elif self.config.provider.value == "bedrock":
            return self.config.bedrock.model_id
        elif self.config.provider.value == "azure_openai":
            return self.config.azure_openai.model_id
        elif self.config.provider.value == "openai":
            return self.config.openai.model_id
        elif self.config.provider.value == "ollama":
            return self.config.ollama.model_id
        return self.config.azure.model_id

    @contextlib.contextmanager
    def _sync_output(self) -> typing.Generator[None, None, None]:
        """Enable DEC Synchronized Output on the console during Live.

        Wraps ``Console._write_buffer()`` so that each refresh frame
        (cursor-up + erase + new content) is emitted as a single
        BSU/ESU pair, preventing spinner remnants in scrollback.
        """
        import atexit

        saved_file = self.console._file  # noqa: SLF001
        bsu = _BSUWriter(self.console.file)
        self.console._file = bsu  # noqa: SLF001
        original_wb = self.console._write_buffer  # noqa: SLF001

        def batched_write_buffer() -> None:
            bsu.begin_frame()
            try:
                original_wb()
            finally:
                bsu.end_frame()

        # Safety net: restore cursor visibility on process exit even if
        # finally block is bypassed (e.g. unhandled signal, os._exit).
        def _atexit_show_cursor() -> None:
            try:
                bsu.show_cursor()
            except Exception:
                pass

        atexit.register(_atexit_show_cursor)

        self.console._write_buffer = batched_write_buffer  # noqa: SLF001
        bsu.hide_cursor()
        try:
            yield
        finally:
            # Each cleanup step is individually protected so that a failure
            # in one (e.g. broken pipe on show_cursor) does not skip the
            # remaining steps — leaving the console in a corrupt state.
            try:
                bsu.show_cursor()
            except Exception:
                pass
            atexit.unregister(_atexit_show_cursor)
            self.console._file = saved_file  # noqa: SLF001
            self.console._write_buffer = original_wb  # noqa: SLF001

    @staticmethod
    @contextlib.contextmanager
    def _suppress_input() -> typing.Generator[None, None, None]:
        """Suppress keyboard echo during response rendering."""
        if termios is None:
            yield
            return
        fd = sys.stdin.fileno()
        try:
            old = termios.tcgetattr(fd)
        except (termios.error, ValueError, OSError):
            yield
            return
        try:
            new = termios.tcgetattr(fd)
            new[3] &= ~(termios.ECHO | termios.ICANON)
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            yield
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            termios.tcflush(fd, termios.TCIFLUSH)

    def _restore_terminal(self) -> None:
        """Restore terminal to saved initial state and reset cursor position."""
        if termios is not None and self._initial_termios is not None:
            with contextlib.suppress(termios.error, ValueError, OSError):
                termios.tcsetattr(
                    sys.stdin.fileno(), termios.TCSANOW, self._initial_termios,
                )
        sys.stdout.write("\n\r\033[K")
        sys.stdout.flush()

    def _print_rule(self) -> None:
        """Print a horizontal rule above the prompt."""
        width = self.console.width
        self.console.print("─" * width, style="#444444")

    def _print_separator(self) -> None:
        """Print a light separator below the prompt."""
        width = self.console.width
        print(f"\033[38;5;238m{'╌' * width}\033[0m\n", flush=True)

    @staticmethod
    def _tool_bullet(tool_name: str) -> tuple[str, str]:
        """Return (icon, color) based on the tool being called."""
        _MAP: dict[str, tuple[str, str]] = {
            # File read
            "read_file":     ("🔍", "#80c8c8"),
            "ls":            ("🔍", "#80c8c8"),
            "find":          ("🔍", "#80c8c8"),
            "grep":          ("🔍", "#80c8c8"),
            "tree":          ("🔍", "#80c8c8"),
            "list_files":    ("🔍", "#80c8c8"),   # Agno legacy
            "search_files":  ("🔍", "#80c8c8"),   # Agno legacy
            # File write
            "write_file":          ("✏️", "#80c880"),
            "edit_file":           ("✏️", "#80c880"),
            "apply_patch":         ("✏️", "#80c880"),
            "move_file":           ("✏️", "#80c880"),
            "create_directory":    ("✏️", "#80c880"),
            "save_file":           ("✏️", "#80c880"),   # Agno legacy
            "replace_file_chunk":  ("✏️", "#80c880"),   # Agno legacy
            # Shell
            "run_shell":         ("⚡", "#c8c880"),
            "run_shell_command": ("⚡", "#c8c880"),   # Agno legacy
            "run_powershell":    ("⚡", "#c8c880"),
            # Web
            "web_search":   ("🌐", "#80c8c8"),
            "search_news":  ("🌐", "#80c8c8"),
            "web_fetch":    ("🌐", "#80c8c8"),
            # Database
            "list_tables":     ("🗄️", "#c8a880"),
            "describe_table":  ("🗄️", "#c8a880"),
            "run_sql_query":   ("🗄️", "#c8a880"),
            # GitHub
            "create_issue":        ("🐙", "#c0c0c0"),
            "create_pull_request": ("🐙", "#c0c0c0"),
            "get_pull_request":    ("🐙", "#c0c0c0"),
            # Memory
            "update_user_memory": ("📌", "#c0a0c0"),
            # Reasoning
            "think":   ("💭", "#a0a0d0"),
            "analyze": ("💭", "#a0a0d0"),
            # Skills
            "get_skill_instructions": ("🧰", "#a0c0e0"),
            "get_skill_reference":    ("🧰", "#a0c0e0"),
            "get_skill_script":       ("🧰", "#a0c0e0"),
            # Sub-agents
            "run_agent": ("🤖", "#c0a0e0"),
        }
        if tool_name in _MAP:
            return _MAP[tool_name]
        return ("●", "#80c8c8")

    def _sub_agent_event_handler(
        self, event_type: str, agent_name: str, detail: str, hint: str = "",
    ) -> None:
        """Handle sub-agent lifecycle events for tree visualization."""
        from hooty.tools.confirm import _active_live

        live = _active_live[0]
        if live is None:
            return

        try:
            if event_type == "start":
                # Lower refresh rate during sub-agent execution to reduce
                # ConPTY timing conflicts that burn spinner frames into
                # scrollback.
                live.refresh_per_second = 2
                task_display = detail[:80] + "..." if len(detail) > 80 else detail
                live.console.print(
                    f"  [#c0a0e0]\U0001f916 {agent_name}[/#c0a0e0]: "
                    f"[dim]\"{task_display}\"[/dim]"
                )
            elif event_type == "tool_call":
                bullet, color = self._tool_bullet(detail)
                hint_part = f"  [dim]({hint})[/dim]" if hint else ""
                live.console.print(
                    f"  [{color}] \u251c\u2500 {bullet} {detail}[/{color}]{hint_part}"
                )
            elif event_type == "retry":
                live.console.print(
                    f"  [#c0a0e0] \u2502  [dim]\u26a0 {detail}[/dim][/#c0a0e0]"
                )
            elif event_type == "complete":
                live.console.print(
                    f"  [#c0a0e0] \u2514\u2500 \u2713 Complete ({detail} tool calls)[/#c0a0e0]"
                )
                # Restore normal refresh rate after sub-agent completes.
                live.refresh_per_second = 4
        except Exception:
            pass

    def _owl_eyes(self) -> tuple[str, str]:
        """Return (eye_char, eye_color) based on current hour and config."""
        return owl_eyes(datetime.now().hour, *self.config.awake)

    def _print_banner(self) -> None:
        """Print the welcome banner with owl mascot."""
        eye_char, eye_color = self._owl_eyes()

        from rich.panel import Panel
        from rich.text import Text as RichText

        lines = RichText()
        lines.append("   ,___,\n", style="banner.owl")
        lines.append("   (")
        lines.append(eye_char, style=f"bold {eye_color}")
        lines.append(",")
        lines.append(eye_char, style=f"bold {eye_color}")
        lines.append(")")
        lines.append("    Hooty", style="bold #E6C200")
        lines.append(f" v{__version__}", style="white")
        if self.config.credentials_active:
            lines.append(" (Caged)", style="dim white")
        lines.append("\n", style="white")
        lines.append("   /)  )", style="banner.owl")
        if self.config.active_profile:
            profile_label = f"{self.config.active_profile} ({self.config.provider.value} / {self._model_id})"
            lines.append("    Profile: ", style="banner.info")
            lines.append(f"{profile_label}\n", style="white")
        else:
            provider_label = f"{self.config.provider.value.title()} ({self._model_id})"
            lines.append("    Provider: ", style="banner.info")
            lines.append(f"{provider_label}\n", style="white")
        lines.append("  --\"\"--", style="banner.owl")
        lines.append("    Working directory: ", style="banner.info")
        wd = str(self.config.working_directory)
        banner_width = min(self.console.width, 80)
        max_path = max(banner_width - 35, 20)
        if len(wd) > max_path:
            wd = "..." + wd[-(max_path - 3):]
        lines.append(f"{wd}", style="white")

        r_mode = self.config.reasoning.mode
        if r_mode != "off":
            if self.config._reasoning_active:
                lines.append(f"  \U0001f4ad {r_mode}", style="#bb86fc")
            else:
                lines.append(f"  \U0001f4ad {r_mode} (inactive)", style="dim")
        lines.append("\n")

        self.console.print()
        self.console.print(Panel(lines, border_style="#2E5A3C", expand=False, padding=(0, 3, 0, 0)))
        self.console.print()

    def _show_resume_history(self) -> None:
        """Display past Q&A pairs when resuming a session."""
        try:
            count = int(self.config.resume_history)
        except (TypeError, ValueError):
            return
        if count <= 0:
            return

        from hooty.conversation_log import load_recent_history

        entries = load_recent_history(
            self.config.project_dir, self.session_id, count,
        )

        # Fallback: Agno DB (last 1 only)
        if not entries:
            try:
                last_run = self.agent.get_last_run_output(session_id=self.session_id)
                if last_run and last_run.content:
                    entries = [{"input": "", "output": str(last_run.content)}]
            except Exception:
                pass

        if not entries:
            return

        from rich.markdown import Markdown

        width = self.console.width
        for entry in entries:
            user_input = entry.get("input", "")
            output = entry.get("output", "")

            # Rule line (same as _print_rule)
            self.console.print("─" * width, style="#444444")

            # Prompt + user input (same as ❯ prompt)
            if user_input:
                self.console.print(f"[bold]❯[/bold] [dim]{user_input}[/dim]")
            else:
                self.console.print("[bold]❯[/bold] [dim]…[/dim]")

            # Separator (same as _print_separator)
            print(f"\033[38;5;238m{'╌' * width}\033[0m\n", flush=True)

            # Truncate long outputs: keep last 4000 chars
            if len(output) > 4000:
                output = "…" + output[-3999:]
                nl = output.find("\n")
                if 0 < nl < 200:
                    output = output[nl + 1:]

            # Response as Markdown (same as agent output)
            self.console.print(Markdown(output))
            self.console.print()

    # ── Agent interaction ──

    def _send_to_agent(self, message: str) -> None:
        """Send a message to the agent and render the response without borders."""
        from hooty.tools.confirm import _auto_approve

        _auto_approve[0] = False
        self._ensure_session_dir()
        # Deferred workspace rebind — only on actual interaction
        if self._workspace_needs_rebind and self.config.session_dir:
            from hooty.workspace import save_workspace
            save_workspace(self.config.session_dir, self.config.working_directory)
            self._workspace_needs_rebind = False

        # --- Hook: UserPromptSubmit ---
        message = self._fire_user_prompt_submit(message)
        if message is None:
            return  # blocked by hook

        # --- Context & skill change detection ---
        reload_reasons: list[str] = []

        new_ctx_fp = self._compute_context_fingerprint()
        if new_ctx_fp != self._context_fingerprint:
            reload_reasons.append("Instructions")
            self._context_fingerprint = new_ctx_fp

        if self.config.skills.enabled:
            new_fp = self._compute_skill_fingerprint()
            if new_fp != self._skill_fingerprint:
                reload_reasons.append("Skills")
                self._skill_fingerprint = new_fp

        if reload_reasons:
            self._close_mcp_tools()
            self._close_agent_model()
            self.agent = self._create_agent()
            self._agent_plan_mode = self.plan_mode
            self._refresh_skill_commands()
            label = " & ".join(reload_reasons)
            self.console.print(f"  [dim]{label} changed — agent reloaded.[/dim]")

        if self._agent_plan_mode != self.plan_mode:
            self._close_mcp_tools()
            self._close_agent_model()
            self.agent = self._create_agent()
            self._agent_plan_mode = self.plan_mode
        self.auto_execute_ref[0] = False
        self._apply_reasoning(message)

        # Flush attachment stack
        images = None
        stack = self._get_attachment_stack()
        if stack.count > 0:
            images, text_block = stack.flush()
            if text_block:
                message = message + "\n\n" + text_block

        try:
            if self.config.stream:
                self._stream_response(message, images=images)
            else:
                self._run_response(message, images=images)
        except KeyboardInterrupt:
            from hooty.tools.confirm import _active_live

            live = _active_live[0]
            if live is not None:
                with contextlib.suppress(Exception):
                    live.stop()
                _active_live[0] = None
            self._restore_terminal()
            self.console.print("  [dim]Response cancelled.[/dim]")
            return
        except Exception as e:
            self._fire_response_error(str(e), message)
            err_msg = str(e)
            if "too long" in err_msg or "token" in err_msg.lower():
                self.console.print("  [error]✗ Session history is too long[/error]")
                self.console.print("  [dim]Please restart hooty with a new session[/dim]")
            elif "mcp" in err_msg.lower() or "stdio" in err_msg.lower():
                self.console.print(f"  [error]✗ MCP connection error: {e}[/error]")
                self.console.print("  [dim]Try '/mcp reload' to reconnect.[/dim]")
            elif "cancelled" in err_msg.lower():
                self.console.print("  [error]✗ Request was cancelled[/error]")
            else:
                self.console.print(f"  [error]✗ {e}[/error]")
            return

        # Auto-compact when context usage exceeds threshold
        self._maybe_auto_compact()

        # Auto-transition: plan mode → execute mode
        if self.auto_execute_ref[0]:
            self.auto_execute_ref[0] = False
            plan = self.pending_plan_ref[0]
            self.pending_plan_ref[0] = None
            plan_id = self.pending_plan_id_ref[0]
            self.pending_plan_id_ref[0] = None
            if self._auto_transition_to_execute():
                self._pending_plan = plan
                if plan_id:
                    # Use plan managed by PlanTools
                    from hooty.plan_store import get_plan, update_plan_status, PLAN_STATUS_COMPLETED
                    info = get_plan(self.config, plan_id)
                    if info:
                        plan_file = str(info.file_path)
                        update_plan_status(self.config, plan_file, PLAN_STATUS_COMPLETED)
                    else:
                        plan_file = self._save_plan_file()  # fallback
                else:
                    # Legacy: save _last_response_text as the plan
                    plan_file = self._save_plan_file()
                    if plan_file:
                        from hooty.plan_store import update_plan_status, PLAN_STATUS_COMPLETED
                        update_plan_status(self.config, plan_file, PLAN_STATUS_COMPLETED)
                self._pending_plan_file = plan_file
                if plan_file:
                    self._last_plan_file = plan_file
                self._pending_execute = True

        # Auto-transition: coding mode → plan mode
        if self.enter_plan_ref[0]:
            self.enter_plan_ref[0] = False
            reason = self.pending_reason_ref[0]
            revise = self.pending_revise_ref[0]
            self.pending_reason_ref[0] = None
            self.pending_revise_ref[0] = False
            self._auto_transition_to_plan(reason, revise)

    def _apply_reasoning(self, message: str) -> None:
        """Set reasoning parameters per-request based on mode and keywords."""
        model = getattr(self.agent, "model", None)
        if model is None:
            return

        from hooty.config import (
            detect_reasoning_level, REASONING_LEVEL_BUDGETS,
            REASONING_EFFORT_MAP, supports_adaptive_thinking,
        )

        level = detect_reasoning_level(message, self.config)

        if level is None:
            if hasattr(model, "thinking"):
                model.thinking = None
                if hasattr(model, "request_params"):
                    model.request_params = None
                if hasattr(model, "_orig_max_tokens"):
                    model.max_tokens = model._orig_max_tokens
            if hasattr(model, "reasoning_effort"):
                model.reasoning_effort = None
            return

        if hasattr(model, "thinking"):
            budget = REASONING_LEVEL_BUDGETS[level]
            if not hasattr(model, "_orig_max_tokens"):
                model._orig_max_tokens = model.max_tokens
            model_id = getattr(model, "id", "") or ""
            if supports_adaptive_thinking(model_id):
                effort = REASONING_EFFORT_MAP[level]
                model.thinking = {"type": "adaptive"}
                model.request_params = {"output_config": {"effort": effort}}
            else:
                model.thinking = {"type": "enabled", "budget_tokens": budget}
            model.max_tokens = max(16384, budget + 8192)
        elif hasattr(model, "reasoning_effort"):
            effort = REASONING_EFFORT_MAP[level]
            model_id_lower = (getattr(model, "id", "") or "").lower()
            if "-pro" in model_id_lower:
                effort = "high"
            elif "-chat" in model_id_lower:
                effort = "medium"
            model.reasoning_effort = effort

    @staticmethod
    def _build_bullet_table(bullet: str, color: str, text: str) -> object:
        """Build a borderless table that pairs a bullet icon with wrapped text."""
        from rich.table import Table

        tbl = Table(
            show_header=False, show_edge=False,
            box=None, padding=0, pad_edge=False,
            expand=True,
        )
        tbl.add_column(style=color, no_wrap=True, width=2)
        tbl.add_column()
        tbl.add_row(f"{bullet} ", text.strip())
        return tbl

    def _run_async(self, coro: typing.Coroutine) -> typing.Any:
        """Run a coroutine on the persistent event loop, handling Ctrl+C."""
        global _win_active_task, _win_active_loop  # noqa: PLW0603

        task = self._loop.create_task(coro)

        # Register SIGINT handler for immediate cancellation (POSIX only)
        interrupted = False
        if sys.platform != "win32":
            import signal

            def _on_sigint() -> None:
                nonlocal interrupted
                interrupted = True
                task.cancel()
                # Signal sub-agents to stop
                from hooty.tools.sub_agent_runner import cancel_event
                cancel_event.set()

            self._loop.add_signal_handler(signal.SIGINT, _on_sigint)
        else:
            # Expose task/loop so the Windows console-ctrl handler can
            # cancel via call_soon_threadsafe (mirrors POSIX _on_sigint).
            _win_active_task = task
            _win_active_loop = self._loop

        try:
            return self._loop.run_until_complete(task)
        except KeyboardInterrupt:
            task.cancel()
            # Signal sub-agents to stop
            from hooty.tools.sub_agent_runner import cancel_event
            cancel_event.set()
            # Drain one tick so the cancellation propagates — but skip on
            # Windows where the ProactorEventLoop may already be broken and
            # run_until_complete would hang on IOCP select().
            if sys.platform != "win32":
                with contextlib.suppress(BaseException):
                    self._loop.run_until_complete(asyncio.sleep(0))
            if sys.platform == "win32":
                # On Windows, the ProactorEventLoop may become unusable after
                # KeyboardInterrupt.  Replace it with a fresh loop instead of
                # relying on private CPython APIs (_close_self_pipe).
                with contextlib.suppress(BaseException):
                    self._loop.close()
                self._loop = asyncio.new_event_loop()
                # The model's cached async_client and the global httpx
                # AsyncClient hold connections bound to the old event loop.
                # If not reset, the next arun() reuses the stale client and
                # hangs because HTTP/2 streams cannot operate on a different
                # loop.  Clearing them forces lazy re-creation on the new loop.
                self._reset_async_clients()
                self._update_hooks_ref()
            raise
        except asyncio.CancelledError:
            # On Windows, check cancel_event to distinguish user-initiated
            # Ctrl+C (propagated via call_soon_threadsafe) from unexpected
            # cancellation.  On POSIX, the _on_sigint handler sets
            # ``interrupted`` directly.
            from hooty.tools.sub_agent_runner import cancel_event
            win_interrupted = sys.platform == "win32" and cancel_event.is_set()
            if sys.platform == "win32":
                with contextlib.suppress(BaseException):
                    self._loop.close()
                self._loop = asyncio.new_event_loop()
                self._reset_async_clients()
                self._update_hooks_ref()
            if interrupted or win_interrupted:
                raise KeyboardInterrupt
            raise RuntimeError("Request was cancelled unexpectedly")
        finally:
            if sys.platform != "win32":
                import signal

                self._loop.remove_signal_handler(signal.SIGINT)
            else:
                _win_active_task = None
                _win_active_loop = None

    def _stream_response(self, message: str, *, images=None) -> None:
        """Stream agent response with Live indicator."""
        # Clear sub-agent / shell cancellation from any previous SIGINT
        from hooty.tools.sub_agent_runner import cancel_event
        cancel_event.clear()
        from hooty.tools.shell_runner import _interrupt_event
        _interrupt_event.clear()
        self._run_async(self._async_stream_response(message, images=images))

    async def _async_stream_response(self, message: str, *, images=None) -> None:
        """Stream agent response using async arun()."""
        import time

        global _tool_running, _last_tool_completed, _win_suppressed  # noqa: PLW0603

        from agno.run.agent import RunEvent
        from rich.live import Live
        from rich.markdown import Markdown

        response_text = ""
        pending_text = ""
        had_tool_call = False
        first_event = True
        last_request_input_tokens = 0
        scrollable = ScrollableMarkdown()
        streaming_view: StreamingView | None = None
        showing_scrollable = False
        reasoning_active = False
        reasoning_chars = 0
        _last_display_ts = 0.0       # monotonic timestamp of last display flush
        _DISPLAY_INTERVAL = 0.500    # Timer fallback for long lines (500ms)
        _needs_first_flush = True    # First content token → immediate display
        indicator = ThinkingIndicator(plan_mode=self.plan_mode, safe_mode=self.confirm_ref[0])
        from hooty.config import Provider
        if self.config.provider == Provider.AZURE_OPENAI:
            _model = getattr(self.agent, "model", None)
            if _model and getattr(_model, "reasoning_effort", None):
                indicator._text = "Reasoning..."
        if self.config.mcp:
            indicator.set_tool("connecting...")
        start_time = time.monotonic()
        indicator.set_start_time(start_time)
        debug = self.config.debug

        if debug:
            logger.debug("LLM request started")

        from hooty.tools.confirm import _active_live

        with self._sync_output(), self._suppress_input(), Live(
            indicator,
            console=self.console,
            refresh_per_second=4,
            transient=True,
            vertical_overflow="crop",
        ) as live:
            _active_live[0] = live
            try:
                async for event in self.agent.arun(
                    message,
                    images=images,
                    stream=True,
                    stream_events=True,
                    session_id=self.session_id,
                ):
                    if first_event:
                        indicator.clear_tool()
                        first_event = False

                    event_type = getattr(event, "event", None)
                    if event_type is None:
                        continue

                    if event_type == RunEvent.run_content.value:
                        reasoning_delta = getattr(event, "reasoning_content", None)
                        content = getattr(event, "content", None)

                        if reasoning_delta and self.config._reasoning_active:
                            if not reasoning_active:
                                reasoning_active = True
                                from hooty.config import Provider
                                if self.config.provider == Provider.AZURE_OPENAI:
                                    indicator._text = "Reasoning..."
                                else:
                                    indicator._text = "Extended thinking..."
                                live.update(indicator, refresh=True)
                            reasoning_chars += len(reasoning_delta)
                        elif isinstance(content, str):
                            if reasoning_active:
                                reasoning_active = False
                                indicator._text = "Thinking..."
                                live.update(indicator, refresh=True)
                                from hooty.config import Provider as _Prov
                                if self.config.provider == _Prov.AZURE_OPENAI:
                                    _label = "Reasoning"
                                else:
                                    _label = "Extended thinking"
                                live.console.print(f"  [dim]\U0001f4ad {_label} ({reasoning_chars:,} chars)[/dim]")
                            elif indicator._text == "Reasoning...":
                                indicator._text = "Thinking..."
                                live.update(indicator, refresh=True)
                            response_text += content
                            pending_text += content

                            # Line-based buffering: flush on newline, timer fallback, or first token
                            _now = time.monotonic()
                            _flush = (
                                _needs_first_flush
                                or "\n" in content
                                or (_now - _last_display_ts) >= _DISPLAY_INTERVAL
                            )
                            if _flush:
                                scrollable.set_text(pending_text)
                                _last_display_ts = _now
                                _needs_first_flush = False
                                if not showing_scrollable:
                                    streaming_view = StreamingView(scrollable, indicator)
                                    showing_scrollable = True
                                live.update(streaming_view)

                    elif event_type == RunEvent.tool_call_started.value:
                        tool = getattr(event, "tool", None)
                        tool_name = ""
                        if tool:
                            tool_name = getattr(tool, "tool_name", None) or "tool"
                            indicator.set_tool(tool_name)
                        _tool_running = True
                        _win_suppressed = 0
                        if pending_text:
                            bullet, color = self._tool_bullet(tool_name)
                            tbl = self._build_bullet_table(bullet, color, pending_text)
                            live.update(indicator, refresh=True)
                            live.console.print(tbl)
                            pending_text = ""
                            scrollable.reset()
                            showing_scrollable = False
                            _needs_first_flush = True
                            had_tool_call = True
                        live.update(indicator, refresh=True)

                    elif event_type == RunEvent.tool_call_completed.value:
                        _completed_tool = getattr(event, "tool", None)
                        _completed_name = ""
                        if _completed_tool:
                            _completed_name = getattr(_completed_tool, "tool_name", None) or ""
                        await self._fire_post_tool_use(_completed_name)
                        indicator.clear_tool()
                        live.update(indicator, refresh=True)
                        # Update stale-window state so the Windows
                        # console-ctrl handler knows the tool is done.
                        _tool_running = False
                        _last_tool_completed = time.monotonic()

                    elif event_type == RunEvent.model_request_completed.value:
                        inp = getattr(event, "input_tokens", None)
                        if inp is not None:
                            last_request_input_tokens = inp
                        if debug:
                            elapsed_so_far = time.monotonic() - start_time
                            parts = []
                            out = getattr(event, "output_tokens", None)
                            if inp:
                                parts.append(f"˄{inp:,}")
                            if out:
                                parts.append(f"˅{out:,}")
                            ttft_val = getattr(event, "time_to_first_token", None)
                            if ttft_val is not None:
                                parts.append(f"TTFT: {ttft_val:.2f}s")
                            parts.append(f"elapsed: {elapsed_so_far:.2f}s")
                            logger.debug(
                                "Model request completed (%s)",
                                " ".join(parts),
                            )

                    elif event_type == RunEvent.run_error.value:
                        error_content = getattr(event, "content", None)
                        if error_content:
                            pending_text += f"\n\n**Error:** {error_content}"
                            scrollable.set_text(pending_text)
                            if not showing_scrollable:
                                streaming_view = StreamingView(scrollable, indicator)
                                showing_scrollable = True
                            live.update(streaming_view, refresh=True)

                # Flush any remaining undisplayed content
                if pending_text and scrollable._text != pending_text:
                    scrollable.set_text(pending_text)
                    if not showing_scrollable:
                        streaming_view = StreamingView(scrollable, indicator)
                        showing_scrollable = True
                    live.update(streaming_view, refresh=True)

            except asyncio.CancelledError:
                live.stop()
                raise
            finally:
                _active_live[0] = None
                # Ensure _tool_running is reset even on exception paths
                _tool_running = False

        elapsed = time.monotonic() - start_time
        if debug:
            logger.debug("LLM stream completed (total: %.2fs)", elapsed)

        if pending_text:
            if had_tool_call:
                self.console.print()
            self.console.print(Markdown(pending_text))

        self._last_final_text = pending_text
        self._last_response_text = response_text
        self._last_request_input_tokens = last_request_input_tokens
        self._print_run_footer(elapsed, message)

    def _run_response(self, message: str, *, images=None) -> None:
        """Run agent and display complete response."""
        self._run_async(self._async_run_response(message, images=images))

    async def _async_run_response(self, message: str, *, images=None) -> None:
        """Run agent using async arun()."""
        import time

        from agno.run.agent import RunOutput
        from rich.live import Live
        from rich.markdown import Markdown

        start_time = time.monotonic()
        debug = self.config.debug
        indicator = ThinkingIndicator(plan_mode=self.plan_mode, safe_mode=self.confirm_ref[0])
        from hooty.config import Provider
        if self.config.provider == Provider.AZURE_OPENAI:
            _model = getattr(self.agent, "model", None)
            if _model and getattr(_model, "reasoning_effort", None):
                indicator._text = "Reasoning..."
        if self.config.mcp:
            indicator.set_tool("connecting...")
        indicator.set_start_time(start_time)

        if debug:
            logger.debug("LLM request started (non-stream)")

        with self._sync_output(), self._suppress_input(), Live(
            indicator,
            console=self.console,
            refresh_per_second=4,
            transient=True,
            vertical_overflow="visible",
        ) as live:
            result = await self.agent.arun(
                message,
                images=images,
                stream=False,
                session_id=self.session_id,
            )
            if isinstance(result, RunOutput) and result.content:
                live.update(Markdown(str(result.content)))

        elapsed = time.monotonic() - start_time
        if debug:
            logger.debug("LLM response received (total: %.2fs)", elapsed)
        self._last_response_text = (
            str(result.content) if isinstance(result, RunOutput) and result.content else ""
        )
        self._last_final_text = self._last_response_text
        # Extract per-request input tokens from last run output
        _input_tokens = 0
        try:
            _last_run = self.agent.get_last_run_output(session_id=self.session_id)
            if _last_run and _last_run.messages:
                # Find the last assistant message with metrics (= last LLM request)
                for msg in reversed(_last_run.messages):
                    if msg.role == "assistant" and msg.metrics and msg.metrics.input_tokens:
                        _input_tokens = msg.metrics.input_tokens
                        break
        except Exception:
            pass
        self._last_request_input_tokens = _input_tokens
        self._print_run_footer(elapsed, message)

    def _get_context_limit(self) -> int:
        """Return the context window limit for the current model."""
        return get_context_limit(self.config)

    def _print_run_footer(self, elapsed: float, user_input: str = "") -> None:
        """Print model info, elapsed time, token usage, and context usage after a response."""
        from hooty.session_stats import RunStats

        token_info = ""
        context_info = ""
        reasoning_info = ""
        run_stats = RunStats(elapsed=elapsed)
        try:
            last_run = self.agent.get_last_run_output(session_id=self.session_id)
            if last_run and last_run.metrics:
                m = last_run.metrics
                parts = []
                # Show total input tokens including cache for consistent display across providers
                _cache_read = getattr(m, "cache_read_tokens", 0) or 0
                _cache_write = getattr(m, "cache_write_tokens", 0) or 0
                total_input = (m.input_tokens or 0) + _cache_read + _cache_write
                if total_input:
                    parts.append(f"˄{total_input:,}")
                    run_stats.input_tokens = m.input_tokens
                if m.output_tokens:
                    parts.append(f"˅{m.output_tokens:,}")
                    run_stats.output_tokens = m.output_tokens
                run_stats.total_tokens = (m.input_tokens or 0) + (m.output_tokens or 0)
                run_stats.ttft = getattr(m, "time_to_first_token", None)
                cache_read = getattr(m, "cache_read_tokens", 0) or 0
                cache_write = getattr(m, "cache_write_tokens", 0) or 0
                run_stats.cache_read_tokens = cache_read
                run_stats.cache_write_tokens = cache_write
                if cache_read:
                    parts.append(f"»{cache_read:,}")
                if self.config.debug and cache_write:
                    parts.append(f"«{cache_write:,}")
                if parts:
                    token_info = f" | {' '.join(parts)}"
                ctx_input_tokens = self._last_request_input_tokens if self._last_request_input_tokens else m.input_tokens
                # Add cache tokens for true context window usage
                ctx_input_tokens = (ctx_input_tokens or 0) + cache_read + cache_write
                if ctx_input_tokens:
                    limit = self._get_context_limit()
                    pct = ctx_input_tokens / limit * 100
                    if pct >= 80:
                        context_info = f" | [bold red]ctx {pct:.0f}%[/bold red]"
                    elif pct >= 50:
                        context_info = f" | [yellow]ctx {pct:.0f}%[/yellow]"
                    else:
                        context_info = f" | ctx {pct:.0f}%"
            rt = 0
            if last_run and last_run.metrics:
                rt = getattr(last_run.metrics, "reasoning_tokens", 0) or 0
                run_stats.reasoning_tokens = rt
            if last_run and hasattr(last_run, "reasoning_content") and last_run.reasoning_content:
                rc_len = len(last_run.reasoning_content)
                reasoning_info = f" | \U0001f4ad {rc_len:,} chars"
                if rt > 0:
                    reasoning_info += f" (\U0001f4ad {rt:,} tokens)"
            elif rt > 0:
                reasoning_info = f" | \U0001f4ad {rt:,} tokens"
        except Exception:
            pass
        self.session_stats.add_run(run_stats)

        # Hook: Stop
        self._fire_stop(
            response=self._last_final_text,
            elapsed=elapsed,
            input_tokens=run_stats.input_tokens,
            output_tokens=run_stats.output_tokens,
        )

        from hooty.session_stats import save_persisted_stats
        if self.config.session_dir:
            self._ensure_session_dir()
            save_persisted_stats(self.config.session_dir, self.session_stats)

        if self._last_final_text:
            from hooty.conversation_log import log_conversation
            log_conversation(
                self.config.project_dir,
                session_id=self.session_id,
                model=self._model_id,
                user_input=user_input,
                output=self._last_final_text,
                full_output=self._last_response_text,
                output_tokens=run_stats.output_tokens,
            )

        self.console.print()
        self.console.print(f"  [dim]● {self._model_id} for {elapsed:.1f}s{token_info}{context_info}{reasoning_info}[/dim]")
        self.console.print()

    # ── Slash command dispatch ──

    def _handle_slash_command(self, command: str) -> None:
        """Route slash commands to command modules."""
        from hooty.commands import agents, attach, database, files, hooks_cmd
        from hooty.commands import memory, misc, mcp_cmd, mode, model
        from hooty.commands import plans, project, session, skills
        from hooty.commands import web_cmd, github_cmd

        parts = command.split()
        cmd = parts[0].lower()
        args = parts[1:]

        handlers = {
            "/attach": attach.cmd_attach,
            "/help": misc.cmd_help,
            "/quit": misc.cmd_quit,
            "/exit": misc.cmd_quit,
            "/plan": mode.cmd_plan,
            "/plans": plans.cmd_plans,
            "/code": mode.cmd_code,
            "/auto": mode.cmd_auto,
            "/safe": misc.cmd_safe,
            "/unsafe": misc.cmd_unsafe,
            "/compact": session.cmd_compact,
            "/diff": files.cmd_diff,
            "/new": session.cmd_new,
            "/fork": session.cmd_fork,
            "/session": session.cmd_session,
            "/memory": memory.cmd_memory,
            "/project": project.cmd_project,
            "/model": model.cmd_model,
            "/reasoning": model.cmd_reasoning,
            "/database": database.cmd_database,
            "/mcp": mcp_cmd.cmd_mcp,
            "/skills": skills.cmd_skills,
            "/websearch": web_cmd.cmd_websearch,
            "/github": github_cmd.cmd_github,
            "/hooks": hooks_cmd.cmd_hooks,
            "/agents": agents.cmd_agents,
            "/context": session.cmd_context,
            "/copy": misc.cmd_copy,
            "/rescan": misc.cmd_rescan,
            "/review": files.cmd_review,
            "/rewind": files.cmd_rewind,
            "/add-dir": files.cmd_add_dir,
            "/list-dirs": files.cmd_list_dirs,
        }

        handler = handlers.get(cmd)
        if handler:
            handler(self._cmd_ctx, args)
        elif self._try_skill_shortcut(cmd, args):
            pass  # Handled as skill invocation
        else:
            self.console.print(f"  [error]✗ Unknown command: {cmd}[/error]")
            self.console.print("  [dim]Type /help to see available commands[/dim]")

    def _try_skill_shortcut(self, cmd: str, args: list[str]) -> bool:
        """Try to dispatch an unknown slash command as a skill shortcut.

        Returns True if matched a user-invocable skill.
        """
        if not self.config.skills.enabled:
            return False
        skill_name = cmd.lstrip("/")
        from hooty.skill_store import discover_skills, load_skill_instructions

        skills = discover_skills(self.config)
        skill = next(
            (s for s in skills if s.name == skill_name and s.user_invocable and s.enabled),
            None,
        )
        if skill is None:
            return False
        invoke_args = " ".join(args) if args else ""
        instructions = load_skill_instructions(skill, invoke_args)
        self.console.print(f"  [success]✓ Invoking skill: {skill_name}[/success]")
        self._pending_skill_message = instructions
        return True

    # ── Bang command ──

    def _handle_bang_command(self, raw_input: str) -> None:
        """Execute a shell command directly (bang escape)."""
        import subprocess

        cmd = raw_input[1:]  # strip leading '!'
        if not cmd.strip():
            self.console.print("  [dim]Usage: !<command>  (e.g. !git status)[/dim]")
            return

        try:
            result = subprocess.run(
                cmd,
                shell=True,
                cwd=self.config.working_directory,
                stdin=subprocess.DEVNULL,
            )
            if result.returncode != 0:
                self.console.print(
                    f"  [dim]exit code: {result.returncode}[/dim]"
                )
        except KeyboardInterrupt:
            self.console.print()  # newline after ^C
        except Exception as exc:
            self.console.print(f"  [error]✗ Shell error: {exc}[/error]")

    # ── Toolbar ──

    def _is_bang_mode(self) -> bool:
        """Check if the current input buffer starts with '!'."""
        try:
            app = self._prompt_session.app
            return bool(app and app.current_buffer.text.startswith("!"))
        except AttributeError:
            return False

    def _get_toolbar(self) -> HTML:
        """Return the bottom toolbar content showing current modes."""
        if self._is_bang_mode():
            parts = (
                " <style color='#e8943a'>⚡ shell mode</style>"
                " <style color='#666666'>(Esc×2 to cancel)</style>"
            )
            if self._last_eof_time and time.monotonic() - self._last_eof_time < 1.0:
                parts += " | <style color='#ff8800'>Press Ctrl+D again to exit</style>"
            return self._HTML(parts)

        if self.plan_mode:
            suffix = "(auto)" if self.auto_ref[0] else "mode"
            mode_part = f"<style color='#00cccc'>💡 planning {suffix}</style>"
        else:
            suffix = "(auto)" if self.auto_ref[0] else "mode"
            mode_part = f"<style color='#00cc66'>🚀 coding {suffix}</style>"
        parts = (
            f" {mode_part}"
            f" <style color='#666666'>(shift+tab to switch)</style>"
        )
        if not self.plan_mode:
            safe = "on" if self.confirm_ref[0] else "off"
            safe_color = "#666666" if self.confirm_ref[0] else "#E6C200"
            parts += f" | <style color='{safe_color}'>safe mode: {safe}</style>"
        r_mode = self.config.reasoning.mode
        if r_mode != "off":
            if self.config._reasoning_active:
                parts += f" | <style color='#bb86fc'>\U0001f4ad reasoning ({r_mode})</style>"
            else:
                parts += f" | <style color='#666666'>\U0001f4ad reasoning ({r_mode}, inactive)</style>"
        if self._last_eof_time and time.monotonic() - self._last_eof_time < 1.0:
            parts += " | <style color='#ff8800'>Press Ctrl+D again to exit</style>"
        return self._HTML(parts)

    # ── Agent lifecycle ──

    def _close_agent_model(self) -> None:
        """Close the current agent's model clients to prevent resource leaks."""
        model = getattr(self.agent, "model", None)
        if model is None:
            return
        if hasattr(model, "close"):
            with contextlib.suppress(Exception):
                model.close()
        if hasattr(model, "aclose"):
            with contextlib.suppress(Exception):
                self._loop.run_until_complete(model.aclose())

    def _create_agent(self) -> object:
        """Create an agent with current REPL state."""
        return create_agent(
            self.config,
            plan_mode=self.plan_mode,
            confirm_ref=self.confirm_ref,
            auto_execute_ref=self.auto_execute_ref,
            pending_plan_ref=self.pending_plan_ref,
            enter_plan_ref=self.enter_plan_ref,
            pending_reason_ref=self.pending_reason_ref,
            pending_revise_ref=self.pending_revise_ref,
            session_id_ref=self.session_id_ref,
            pending_plan_id_ref=self.pending_plan_id_ref,
        )

    def _refresh_skill_commands(self) -> None:
        """Rebuild cached list of user-invocable skill slash commands."""
        if not self.config.skills.enabled:
            self._skill_command_cache = []
            return
        from hooty.skill_store import discover_skills

        existing = {cmd.split()[0] for cmd, _ in SLASH_COMMANDS}
        skills = discover_skills(self.config)
        self._skill_command_cache = [
            (f"/{s.name}", s.description)
            for s in skills
            if s.user_invocable and s.enabled and f"/{s.name}" not in existing
        ]

    def _compute_skill_fingerprint(self) -> str:
        """Compute current skill fingerprint for change detection."""
        if not self.config.skills.enabled:
            return ""
        from hooty.skill_store import skill_fingerprint
        return skill_fingerprint(self.config)

    def _compute_context_fingerprint(self) -> tuple:
        """Compute current instruction file fingerprint for change detection."""
        from pathlib import Path
        from hooty.context import context_fingerprint
        return context_fingerprint(
            self.config.config_dir,
            Path(self.config.working_directory),
        )

    def _get_coding_tools(self):
        """Return the HootyCodingTools instance from the agent's tools."""
        from hooty.tools.coding_tools import HootyCodingTools

        for toolkit in getattr(self.agent, "tools", []) or []:
            if isinstance(toolkit, HootyCodingTools):
                return toolkit
        return None

    def _get_snapshot_store(self):
        """Return the FileSnapshotStore from the coding tools, or None."""
        ct = self._get_coding_tools()
        if ct is None:
            return None
        return getattr(ct, "_snapshot_store", None)

    # ── Mode transitions ──

    def _auto_transition_to_execute(self) -> bool:
        """Switch from plan mode to coding mode after exit_plan_mode() approval."""
        if self.auto_ref[0]:
            self._clear_session_runs()
            self.plan_mode = False
            self._close_mcp_tools()
            self._close_agent_model()
            self.agent = self._create_agent()
            self._agent_plan_mode = False
            self._fire_mode_switch("planning", "coding")
            self.console.print("  [success]✓ Auto-switched to Coding mode[/success]")
            return True

        from hooty.ui import hotkey_select

        MODE_OPTIONS = [
            ("Y", "Yes, switch to coding"),
            ("N", "No, stay in planning"),
        ]
        key = hotkey_select(
            MODE_OPTIONS,
            title="\u25cf Switch to coding mode?",
            border_style="cyan",
            con=self.console,
        )
        if key != "Y":
            return False

        self._clear_session_runs()

        self.plan_mode = False
        self._close_mcp_tools()
        self._close_agent_model()
        self.agent = self._create_agent()
        self._agent_plan_mode = False
        self._fire_mode_switch("planning", "coding")
        self.console.print("  [success]✓ Switched to Coding mode[/success]")
        return True

    def _auto_transition_to_plan(self, reason: str | None, revise: bool = False) -> None:
        """Switch from coding mode to planning mode after enter_plan_mode()."""
        if self.auto_ref[0]:
            last_plan = self._last_plan_file
            key = "R" if (revise and last_plan) else "Y"

            self.plan_mode = True
            self._close_mcp_tools()
            self._close_agent_model()
            self.agent = self._create_agent()
            self._agent_plan_mode = True
            self._fire_mode_switch("coding", "planning")
            self.console.print("  [success]✓ Auto-switched to Planning mode[/success]")

            coding_context = self._last_response_text.strip() if self._last_response_text else ""

            if key == "R" and last_plan:
                self._pending_plan_input = reason
                self._pending_plan_revise_file = last_plan
            else:
                self._pending_plan_input = reason
                self._pending_plan_revise_file = None
            self._pending_plan_context = coding_context
            self._pending_plan_start = True
            return

        from hooty.ui import hotkey_select

        last_plan = self._last_plan_file

        if last_plan:
            if revise:
                options = [
                    ("R", "Revise current plan"),
                    ("Y", "Yes, start new plan"),
                    ("N", "No, keep coding"),
                    ("C", "Cancel"),
                ]
            else:
                options = [
                    ("Y", "Yes, start new plan"),
                    ("R", "Revise current plan"),
                    ("N", "No, keep coding"),
                    ("C", "Cancel"),
                ]
        else:
            options = [
                ("Y", "Yes, start new plan"),
                ("N", "No, keep coding"),
                ("C", "Cancel"),
            ]

        subtitle = reason if reason else None
        key = hotkey_select(
            options,
            title="\u25cf Switch to Planning",
            subtitle=subtitle,
            border_style="cyan",
            con=self.console,
        )

        if key in ("N", "C"):
            return

        self.plan_mode = True
        self._close_mcp_tools()
        self._close_agent_model()
        self.agent = self._create_agent()
        self._agent_plan_mode = True
        self._fire_mode_switch("coding", "planning")
        self.console.print("  [success]✓ Switched to Planning mode[/success]")

        coding_context = self._last_response_text.strip() if self._last_response_text else ""

        if key == "R" and last_plan:
            self._pending_plan_input = reason
            self._pending_plan_revise_file = last_plan
        else:
            self._pending_plan_input = reason
            self._pending_plan_revise_file = None
        self._pending_plan_context = coding_context
        self._pending_plan_start = True

    def _save_plan_file(self) -> str | None:
        """Save the last LLM response to a plan markdown file."""
        text = self._last_response_text
        if not text or not text.strip():
            return None
        summary = self.pending_plan_ref[0] or ""
        from hooty.plan_store import save_plan
        return save_plan(self.config, body=text, session_id=self.session_id, summary=summary)

    def _clear_session_runs(self) -> None:
        """Clear session runs from DB to free context for the next phase."""
        try:
            from agno.db.base import SessionType

            session = self.agent.db.get_session(
                session_id=self.session_id,
                session_type=SessionType.AGENT,
            )
            if session and session.runs:
                session.runs = []
                self.agent.db.upsert_session(session)
        except Exception:
            pass

    def _maybe_auto_compact(self) -> None:
        """Auto-compact session when context usage exceeds the configured threshold."""
        if not self.config.auto_compact:
            return
        try:
            last_run = self.agent.get_last_run_output(session_id=self.session_id)
            if not last_run or not last_run.metrics or not last_run.metrics.input_tokens:
                return
            limit = self._get_context_limit()
            ctx_input_tokens = self._last_request_input_tokens or last_run.metrics.input_tokens
            # Add cache tokens for true context window usage
            m = last_run.metrics
            ctx_input_tokens = (ctx_input_tokens or 0) + (getattr(m, "cache_read_tokens", 0) or 0) + (getattr(m, "cache_write_tokens", 0) or 0)
            usage = ctx_input_tokens / limit
            if usage < self.config.auto_compact_threshold:
                return
            pct = usage * 100
            self.console.print(
                f"  [dim]Auto-compacting session (context usage {pct:.0f}%)...[/dim]"
            )
            from hooty.commands.session import cmd_compact
            cmd_compact(self._cmd_ctx)
        except Exception:
            pass

    # ── Session management ──

    def _switch_session(self, new_session_id: str) -> bool:
        """Switch to a different session. Returns True on success."""
        from hooty.session_lock import acquire_lock, release_lock
        from hooty.session_stats import (
            SessionStats,
            load_persisted_stats,
            save_persisted_stats,
        )

        self._fire_session_end()

        if self.config.session_dir:
            save_persisted_stats(self.config.session_dir, self.session_stats)

        old_session_id = self.session_id
        release_lock(self.config, old_session_id)

        if not acquire_lock(self.config, new_session_id):
            acquire_lock(self.config, old_session_id)
            return False

        self.session_id = new_session_id
        self.config.session_id = new_session_id

        # Check workspace mismatch BEFORE _ensure_session_dir
        _stored_wd: str | None = None
        if self.config.session_dir and self.config.session_dir.exists():
            from hooty.workspace import check_workspace_mismatch
            _stored_wd = check_workspace_mismatch(
                self.config.session_dir, self.config.working_directory
            )
        if _stored_wd:
            self._workspace_needs_rebind = True

        self._session_dir_created = False
        self._ensure_session_dir()

        if _stored_wd:
            self.console.print(
                f"\n  [bold yellow]🚫 Workspace mismatch[/bold yellow]"
                f"\n  [dim]Session directory:[/dim]  [white]{_stored_wd}[/white]"
                f"\n  [dim]Current directory:[/dim]  [white]{self.config.working_directory}[/white]"
                f"\n  [dim]Session will rebind on next interaction.[/dim]\n"
            )

        self.session_stats = SessionStats()
        if self.config.session_dir and self.config.session_dir.exists():
            self.session_stats.persisted = load_persisted_stats(self.config.session_dir)

        self._close_mcp_tools()
        self._close_agent_model()
        self.agent = self._create_agent()
        self._agent_plan_mode = self.plan_mode

        # Reset attachment stack on session switch
        self._attachment_stack = None

        self._update_hooks_ref()
        self._fire_session_start()
        self._show_resume_history()

        return True

    def _run_mcp_health_check(self) -> None:
        """Display deferred MCP warnings and run health check."""
        # Show deferred creation warnings (collected during spinner)
        for w in getattr(self.config, "_mcp_warnings", []):
            self.console.print(w)

        if not self.config.mcp:
            return
        try:
            from hooty.tools.mcp_tools import check_mcp_health

            agent_tools = getattr(self.agent, "tools", []) or []
            failed = self._loop.run_until_complete(
                check_mcp_health(agent_tools, console_out=self.console)
            )
            if failed:
                self.console.print(
                    "  [dim]Use '/mcp reload' to retry failed connections.[/dim]"
                )
        except Exception:
            logger.debug("MCP health check failed", exc_info=True)

    def _close_mcp_tools(self) -> None:
        """Close MCP tool connections before event loop shutdown.

        MCPTools uses anyio cancel scopes that are task-local.
        If left to shutdown_asyncgens(), cleanup runs in a different
        task context causing RuntimeError. Closing explicitly in the
        same loop avoids this.
        """
        try:
            from agno.tools.mcp import MCPTools
        except ImportError:
            return
        for toolkit in getattr(self.agent, "tools", []) or []:
            if isinstance(toolkit, MCPTools):
                with contextlib.suppress(BaseException):
                    self._loop.run_until_complete(toolkit.close())

    def _shutdown_loop(self) -> None:
        """Gracefully shut down the asyncio event loop."""
        if self._loop.is_closed():
            return

        if sys.platform == "win32":
            # On Windows, run_until_complete on a broken ProactorEventLoop
            # can hang indefinitely in IOCP select().  Run the teardown in
            # a daemon thread with a short deadline so we never block exit.
            import threading

            def _do_shutdown() -> None:
                with contextlib.suppress(BaseException):
                    try:
                        pending = asyncio.all_tasks(self._loop)
                    except RuntimeError:
                        return
                    for t in pending:
                        t.cancel()
                    if pending:
                        self._loop.run_until_complete(
                            asyncio.wait(pending, timeout=1.0)
                        )
                    self._loop.set_exception_handler(lambda _l, _c: None)
                    self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                    self._loop.run_until_complete(
                        self._loop.shutdown_default_executor(timeout=1)
                    )
                with contextlib.suppress(BaseException):
                    self._loop.close()

            th = threading.Thread(target=_do_shutdown, daemon=True)
            th.start()
            th.join(timeout=3.0)
            # If the thread is still alive the loop is hung — just close it.
            if th.is_alive():
                with contextlib.suppress(BaseException):
                    self._loop.close()
            return

        try:
            pending = asyncio.all_tasks(self._loop)
        except RuntimeError:
            return
        for task in pending:
            task.cancel()
        if pending:
            with contextlib.suppress(BaseException):
                self._loop.run_until_complete(
                    asyncio.wait(pending, timeout=2.0)
                )
        # Suppress noisy errors from MCP async generator cleanup
        # (anyio cancel scope task mismatch) and Windows ProactorEventLoop
        # (CancelledError in _loop_reading, weak-ref TypeError).
        self._loop.set_exception_handler(lambda _loop, _ctx: None)
        with contextlib.suppress(BaseException):
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        with contextlib.suppress(BaseException):
            self._loop.run_until_complete(
                self._loop.shutdown_default_executor(timeout=2)
            )
        with contextlib.suppress(BaseException):
            self._loop.close()

    # ── Hooks ──

    def _load_hooks_config(self) -> None:
        """Load hooks configuration from YAML files."""
        if not self.config.hooks_enabled:
            self._hooks_config = {}
            self._update_hooks_ref()
            return
        from hooty.hooks import apply_disabled_state, load_hooks_config

        self._hooks_config = load_hooks_config(self.config)
        apply_disabled_state(self._hooks_config, self.config)
        self._update_hooks_ref()

    def _update_hooks_ref(self) -> None:
        """Update the shared hooks reference used by confirm.py."""
        from hooty.tools.confirm import _hooks_ref

        _hooks_ref[0] = self._hooks_config
        _hooks_ref[1] = self.session_id
        _hooks_ref[2] = self.config.working_directory
        _hooks_ref[3] = self._loop

    def _reset_async_clients(self) -> None:
        """Reset cached async HTTP clients after an event loop replacement.

        The model's ``async_client`` and agno's global ``httpx.AsyncClient``
        hold connections bound to the old event loop.  Clearing them forces
        lazy re-creation on the next ``arun()`` call with the new loop.
        """
        # 1. Model-level cached async client
        model = getattr(self.agent, "model", None)
        if model is not None:
            with contextlib.suppress(Exception):
                ac = getattr(model, "async_client", None)
                if ac is not None and hasattr(ac, "close"):
                    # Synchronous close — the old loop is already closed so
                    # we cannot await; just release file descriptors.
                    with contextlib.suppress(Exception):
                        ac._client.close()  # inner httpx.AsyncClient
                model.async_client = None

        # 2. agno global httpx.AsyncClient singleton
        try:
            from agno.utils.http import _async_client_lock
            import agno.utils.http as _agno_http

            with _async_client_lock:
                _gc = getattr(_agno_http, "_global_async_client", None)
                if _gc is not None:
                    with contextlib.suppress(Exception):
                        _gc.close()  # synchronous close (releases sockets)
                    _agno_http._global_async_client = None
        except Exception:
            pass

    def _fire_session_start(self) -> None:
        """Emit SessionStart hook."""
        if not self.config.hooks_enabled or not self._hooks_config:
            return
        from hooty.hooks import HookEvent, emit_hook_sync, get_additional_context

        results = emit_hook_sync(
            HookEvent.SESSION_START, self._hooks_config,
            self.session_id, self.config.working_directory,
            loop=self._loop,
            provider=self.config.provider.value,
            model_id=self._model_id,
            plan_mode=self.plan_mode,
            is_resume=self.config.resume or self.config.continue_session,
            non_interactive=False,
        )
        ctx = get_additional_context(results)
        if ctx:
            self._hook_pending_context = ctx

    def _fire_session_end(self) -> None:
        """Emit SessionEnd hook."""
        if not self.config.hooks_enabled or not self._hooks_config:
            return
        from hooty.hooks import HookEvent, emit_hook_sync

        try:
            emit_hook_sync(
                HookEvent.SESSION_END, self._hooks_config,
                self.session_id, self.config.working_directory,
                loop=self._loop,
                total_runs=self.session_stats.total_runs,
                total_elapsed=self.session_stats.total_elapsed,
                total_input_tokens=self.session_stats.total_input_tokens,
                total_output_tokens=self.session_stats.total_output_tokens,
            )
        except Exception:
            logger.debug("SessionEnd hook failed", exc_info=True)

    def _fire_user_prompt_submit(self, message: str) -> str | None:
        """Emit UserPromptSubmit hook. Returns modified message or None if blocked."""
        if not self.config.hooks_enabled or not self._hooks_config:
            if self._hook_pending_context:
                ctx = self._hook_pending_context
                self._hook_pending_context = ""
                message += f"\n\n<hook_context>\n{ctx}\n</hook_context>"
            return message

        from hooty.hooks import (
            HookEvent,
            emit_hook_sync,
            get_additional_context,
            get_block_reason,
            has_blocking,
        )

        results = emit_hook_sync(
            HookEvent.USER_PROMPT_SUBMIT, self._hooks_config,
            self.session_id, self.config.working_directory,
            loop=self._loop,
            message=message,
            plan_mode=self.plan_mode,
        )

        if has_blocking(results):
            reason = get_block_reason(results)
            self.console.print(f"  [warning]⚠ Blocked by hook: {reason}[/warning]")
            return None

        ctx_parts: list[str] = []
        hook_ctx = get_additional_context(results)
        if hook_ctx:
            ctx_parts.append(hook_ctx)
        if self._hook_pending_context:
            ctx_parts.append(self._hook_pending_context)
            self._hook_pending_context = ""
        if ctx_parts:
            message += "\n\n<hook_context>\n" + "\n".join(ctx_parts) + "\n</hook_context>"

        return message

    def _fire_stop(
        self, *, response: str, elapsed: float,
        input_tokens: int, output_tokens: int,
    ) -> None:
        """Emit Stop hook."""
        if not self.config.hooks_enabled or not self._hooks_config:
            return
        from hooty.hooks import HookEvent, emit_hook_sync, get_additional_context

        results = emit_hook_sync(
            HookEvent.STOP, self._hooks_config,
            self.session_id, self.config.working_directory,
            loop=self._loop,
            response=response,
            elapsed=elapsed,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            model_id=self._model_id,
        )
        ctx = get_additional_context(results)
        if ctx:
            self._hook_pending_context = ctx

    def _fire_response_error(self, error: str, message: str) -> None:
        """Emit ResponseError hook."""
        if not self.config.hooks_enabled or not self._hooks_config:
            return
        from hooty.hooks import HookEvent, emit_hook_sync

        try:
            emit_hook_sync(
                HookEvent.RESPONSE_ERROR, self._hooks_config,
                self.session_id, self.config.working_directory,
                loop=self._loop,
                error=error,
                message=message,
            )
        except Exception:
            pass

    async def _fire_post_tool_use(self, tool_name: str) -> None:
        """Emit PostToolUse hook (async, inside streaming loop)."""
        if not self.config.hooks_enabled or not self._hooks_config:
            return
        from hooty.hooks import HookEvent, emit_hook

        await emit_hook(
            HookEvent.POST_TOOL_USE, self._hooks_config,
            self.session_id, self.config.working_directory,
            tool_name=tool_name,
        )

    def _fire_mode_switch(self, from_mode: str, to_mode: str) -> None:
        """Emit ModeSwitch hook."""
        if not self.config.hooks_enabled or not self._hooks_config:
            return
        from hooty.hooks import HookEvent, emit_hook_sync

        try:
            emit_hook_sync(
                HookEvent.MODE_SWITCH, self._hooks_config,
                self.session_id, self.config.working_directory,
                loop=self._loop,
                from_mode=from_mode,
                to_mode=to_mode,
            )
        except Exception:
            pass
