"""Sub-agent execution engine — creates and runs ephemeral Agno agents."""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from hooty.agent_store import NEVER_INHERIT, AgentDef

if TYPE_CHECKING:
    from hooty.config import AppConfig

logger = logging.getLogger("hooty")

# Module-level cancellation event — set by REPL on SIGINT to stop sub-agents
cancel_event = threading.Event()

# Primary arg to show as hint per tool name
_HINT_KEY: dict[str, str] = {
    "read_file": "file_path",
    "write_file": "file_path",
    "edit_file": "file_path",
    "apply_patch": "patch",
    "move_file": "src",
    "create_directory": "path",
    "save_file": "file_path",           # Agno legacy
    "replace_file_chunk": "file_path",  # Agno legacy
    "ls": "path",
    "find": "pattern",
    "grep": "pattern",
    "list_files": "path",               # Agno legacy
    "search_files": "pattern",          # Agno legacy
    "run_shell": "command",
    "run_powershell": "command",
    "web_fetch": "url",
    "web_search": "query",
    "search_news": "query",
}


def _tool_hint(tool_name: str, tool_args: dict[str, Any], cwd: str = "") -> str:
    """Extract a short hint string from tool arguments."""
    key = _HINT_KEY.get(tool_name)
    if key and key in tool_args:
        value = str(tool_args[key])
        # For run_shell, show just the first line
        if key == "command":
            value = value.split("\n")[0]
            if len(value) > 60:
                value = value[:57] + "..."
        elif key == "patch":
            # Extract file paths from patch text for a meaningful hint
            value = _extract_patch_files(value, cwd)
        else:
            value = _shorten_path(value, cwd)
        return value
    # Fallback: try common keys
    for fallback in ("file_path", "path", "file", "pattern", "query", "directory"):
        if fallback in tool_args:
            value = _shorten_path(str(tool_args[fallback]), cwd)
            return value
    return ""


def _extract_patch_files(patch: str, cwd: str) -> str:
    """Extract file paths from a patch text for display as a hint."""
    import re
    paths = re.findall(r"\*\*\* (?:Add|Update|Delete) File: (.+)", patch)
    if not paths:
        # Fallback: truncate patch text
        first_line = patch.split("\n")[0]
        if len(first_line) > 60:
            return first_line[:57] + "..."
        return first_line
    shortened = [_shorten_path(p.strip(), cwd) for p in paths]
    result = ", ".join(shortened)
    if len(result) > 60:
        result = result[:57] + "..."
    return result


def _shorten_path(value: str, cwd: str) -> str:
    """Make a path relative to cwd if under it, otherwise keep full path."""
    if cwd:
        # Ensure cwd ends with / for prefix matching
        prefix = cwd.rstrip("/") + "/"
        if value.startswith(prefix):
            value = value[len(prefix):] or "."
        elif value == cwd.rstrip("/"):
            value = "."
    if len(value) > 60:
        value = "..." + value[-57:]
    return value


def _create_sub_agent_model(agent_def: AgentDef, config: AppConfig) -> Any:
    """Create a model for the sub-agent.

    Uses agent_def.model if specified, otherwise inherits from parent config.
    Reasoning/thinking is always disabled for sub-agents.
    """
    from hooty.config import AppConfig as _AC, Provider
    from hooty.providers import create_model

    if agent_def.model:
        # Build a minimal config with the sub-agent's model settings
        sub_config = _AC(
            provider=Provider(agent_def.model.provider),
            working_directory=config.working_directory,
        )
        # Copy credentials/auth and API timeout from parent
        sub_config.bedrock = config.bedrock
        sub_config.anthropic = config.anthropic
        sub_config.azure = config.azure
        sub_config.azure_openai = config.azure_openai
        sub_config.ollama = config.ollama
        sub_config.provider_env = config.provider_env
        sub_config.cache_system_prompt = config.cache_system_prompt
        sub_config.api_connect_timeout = config.api_connect_timeout
        sub_config.api_streaming_read_timeout = config.api_streaming_read_timeout
        sub_config.api_read_timeout = config.api_read_timeout

        # Apply sub-agent model_id override
        provider = Provider(agent_def.model.provider)
        if provider == Provider.BEDROCK:
            sub_config.bedrock.model_id = agent_def.model.model_id
        elif provider == Provider.ANTHROPIC:
            sub_config.anthropic.model_id = agent_def.model.model_id
        elif provider == Provider.AZURE:
            sub_config.azure.model_id = agent_def.model.model_id
        elif provider == Provider.AZURE_OPENAI:
            sub_config.azure_openai.model_id = agent_def.model.model_id
        elif provider == Provider.OLLAMA:
            sub_config.ollama.model_id = agent_def.model.model_id
        sub_config.provider = provider
        # Disable reasoning for sub-agents
        sub_config.reasoning.mode = "off"
        return create_model(sub_config)

    # Inherit parent model — disable reasoning
    from hooty.config import AppConfig as _AC2

    parent_copy = _AC2(
        provider=config.provider,
        working_directory=config.working_directory,
        bedrock=config.bedrock,
        anthropic=config.anthropic,
        azure=config.azure,
        azure_openai=config.azure_openai,
        ollama=config.ollama,
        provider_env=config.provider_env,
        cache_system_prompt=config.cache_system_prompt,
        api_connect_timeout=config.api_connect_timeout,
        api_streaming_read_timeout=config.api_streaming_read_timeout,
        api_read_timeout=config.api_read_timeout,
    )
    parent_copy.reasoning.mode = "off"
    return create_model(parent_copy)


def _create_sub_agent_tools(
    agent_def: AgentDef,
    config: AppConfig,
    confirm_ref: list[bool] | None = None,
) -> list:
    """Build tools for the sub-agent.

    Inherits parent tools minus NEVER_INHERIT and disallowed_tools.
    """
    disallowed = set(agent_def.disallowed_tools) | NEVER_INHERIT

    tools = []

    # CodingTools — always available, but filter disallowed methods
    _build_coding_tools(config, disallowed, confirm_ref, tools)

    # PowerShellTools — available if PowerShell is installed (Windows or Linux with pwsh)
    if "run_powershell" not in disallowed:
        try:
            from hooty.tools.powershell_tools import create_powershell_tools

            ps_tools = create_powershell_tools(
                config.working_directory,
                confirm_ref=confirm_ref,
                extra_commands=config.allowed_commands,
                shell_timeout=config.shell_timeout,
                idle_timeout=config.idle_timeout,
            )
            if ps_tools:
                tools.append(ps_tools)
        except Exception:
            pass

    # Web search
    if "web_search" not in disallowed and config.web_search:
        try:
            from hooty.tools.search_tools import create_search_tools
            search_tools = create_search_tools()
            if search_tools:
                tools.append(search_tools)
        except Exception:
            pass

    # Web fetch — always available (lightweight URL fetching)
    if "web_fetch" not in disallowed:
        try:
            from hooty.tools.search_tools import create_web_fetch_tools
            web_fetch_tools = create_web_fetch_tools()
            if web_fetch_tools:
                tools.append(web_fetch_tools)
        except Exception:
            pass

    # GitHub
    if "github_create_issue" not in disallowed and config.github_enabled:
        import os
        if os.environ.get("GITHUB_ACCESS_TOKEN"):
            try:
                from hooty.tools.github_tools import create_github_tools
                github_tools = create_github_tools()
                if github_tools:
                    tools.append(github_tools)
            except Exception:
                pass

    # TODO: MCP/SQL — future extension as dedicated sub-agents
    # Rather than inheriting MCP/SQL tools into arbitrary sub-agents,
    # these should be realized as dedicated agents in agents.yaml:
    #   - sql_expert: DB connection + query tools
    #   - browser_expert: Playwright MCP for web operations
    # Each dedicated agent owns its MCP server/DB lifecycle internally.

    return tools


def _build_coding_tools(
    config: AppConfig,
    disallowed: set[str],
    confirm_ref: list[bool] | None,
    tools: list,
) -> None:
    """Build CodingTools for the sub-agent with disallowed methods filtered."""
    from hooty.tools.coding_tools import create_coding_tools

    # All write-capable methods that can be selectively blocked
    _WRITE_METHODS = ("write_file", "edit_file", "run_shell", "apply_patch", "move_file", "create_directory")
    # Core write methods — when ALL of these are blocked, use PlanModeCodingTools (read-only)
    _CORE_WRITE_METHODS = frozenset(("write_file", "edit_file", "run_shell"))

    coding_blocked = frozenset(t for t in _WRITE_METHODS if t in disallowed)
    all_blocked = _CORE_WRITE_METHODS <= coding_blocked

    coding = create_coding_tools(
        config.working_directory,
        confirm_ref=confirm_ref if not all_blocked else None,
        plan_mode=all_blocked,
        blocked_tools=coding_blocked if not all_blocked and coding_blocked else None,
        extra_commands=config.allowed_commands,
        shell_timeout=config.shell_timeout,
        idle_timeout=config.idle_timeout,
        add_dirs=config.add_dirs,
        ignore_dirs=config.ignore_dirs,
    )
    tools.append(coding)


def _build_additional_context(config: AppConfig) -> str | None:
    """Build additional context for the sub-agent (inherits global/project instructions)."""
    from hooty.context import load_context

    additional_context, _ = load_context(
        config_dir=config.config_dir,
        project_root=Path(config.working_directory),
    )
    return additional_context


async def _close_agent_model(agent: Any) -> None:
    """Close the sub-agent model's HTTP clients before the event loop shuts down.

    asyncio.run() closes the loop after the coroutine finishes.  If the
    model's async HTTP client is still open, its __del__ method tries to
    schedule cleanup on the (now-closed) loop, producing
    "RuntimeError: Event loop is closed".  Closing explicitly avoids this.

    The Agno model object lazily creates ``async_client`` (an
    ``anthropic.AsyncAnthropic`` instance).  That client wraps an
    ``httpx.AsyncClient`` whose ``__del__`` triggers the error.  We close
    both layers here and clear the reference so ``__del__`` becomes a no-op.
    """
    import contextlib

    model = getattr(agent, "model", None)
    if model is None:
        return

    # The lazily-created async client (e.g. anthropic.AsyncAnthropic)
    async_client = getattr(model, "async_client", None)
    if async_client is None:
        return

    # Close the outer async client (AsyncAnthropic.close() is a coroutine)
    # This internally closes the httpx async client as well.
    with contextlib.suppress(Exception):
        if hasattr(async_client, "close"):
            await async_client.close()

    # Clear the reference so __del__ won't try to clean up again
    with contextlib.suppress(Exception):
        model.async_client = None


def _fire_hook(event_name: str, **data: Any) -> None:
    """Best-effort hook firing using shared refs from confirm.py."""
    from hooty.tools.confirm import _hooks_ref

    hooks_config, session_id, cwd, loop = _hooks_ref
    if not hooks_config or not session_id:
        return
    try:
        from hooty.hooks import HookEvent, emit_hook_sync

        emit_hook_sync(
            HookEvent(event_name), hooks_config,
            session_id, cwd or "",
            loop=loop,
            **data,
        )
    except Exception:
        logger.debug("Hook %s failed for sub-agent", event_name, exc_info=True)


async def _arun_sub_agent(
    agent_def: AgentDef,
    task: str,
    config: AppConfig,
    confirm_ref: list[bool] | None = None,
    on_event: Callable[..., None] | None = None,
) -> str:
    """Create and run an ephemeral sub-agent. Returns the result text."""
    from agno.agent import Agent
    from agno.run.agent import RunEvent

    model = _create_sub_agent_model(agent_def, config)
    tools = _create_sub_agent_tools(agent_def, config, confirm_ref)
    additional_context = _build_additional_context(config)

    instructions = [
        agent_def.instructions,
        "You are a sub-agent executing autonomously. Do NOT ask the user questions.",
        "Complete the task thoroughly and return a clear, structured result.",
        f"Primary working directory: {config.working_directory}",
    ]

    session_state = {"working_directory": config.working_directory}

    # Enable tool result compression for write-capable agents (e.g. implement)
    # to prevent context overflow during edit-test-fix cycles
    has_write_tools = not (
        {"write_file", "edit_file", "run_shell"} <= set(agent_def.disallowed_tools)
    )
    compression_kwargs: dict[str, Any] = {}
    if has_write_tools:
        from agno.compression.manager import CompressionManager
        from hooty.model_catalog import get_context_limit

        ctx_limit = get_context_limit(config)
        compression_kwargs = {
            "compress_tool_results": True,
            "compression_manager": CompressionManager(
                compress_token_limit=int(ctx_limit * 0.5),
            ),
        }

    agent = Agent(
        name=f"sub-{agent_def.name}",
        model=model,
        telemetry=config.agno.telemetry,
        tools=tools,
        instructions=instructions,
        use_instruction_tags=True,
        additional_context=additional_context,
        markdown=True,
        session_state=session_state,
        **compression_kwargs,
    )

    if on_event:
        on_event("start", agent_def.name, task)

    # Hook: SubagentStart
    _fire_hook("SubagentStart", agent_name=agent_def.name, task=task)

    # Capture SDK retry/throttle logs and surface them to the UI via
    # on_event so the user sees "Retrying in X seconds" instead of a
    # silent multi-minute wait.  Covers both Anthropic SDK (direct API)
    # and botocore (AWS Bedrock).
    _retry_handlers: list[tuple[logging.Logger, logging.Handler]] = []
    if on_event:
        class _RetryLogHandler(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    on_event("retry", agent_def.name, record.getMessage())
                except Exception:
                    pass

        _rh = _RetryLogHandler(level=logging.DEBUG)

        # Anthropic SDK retries (direct API / Azure AI Foundry)
        _anthropic_logger = logging.getLogger("anthropic._base_client")
        _anthropic_logger.addHandler(_rh)
        _retry_handlers.append((_anthropic_logger, _rh))

        # botocore retries (AWS Bedrock) — logged at DEBUG level
        _botocore_logger = logging.getLogger("botocore.retryhandler")
        _botocore_logger.addHandler(_rh)
        _retry_handlers.append((_botocore_logger, _rh))

    start_time = time.monotonic()
    tool_call_count = 0
    input_tokens = 0
    output_tokens = 0
    result_text = ""
    error_msg = ""

    try:
        async for event in agent.arun(
            task,
            stream=True,
            stream_events=True,
            max_turns=agent_def.max_turns,
        ):
            # Check cancellation between events
            if cancel_event.is_set():
                logger.debug("Sub-agent '%s' cancelled by SIGINT", agent_def.name)
                break

            event_type = getattr(event, "event", None)

            if event_type == RunEvent.tool_call_started.value:
                tool = getattr(event, "tool", None)
                if tool and on_event:
                    tool_name = getattr(tool, "tool_name", None) or "tool"
                    tool_args = getattr(tool, "tool_args", None) or {}
                    hint = _tool_hint(tool_name, tool_args, config.working_directory)
                    on_event("tool_call", agent_def.name, tool_name, hint)
                tool_call_count += 1

            elif event_type == RunEvent.run_completed.value:
                run_metrics = getattr(event, "metrics", None)
                if run_metrics:
                    input_tokens += getattr(run_metrics, "input_tokens", 0) or 0
                    output_tokens += getattr(run_metrics, "output_tokens", 0) or 0

            elif event_type == RunEvent.run_content.value:
                content = getattr(event, "content", None)
                if content and isinstance(content, str):
                    result_text += content

    except Exception as e:
        logger.warning("Sub-agent '%s' error: %s", agent_def.name, e)
        error_msg = str(e)
        result_text = f"Error: Sub-agent '{agent_def.name}' failed: {e}"

    elapsed = time.monotonic() - start_time

    # Remove retry log handlers to avoid leaking handlers
    for _logger, _handler in _retry_handlers:
        _logger.removeHandler(_handler)

    if on_event:
        on_event("complete", agent_def.name, str(tool_call_count))

    # Truncate to max_output_tokens (character count)
    if len(result_text) > agent_def.max_output_tokens:
        result_text = result_text[:agent_def.max_output_tokens] + "\n\n[truncated]"

    # Clean up the sub-agent model's async clients before the event loop
    # closes.  Without this, asyncio.run() shuts down the loop and the
    # model's HTTP client destructor raises "Event loop is closed".
    await _close_agent_model(agent)

    # Hook: SubagentEnd
    _fire_hook(
        "SubagentEnd",
        agent_name=agent_def.name,
        task=task,
        tool_call_count=tool_call_count,
        result_length=len(result_text),
        elapsed=round(elapsed, 2),
        error=error_msg,
    )

    # Record sub-agent stats in SessionStats
    from hooty.tools.sub_agent_tools import _session_stats_ref
    from hooty.session_stats import SubAgentRunStats

    ss = _session_stats_ref[0]
    if ss is not None:
        ss.add_sub_agent_run(SubAgentRunStats(
            agent_name=agent_def.name,
            elapsed=round(elapsed, 2),
            tool_calls=tool_call_count,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            error=bool(error_msg),
        ))

    return result_text


def run_sub_agent(
    agent_def: AgentDef,
    task: str,
    config: AppConfig,
    confirm_ref: list[bool] | None = None,
    on_event: Callable[..., None] | None = None,
) -> str:
    """Synchronous wrapper — runs the sub-agent in a separate thread.

    Called from within the main agent's tool execution (which runs inside
    an existing event loop), so we use ThreadPoolExecutor like hooks.py.
    """
    coro = _arun_sub_agent(agent_def, task, config, confirm_ref, on_event)

    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        pass

    if loop is not None and loop.is_running():
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = pool.submit(asyncio.run, coro)
        try:
            # Poll with short timeouts so we can detect cancel_event
            # (on Windows, KeyboardInterrupt is suppressed by the
            # console-ctrl handler to protect the ProactorEventLoop,
            # so we must check cancel_event explicitly).
            deadline = time.monotonic() + 600  # 10 minute max
            while True:
                try:
                    return future.result(timeout=1.0)
                except concurrent.futures.TimeoutError:
                    if cancel_event.is_set():
                        # Give the sub-agent thread a short window to wind down
                        try:
                            return future.result(timeout=5)
                        except Exception:
                            return f"Error: Sub-agent '{agent_def.name}' cancelled by user"
                    if time.monotonic() >= deadline:
                        cancel_event.set()
                        try:
                            future.result(timeout=5)
                        except Exception:
                            pass
                        raise concurrent.futures.TimeoutError()
        except KeyboardInterrupt:
            cancel_event.set()
            try:
                future.result(timeout=5)
            except Exception:
                pass
            raise
        finally:
            pool.shutdown(wait=False)

    return asyncio.run(coro)
