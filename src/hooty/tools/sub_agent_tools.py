"""Sub-agent tools — run_agent() for delegating tasks to sub-agents."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Callable

from agno.tools import Toolkit

if TYPE_CHECKING:
    from hooty.agent_store import AgentDef
    from hooty.config import AppConfig

logger = logging.getLogger("hooty")

# Module-level event callback reference (set by REPL at startup)
# Pattern: confirm.py _active_live
_on_event: list[Callable[[str, str, str], None] | None] = [None]

# Module-level SessionStats reference (set by REPL at startup)
_session_stats_ref: list[Any] = [None]


class SubAgentTools(Toolkit):
    """Toolkit providing run_agent() to delegate tasks to sub-agents."""

    def __init__(
        self,
        agent_defs: dict[str, AgentDef],
        config: AppConfig,
        confirm_ref: list[bool] | None = None,
    ) -> None:
        super().__init__(name="sub_agent_tools")
        self.agent_defs = agent_defs
        self.config = config
        self.confirm_ref = confirm_ref

        # Build instructions listing available agents
        agent_list = []
        for name, adef in agent_defs.items():
            agent_list.append(f"- **{name}**: {adef.description}")
        agents_desc = "\n".join(agent_list)

        self.instructions = (
            "You can delegate tasks to specialized sub-agents using run_agent(). "
            "Sub-agents run in their own context window — only the final result "
            "is returned to you, keeping your context clean.\n\n"
            "Use sub-agents when:\n"
            "- A task requires reading many files (exploration, impact analysis)\n"
            "- You need a summary of code you haven't read yet\n"
            "- The investigation scope is broad and would clutter your context\n"
            "- Implementation involves edit-test-fix cycles across multiple files "
            "(use 'implement')\n"
            "- A coding task is likely to involve error retries that would "
            "consume your context\n"
            "- Tests are failing and need diagnosis + fix (use 'test-runner')\n"
            "- A task requires reading 2+ web pages or combining search + reading "
            "(use 'web-researcher') — NEVER call web_fetch/web_search multiple times "
            "yourself; delegate to web-researcher instead\n"
            "- The task is not code-related (writing, analysis, sysadmin, data processing) "
            "— use 'assistant'\n\n"
            "Do NOT use sub-agents for:\n"
            "- Simple single-file reads or greps (use your own tools)\n"
            "- Tasks that require conversation with the user\n"
            "- Quick lookups that would take one tool call\n"
            "- Trivial single-file edits with no verification needed\n\n"
            "Agent selection guide:\n"
            "- 'implement': You know WHAT to change — delegate the coding. "
            "Provide target files, changes, and a verification command.\n"
            "- 'test-runner': Tests are failing and you want them fixed. "
            "Provide the test command and optional scope (file/directory). "
            "The agent detects the framework, analyzes failures, fixes code, "
            "and re-runs until green.\n"
            "- 'explore': You need to understand code before acting.\n"
            "- 'summarize': You need compressed context from files.\n"
            "- 'web-researcher': ALWAYS use for any task that involves reading "
            "multiple web pages, comparing web sources, or researching a topic online. "
            "Web pages are large and will bloat your context — delegate to keep it clean. "
            "You may call web_fetch yourself ONLY for a single specific URL the user "
            "provided. For anything broader, use web-researcher.\n"
            "- 'assistant': For non-coding LOCAL tasks — document writing, data analysis, "
            "system administration, file organization. Does NOT do web research. "
            "If the task needs web search or reading URLs, use 'web-researcher' instead.\n\n"
            "Task decomposition:\n"
            "When a request spans multiple phases or agent types, split it into "
            "sequential calls. Run each sub-agent, review its result, then dispatch "
            "the next with adjusted context. "
            "Example chain: explore → implement → test-runner. "
            "Keep tightly coupled work in one call — only split when phases have "
            "distinct goals or need different agent capabilities.\n\n"
            f"Available agents:\n{agents_desc}"
        )

        self.register(self.run_agent)

    def _ensure_required_config(self, agent_def: AgentDef) -> str | None:
        """Check requires_config and prompt user if needed.

        Returns None if all config requirements are satisfied (or user approved).
        Returns an error message string if the user cancelled.
        """
        if not agent_def.requires_config:
            return None

        for config_key in agent_def.requires_config:
            if config_key == "web_search" and not self.config.web_search:
                approved = self._prompt_enable_web_search(agent_def.name)
                if not approved:
                    return f"Cancelled: '{agent_def.name}' requires web search, but it was not enabled."
                # Enable web_search on the config (persistent, same as /websearch toggle)
                self.config.web_search = True
                logger.debug("[sub-agent] enabled web_search for '%s'", agent_def.name)

        return None

    def _prompt_enable_web_search(self, agent_name: str) -> bool:
        """Show Y/N dialog to enable web search for a sub-agent."""
        from hooty.tools.confirm import _active_live, _confirm_lock, _non_interactive
        from hooty.ui import _active_console, hotkey_select

        # Non-interactive mode: deny
        if _non_interactive[0]:
            return False

        options = [
            ("Y", "Yes, enable /websearch"),
            ("N", "No, cancel"),
        ]

        with _confirm_lock:
            live = _active_live[0]
            if live:
                live.stop()
                from hooty.repl_ui import _erase_live_area
                lr = getattr(live, "_live_render", None)
                shape = getattr(lr, "_shape", None)
                height = shape[1] if shape else 1
                _erase_live_area(live.console.file, height)

            try:
                con = _active_console[0]
                if con is None:
                    from rich.console import Console
                    con = Console()

                key = hotkey_select(
                    options,
                    title=f"🌐 {agent_name} requires Web search",
                    border_style="cyan",
                    con=con,
                )

                from hooty.tools.confirm import _flush_win_input
                _flush_win_input()
            finally:
                if live:
                    live.start()

        from hooty.tools.confirm import _clear_win_cancel_state
        _clear_win_cancel_state()
        return key == "Y"

    def run_agent(self, agent_name: str, task: str) -> str:
        """Delegate a task to a named sub-agent.

        The sub-agent runs in its own context window with read-only or
        restricted tools. Only the final result text is returned.

        Args:
            agent_name: Name of the sub-agent to invoke (e.g. "explore", "summarize").
            task: A clear, specific description of what the sub-agent should investigate or do.

        Returns:
            The sub-agent's result text (structured report, summary, etc.).
        """
        agent_def = self.agent_defs.get(agent_name)
        if agent_def is None:
            available = ", ".join(sorted(self.agent_defs.keys()))
            return f"Error: Unknown agent '{agent_name}'. Available agents: {available}"

        # Check requires_config before execution
        cancel_msg = self._ensure_required_config(agent_def)
        if cancel_msg:
            return cancel_msg

        logger.debug(
            "[sub-agent] starting '%s': %s",
            agent_name, task[:100],
        )

        from hooty.tools.sub_agent_runner import run_sub_agent

        try:
            result = run_sub_agent(
                agent_def=agent_def,
                task=task,
                config=self.config,
                confirm_ref=self.confirm_ref,
                on_event=_on_event[0],
            )
        except Exception as e:
            logger.warning("[sub-agent] '%s' failed: %s", agent_name, e)
            return f"Error: Sub-agent '{agent_name}' failed: {e}"

        logger.debug(
            "[sub-agent] '%s' completed (%d chars)",
            agent_name, len(result),
        )
        return result
