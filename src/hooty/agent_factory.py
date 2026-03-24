"""Agent assembly for Hooty."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from hooty.context import load_context
from hooty.model_catalog import get_context_limit
from hooty.prompt_store import load_prompts, resolve_instructions

from hooty.config import AppConfig

logger = logging.getLogger("hooty")

if TYPE_CHECKING:
    from agno.agent import Agent

_prompts = load_prompts()


def create_agent(
    config: AppConfig,
    *,
    plan_mode: bool = False,
    confirm_ref: list[bool] | None = None,
    auto_execute_ref: list[bool] | None = None,
    pending_plan_ref: list[str | None] | None = None,
    enter_plan_ref: list[bool] | None = None,
    pending_reason_ref: list[str | None] | None = None,
    pending_revise_ref: list[bool] | None = None,
    session_id_ref: list[str] | None = None,
    pending_plan_id_ref: list[str | None] | None = None,
    # Reusable components — skip expensive rebuild when provided
    reuse_storage: object | None = None,
    reuse_tools: list | None = None,
    reuse_skills: object | None = None,
) -> Agent:
    """Create and configure the Hooty agent."""
    from agno.agent import Agent
    from agno.compression.manager import CompressionManager
    from agno.db.sqlite import SqliteDb

    from hooty.providers import create_model
    from hooty.tools import build_tools

    model = create_model(config)

    # Session storage
    if reuse_storage is not None:
        storage = reuse_storage
    else:
        from hooty.concurrency import create_wal_engine

        storage = SqliteDb(
            session_table="agent_sessions",
            db_engine=create_wal_engine(config.session_db_path),
        )

    # Tools
    tools = reuse_tools if reuse_tools is not None else build_tools(
        config,
        plan_mode=plan_mode,
        confirm_ref=confirm_ref,
        auto_execute_ref=auto_execute_ref,
        pending_plan_ref=pending_plan_ref,
        enter_plan_ref=enter_plan_ref,
        pending_reason_ref=pending_reason_ref,
        pending_revise_ref=pending_revise_ref,
        session_id_ref=session_id_ref,
        pending_plan_id_ref=pending_plan_id_ref,
    )

    # Compression threshold — percentage of context window at which to
    # trigger tool-result compression.
    #
    # For Claude (Bedrock): tiktoken counts are corrected by 1.2x in
    # providers.py, so 70% threshold ≒ 84% of actual context usage.
    # For other models: tiktoken is accurate, 50% gives safe margin.
    context_limit = get_context_limit(config)
    compress_ratio = 0.7
    compress_token_limit = int(context_limit * compress_ratio)

    # Mode-specific role & instructions (from prompts.yaml)
    mode_key = "planning" if plan_mode else "coding"
    mode_prompts = _prompts.modes[mode_key]

    if plan_mode:
        role = config.roles.planning or mode_prompts.role
    else:
        role = config.roles.coding or mode_prompts.role

    instructions = resolve_instructions(
        mode_prompts.instructions, flags={}, template_vars={},
    )

    # Working directory information
    dir_info = f"Primary working directory: {config.working_directory}"
    if config.add_dirs:
        dir_info += "\nAdditional working directories (read+write allowed):"
        for d in config.add_dirs:
            dir_info += f"\n- {d}"
    dir_info += (
        "\nAll file operations (read, write, edit, grep, find, ls)"
        " are restricted to the directories listed above."
        " Paths outside these directories will be rejected."
        " Focus your work within the working directory."
    )
    instructions.append(dir_info)

    # Non-interactive mode instruction
    if config.non_interactive:
        instructions.append(
            "Non-interactive mode: ask_user() is unavailable. "
            "Make reasonable decisions autonomously without asking the user."
        )

    # Memory policy instruction (appended to both planning and coding)
    if config.memory_enabled:
        instructions.append(_prompts.memory_policy)

    # Past context reference (history + plans)
    hist_dir = config.project_history_dir
    plans_dir = config.project_plans_dir
    ref_parts = []
    if hist_dir.exists():
        ref_parts.append(
            f"- Conversation logs: {hist_dir}/*.jsonl (one file per session, "
            "each line has 'input' and 'output' fields)"
        )
    if plans_dir.exists() and any(plans_dir.iterdir()):
        ref_parts.append(
            f"- Plans: {plans_dir}/*.md (Markdown with YAML frontmatter)"
        )
    if ref_parts:
        instructions.append(
            "Past project artifacts are available for reference:\n"
            + "\n".join(ref_parts) + "\n"
            "IMPORTANT: NEVER access these paths on your own initiative. "
            "Only when the user EXPLICITLY asks to recall or search previous conversations or plans, "
            "use plans_list() / plans_get() / plans_search() for plan access, "
            "and read_file() / grep() for conversation logs. Do NOT use run_shell for this."
        )

    # Additional context from user instruction files
    additional_context, _ = load_context(
        config_dir=config.config_dir,
        project_root=Path(config.working_directory),
    )

    # Memory manager
    memory_manager = None
    if config.memory_enabled:
        from agno.memory.manager import MemoryManager

        # Ensure project directory exists
        config.project_dir.mkdir(parents=True, exist_ok=True)

        # Write .meta.json for orphan detection
        from hooty.project_store import ensure_project_meta

        ensure_project_meta(config.project_dir, config.working_directory)

        from hooty.concurrency import create_wal_engine

        project_memory_db = SqliteDb(
            memory_table="user_memories",
            db_engine=create_wal_engine(config.project_memory_db_path),
        )
        memory_manager = MemoryManager(
            db=project_memory_db,
            model=model,
        )

        # Inject global memories as read-only additional context
        global_context = _build_global_memory_context(config)
        if global_context:
            if additional_context:
                additional_context = additional_context + "\n\n" + global_context
            else:
                additional_context = global_context

    # Agent Skills (progressive discovery)
    if reuse_skills is not None:
        agno_skills = reuse_skills
    elif config.skills.enabled:
        agno_skills = _build_skills(config)
    else:
        agno_skills = None

    # Session state — store working directory for project association
    session_state = {"working_directory": config.working_directory}

    from hooty.hooks import _agno_pre_tool_hook

    return Agent(
        name="hooty",
        model=model,
        role=role,
        telemetry=config.agno.telemetry,
        tool_hooks=[_agno_pre_tool_hook],
        db=storage,
        tools=tools,
        skills=agno_skills,
        instructions=instructions,
        use_instruction_tags=True,
        additional_context=additional_context,
        add_history_to_context=True,
        num_history_runs=3,
        add_session_summary_to_context=True,
        markdown=True,
        # Memory
        memory_manager=memory_manager,
        enable_agentic_memory=config.memory_enabled,
        update_memory_on_run=False,
        add_memories_to_context=config.memory_enabled,
        # Session state
        session_state=session_state,
        # Tool result compression — large tool outputs (file reads, shell output)
        compress_tool_results=True,
        compression_manager=CompressionManager(
            compress_token_limit=compress_token_limit,
        ),
    )


def _build_skills(config: AppConfig):
    """Build Agno Skills from discovered skill directories.

    Returns a Skills object or None if no skills are available.
    """
    import time

    from agno.skills import LocalSkills, Skills

    from hooty.skill_store import load_disabled_skills, get_all_extra_paths

    t_start = time.perf_counter()
    loaders = []

    # Load order determines priority (last wins for same-name skills):
    # builtin → global → extra_paths → .github → .claude → .hooty

    # 0. Builtin skills (lowest priority — first in list)
    builtin_dir = Path(__file__).parent / "data" / "skills"
    if builtin_dir.is_dir():
        loaders.append(LocalSkills(str(builtin_dir), validate=False))
        logger.debug("[skills] loader: %s (builtin)", builtin_dir)

    # 1. Global skills
    global_dir = config.config_dir / "skills"
    if global_dir.is_dir():
        loaders.append(LocalSkills(str(global_dir), validate=False))
        logger.debug("[skills] loader: %s", global_dir)

    # 2. Extra paths (global + per-project, merged)
    for p in get_all_extra_paths(config):
        path = Path(p)
        if path.is_dir():
            loaders.append(LocalSkills(str(path), validate=False))
            logger.debug("[skills] loader: %s (extra)", path)

    # 3. Project skills (ascending priority: .github → .claude → .hooty)
    project_root = Path(config.working_directory)
    for subdir in [".github/skills", ".claude/skills", ".hooty/skills"]:
        d = project_root / subdir
        if d.is_dir():
            loaders.append(LocalSkills(str(d), validate=False))
            logger.debug("[skills] loader: %s", d)

    if not loaders:
        logger.debug("[skills] no skill directories found")
        return None

    try:
        skills = Skills(loaders=loaders)
    except Exception as e:
        logger.debug("[skills] failed to load: %s", e)
        return None

    loaded_names = list(skills._skills.keys())
    logger.debug("[skills] loaded %d skill(s): %s", len(loaded_names), loaded_names)

    # Filter out disabled skills (per-project state)
    disabled = load_disabled_skills(config)
    for name in list(skills._skills.keys()):
        if name in disabled:
            del skills._skills[name]
            logger.debug("[skills] filtered (disabled): %s", name)

    # Filter out disable-model-invocation skills (manual-only)
    for name, skill in list(skills._skills.items()):
        meta = skill.metadata or {}
        if meta.get("disable-model-invocation"):
            del skills._skills[name]
            logger.debug("[skills] filtered (manual-only): %s", name)

    elapsed = (time.perf_counter() - t_start) * 1000
    remaining = list(skills._skills.keys())
    logger.debug("[skills] ready: %d skill(s) in %.1fms: %s", len(remaining), elapsed, remaining)

    return skills if skills._skills else None


def _build_global_memory_context(config: AppConfig) -> str | None:
    """Load global memories and format as XML context block."""
    import os

    if not os.path.exists(config.global_memory_db_path):
        return None

    try:
        from hooty.memory_store import list_memories

        memories = list_memories(config.global_memory_db_path)
    except Exception:
        return None

    if not memories:
        return None

    lines = []
    for m in memories:
        mid = (m.memory_id or "")[:8]
        lines.append(f"ID: m-{mid}")
        lines.append(f"Memory: {m.memory}")
        lines.append("")

    content = "\n".join(lines).rstrip()
    return f"<global_memories>\n{content}\n</global_memories>"
