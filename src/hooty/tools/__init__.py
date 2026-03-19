"""Tool assembly for Hooty agent."""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

from hooty.tools.coding_tools import create_coding_tools

if TYPE_CHECKING:
    from agno.tools import Toolkit

    from hooty.config import AppConfig


def build_tools(
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
) -> list[Toolkit]:
    """Build the list of tools based on configuration."""
    tools: list[Toolkit] = []
    tmp_dir = str(config.session_tmp_dir) if config.session_tmp_dir else None
    session_dir = str(config.session_dir) if config.session_dir else None
    project_dir = str(config.project_dir)

    # Always enabled
    tools.append(
        create_coding_tools(
            config.working_directory,
            confirm_ref=confirm_ref,
            plan_mode=plan_mode,
            auto_execute_ref=auto_execute_ref,
            extra_commands=config.allowed_commands,
            shell_timeout=config.shell_timeout,
            idle_timeout=config.idle_timeout,
            tmp_dir=tmp_dir,
            session_dir=session_dir,
            project_dir=project_dir,
            add_dirs=config.add_dirs,
            ignore_dirs=config.ignore_dirs,
            snapshot_enabled=config.snapshot_enabled,
            shell_operators=config.shell_operators,
        )
    )

    # Ask user — always available (both modes, regardless of safe mode)
    from hooty.tools.ask_user_tools import AskUserTools

    tools.append(AskUserTools())

    # PowerShell tools - Windows only
    if sys.platform == "win32":
        from hooty.tools.powershell_tools import create_powershell_tools

        ps_tools = create_powershell_tools(
            config.working_directory,
            confirm_ref=confirm_ref,
            plan_mode=plan_mode,
            auto_execute_ref=auto_execute_ref,
            extra_commands=config.allowed_commands,
            shell_timeout=config.shell_timeout,
            idle_timeout=config.idle_timeout,
            tmp_dir=tmp_dir,
            session_dir=session_dir,
        )
        if ps_tools:
            tools.append(ps_tools)

    # Plan mode: exit_plan_mode to switch to coding
    if plan_mode:
        if auto_execute_ref is not None and pending_plan_ref is not None:
            from hooty.tools.exit_plan_mode_tools import ExitPlanModeTools

            tools.append(ExitPlanModeTools(
                auto_execute_ref=auto_execute_ref,
                pending_plan_ref=pending_plan_ref,
                pending_plan_id_ref=pending_plan_id_ref,
            ))

    # Plan CRUD — always available (both modes)
    if session_id_ref is not None:
        from hooty.tools.plan_tools import PlanTools

        tools.append(PlanTools(config=config, session_id_ref=session_id_ref))

    # Coding mode: enter_plan_mode to switch to planning
    if not plan_mode:
        if (enter_plan_ref is not None
                and pending_reason_ref is not None
                and pending_revise_ref is not None):
            from hooty.tools.enter_plan_mode_tools import EnterPlanModeTools

            tools.append(EnterPlanModeTools(
                enter_plan_ref=enter_plan_ref,
                pending_reason_ref=pending_reason_ref,
                pending_revise_ref=pending_revise_ref,
            ))

    # GitHub - enabled via /github toggle (requires GITHUB_ACCESS_TOKEN)
    if config.github_enabled and os.environ.get("GITHUB_ACCESS_TOKEN"):
        from hooty.tools.github_tools import create_github_tools

        github_tools = create_github_tools()
        if github_tools:
            tools.append(github_tools)

    # Web fetch — always enabled (lightweight URL fetching)
    from hooty.tools.search_tools import create_web_fetch_tools

    web_fetch_tools = create_web_fetch_tools()
    if web_fetch_tools:
        tools.append(web_fetch_tools)

    # Web search (DuckDuckGo) — enabled via /websearch toggle
    if config.web_search:
        from hooty.tools.search_tools import create_search_tools

        search_tools = create_search_tools(region=config.web_search_region)
        if search_tools:
            tools.append(search_tools)

    # SQL Database - enabled when active_db is configured
    if config.active_db:
        db_url = config.databases.get(config.active_db)
        if db_url:
            from hooty.tools.sql_tools import SQLToolsError, create_sql_tools

            try:
                sql_tools = create_sql_tools(db_url)
                if sql_tools:
                    tools.append(sql_tools)
            except SQLToolsError:
                pass  # error is handled by REPL's _cmd_database_connect

    # MCP - enabled when mcp config exists
    # Warnings are stashed on config so they can be displayed after the spinner
    config._mcp_warnings = []  # type: ignore[attr-defined]
    if config.mcp:
        from hooty.tools.mcp_tools import create_mcp_tools

        mcp_tools, config._mcp_warnings = create_mcp_tools(  # type: ignore[attr-defined]
            config.mcp, mcp_debug=config.mcp_debug,
        )
        tools.extend(mcp_tools)

    # Sub-agents (always enabled — core feature)
    from hooty.agent_store import load_agents_config

    agents_config = load_agents_config(config)
    if agents_config:
        from hooty.tools.sub_agent_tools import SubAgentTools

        tools.append(SubAgentTools(agents_config, config, confirm_ref))

    return tools
