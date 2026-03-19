"""Non-interactive (oneshot) mode — run a single prompt and exit."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from hooty.config import AppConfig

logger = logging.getLogger("hooty")


def _model_id(config: AppConfig) -> str:
    """Return the current model ID from config."""
    if config.provider.value == "anthropic":
        return config.anthropic.model_id
    if config.provider.value == "bedrock":
        return config.bedrock.model_id
    if config.provider.value == "azure":
        return config.azure.model_id
    if config.provider.value == "azure_openai":
        return config.azure_openai.model_id
    return ""


def _load_hooks(config: AppConfig) -> dict:
    """Load hooks config if enabled."""
    if not config.hooks_enabled:
        return {}
    from hooty.hooks import apply_disabled_state, load_hooks_config

    hooks_config = load_hooks_config(config)
    apply_disabled_state(hooks_config, config)
    return hooks_config


def oneshot_run(config: AppConfig, prompt: str, *, attach_files: list[str] | None = None) -> None:
    """Execute a single prompt in non-interactive mode.

    - stdout: LLM response content (plain Markdown)
    - stderr: metadata (model, tokens, elapsed time), errors
    - Exit code: 0=success, 1=LLM error, 2=config error
    """
    from hooty.tools.confirm import _non_interactive

    _non_interactive[0] = True
    config.non_interactive = True

    # --unsafe: disable confirmation dialogs
    confirm_ref: list[bool] = [not config.unsafe]

    from hooty.agent_factory import create_agent

    try:
        agent = create_agent(config, confirm_ref=confirm_ref)
    except Exception as e:
        print(f"Error creating agent: {e}", file=sys.stderr)
        sys.exit(2)

    # Assign a session ID for memory/logging
    if not config.session_id:
        import uuid

        config.session_id = str(uuid.uuid4())

    session_id = config.session_id
    cwd = config.working_directory

    # Process --attach files (after session_id is set so session_dir is available)
    images = None
    if attach_files:
        images, prompt = _process_attach_files(config, attach_files, prompt)

    # Load hooks config
    hooks_config = _load_hooks(config)

    # Hook: SessionStart
    _fire_hook_sync(hooks_config, "SessionStart", session_id, cwd,
                    provider=config.provider.value,
                    model_id=_model_id(config),
                    plan_mode=False, is_resume=False, non_interactive=True)

    # Run the agent
    start_time = time.monotonic()
    try:
        result = asyncio.run(_run(agent, prompt, session_id, images=images))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        _fire_hook_sync(hooks_config, "SessionEnd", session_id, cwd)
        sys.exit(1)
    except Exception as e:
        _fire_hook_sync(hooks_config, "ResponseError", session_id, cwd,
                        error=str(e), message=prompt)
        print(f"Error: {e}", file=sys.stderr)
        _fire_hook_sync(hooks_config, "SessionEnd", session_id, cwd)
        sys.exit(1)

    elapsed = time.monotonic() - start_time

    # Output content to stdout
    from agno.run.agent import RunOutput

    content = ""
    input_tokens = 0
    output_tokens = 0
    if isinstance(result, RunOutput) and result.content:
        content = str(result.content)
    if isinstance(result, RunOutput) and result.metrics:
        input_tokens = result.metrics.input_tokens or 0
        output_tokens = result.metrics.output_tokens or 0

    if content:
        sys.stdout.write(content)
        # Ensure trailing newline
        if not content.endswith("\n"):
            sys.stdout.write("\n")

    # Hook: Stop
    _fire_hook_sync(hooks_config, "Stop", session_id, cwd,
                    response=content, elapsed=elapsed,
                    input_tokens=input_tokens, output_tokens=output_tokens,
                    model_id=_model_id(config))

    # Metadata to stderr
    _print_meta(result, elapsed, config)

    # Log conversation
    _log_conversation(config, prompt, content)

    # Hook: SessionEnd
    _fire_hook_sync(hooks_config, "SessionEnd", session_id, cwd)


def _process_attach_files(
    config: AppConfig, attach_files: list[str], prompt: str,
) -> tuple[list | None, str]:
    """Process --attach files and return (images, updated_prompt)."""
    from pathlib import Path

    from hooty.attachment import AttachmentStack
    from hooty.model_catalog import get_context_limit

    stack = AttachmentStack()

    # Use tempfile for non-interactive mode — avoids creating orphan session dirs
    import tempfile
    attachments_dir = Path(tempfile.mkdtemp(prefix="hooty-att-"))

    ctx_limit = get_context_limit(config)

    for file_path in attach_files:
        p = Path(file_path)
        if not p.is_absolute():
            p = Path(config.working_directory) / p

        result = stack.add(
            p,
            config=config,
            attachments_dir=attachments_dir,
            context_limit=ctx_limit,
        )
        if isinstance(result, str):
            print(f"attach: {result}", file=sys.stderr)

    if stack.count == 0:
        return None, prompt

    images, text_block = stack.flush()
    if text_block:
        prompt = prompt + "\n\n" + text_block

    # Clean up temp dir after flush (image bytes are already in memory)
    import shutil
    shutil.rmtree(attachments_dir, ignore_errors=True)

    return images, prompt


def _fire_hook_sync(hooks_config: dict, event_name: str,
                    session_id: str, cwd: str, **data: object) -> None:
    """Best-effort synchronous hook firing."""
    if not hooks_config:
        return
    try:
        from hooty.hooks import HookEvent, emit_hook_sync

        emit_hook_sync(HookEvent(event_name), hooks_config, session_id, cwd, **data)
    except Exception:
        logger.debug("Hook %s failed", event_name, exc_info=True)


async def _run(agent: object, prompt: str, session_id: str, *, images=None) -> object:
    """Run the agent asynchronously."""
    return await agent.arun(  # type: ignore[union-attr]
        prompt,
        images=images,
        stream=False,
        session_id=session_id,
    )


def _print_meta(result: object, elapsed: float, config: AppConfig) -> None:
    """Print metadata to stderr."""
    from hooty.session_stats import format_duration

    parts = [config.active_profile or config.provider.value]
    parts.append(format_duration(elapsed))

    from agno.run.agent import RunOutput

    if isinstance(result, RunOutput) and result.metrics:
        m = result.metrics
        if m.input_tokens:
            parts.append(f"in:{m.input_tokens:,}")
        if m.output_tokens:
            parts.append(f"out:{m.output_tokens:,}")

    print(" | ".join(parts), file=sys.stderr)


def _log_conversation(config: AppConfig, prompt: str, content: str) -> None:
    """Best-effort conversation logging."""
    if not content:
        return
    try:
        from hooty.conversation_log import log_conversation

        log_conversation(
            project_dir=config.project_dir,
            session_id=config.session_id or "",
            model=_model_id(config),
            user_input=prompt,
            output=content,
        )
    except Exception:
        logger.debug("Failed to log conversation", exc_info=True)
