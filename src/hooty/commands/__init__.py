"""Command context and dispatch for Hooty REPL slash commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from rich.console import Console

    from hooty.config import AppConfig
    from hooty.file_snapshot import FileSnapshotStore
    from hooty.session_stats import SessionStats
    from hooty.tools.coding_tools import HootyCodingTools


@dataclass
class CommandContext:
    """Shared context passed to all command handlers.

    All REPL state access goes through explicit fields or callbacks,
    keeping command modules decoupled from the REPL class.
    """

    config: AppConfig
    console: Console

    # Session
    get_session_id: Callable[[], str]
    set_session_id: Callable[[str], None]

    # Agent lifecycle
    get_agent: Callable[[], object]
    set_agent: Callable[[object], None]
    create_agent: Callable[[], object]
    close_agent_model: Callable[[], None]

    # Mode management
    get_plan_mode: Callable[[], bool]
    set_plan_mode: Callable[[bool], None]
    get_agent_plan_mode: Callable[[], bool]
    set_agent_plan_mode: Callable[[bool], None]

    # Safe mode
    confirm_ref: list[bool] = field(default_factory=lambda: [True])

    # Auto mode transitions
    auto_ref: list[bool] = field(default_factory=lambda: [False])

    # Auto-execute / plan refs
    auto_execute_ref: list[bool] = field(default_factory=lambda: [False])
    pending_plan_ref: list[str | None] = field(default_factory=lambda: [None])
    enter_plan_ref: list[bool] = field(default_factory=lambda: [False])
    pending_reason_ref: list[str | None] = field(default_factory=lambda: [None])
    pending_revise_ref: list[bool] = field(default_factory=lambda: [False])

    # Session stats
    get_session_stats: Callable[[], SessionStats] = field(default=lambda: None)  # type: ignore[assignment]
    set_session_stats: Callable[[SessionStats], None] = field(default=lambda _: None)

    # Streaming / agent interaction
    send_to_agent: Callable[[str], None] = field(default=lambda _: None)
    set_pending_skill_message: Callable[[str], None] = field(default=lambda _: None)

    # REPL control
    set_running: Callable[[bool], None] = field(default=lambda _: None)
    shutdown_loop: Callable[[], None] = field(default=lambda: None)
    ensure_session_dir: Callable[[], None] = field(default=lambda: None)

    # Tools access
    get_coding_tools: Callable[[], HootyCodingTools | None] = field(default=lambda: None)  # type: ignore[assignment]
    get_snapshot_store: Callable[[], FileSnapshotStore | None] = field(default=lambda: None)  # type: ignore[assignment]

    # Last response text (for review, mode transitions)
    get_last_response_text: Callable[[], str] = field(default=lambda: "")
    get_last_final_text: Callable[[], str] = field(default=lambda: "")

    # Hooks
    fire_mode_switch: Callable[[str, str], None] = field(default=lambda _a, _b: None)
    fire_session_start: Callable[[], None] = field(default=lambda: None)
    fire_session_end: Callable[[], None] = field(default=lambda: None)
    load_hooks_config: Callable[[], None] = field(default=lambda: None)
    get_hooks_config: Callable[[], dict] = field(default=lambda: {})
    set_hooks_config: Callable[[dict], None] = field(default=lambda _: None)
    update_hooks_ref: Callable[[], None] = field(default=lambda: None)

    # Plan file tracking
    get_last_plan_file: Callable[[], str | None] = field(default=lambda: None)
    set_last_plan_file: Callable[[str | None], None] = field(default=lambda _: None)

    # Session switch
    switch_session: Callable[[str], bool] = field(default=lambda _: False)

    # Context limit
    get_context_limit: Callable[[], int] = field(default=lambda: 200000)

    # Model ID
    get_model_id: Callable[[], str] = field(default=lambda: "")

    # Session dir created flag
    get_session_dir_created: Callable[[], bool] = field(default=lambda: False)
    set_session_dir_created: Callable[[bool], None] = field(default=lambda _: None)

    # Last per-request input tokens (for accurate ctx % calculation)
    get_last_request_input_tokens: Callable[[], int] = field(default=lambda: 0)

    # MCP tools lifecycle
    close_mcp_tools: Callable[[], None] = field(default=lambda: None)
    run_mcp_health_check: Callable[[], None] = field(default=lambda: None)

    # Attachment stack access
    get_attachment_stack: Callable[[], object] = field(default=lambda: None)

    # Skill command cache refresh
    refresh_skill_commands: Callable[[], None] = field(default=lambda: None)
