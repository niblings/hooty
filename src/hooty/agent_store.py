"""Sub-agent definition store — discovery, loading, and merge logic."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("hooty")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

# Tool names that are NEVER inherited by sub-agents (hardcoded)
NEVER_INHERIT: frozenset[str] = frozenset({
    "exit_plan_mode",
    "enter_plan_mode",
    "run_agent",
    "ask_user",
    "think",
    "analyze",
})

# Tool names that agents.yaml may reference in disallowed_tools
ALLOWED_TOOL_NAMES: set[str] = {
    "read_file", "grep", "find", "ls",
    "write_file", "edit_file",
    "apply_patch", "move_file", "create_directory",
    "run_shell", "run_powershell",
    "web_search", "web_fetch",
    "github_create_issue", "github_get_issue", "github_list_issues",
    "github_create_pr", "github_get_pr", "github_list_prs",
    "sql_query", "sql_describe",
}


@dataclass
class AgentModelConfig:
    """Optional model override for a sub-agent."""

    provider: str = ""   # "bedrock" | "anthropic" | "azure" | "azure_openai"
    model_id: str = ""


@dataclass
class AgentDef:
    """A single sub-agent definition."""

    name: str
    description: str
    instructions: str
    disallowed_tools: list[str] = field(default_factory=list)
    model: AgentModelConfig | None = None
    max_turns: int = 25
    max_output_tokens: int = 4000
    source: str = ""  # "builtin" | "global" | "project"
    requires_config: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def _builtin_yaml_path() -> Path:
    """Return the path to the built-in agents.yaml bundled with the package."""
    return Path(__file__).parent / "data" / "agents.yaml"


def _load_yaml(path: Path) -> dict[str, dict]:
    """Parse a single YAML file and return the ``agents`` section.

    Returns ``{agent_name: raw_dict}`` or empty dict on failure.
    """
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception:
        logger.warning("Failed to load agents from %s", path)
        return {}

    if not isinstance(data, dict):
        return {}
    agents_section = data.get("agents")
    if not isinstance(agents_section, dict):
        return {}
    return agents_section


def _parse_agent_def(name: str, raw: dict[str, Any], source: str) -> AgentDef | None:
    """Parse a raw dict into an AgentDef. Returns None if invalid."""
    description = raw.get("description")
    instructions = raw.get("instructions")
    if not description or not isinstance(description, str):
        logger.warning("Agent '%s' missing description in %s", name, source)
        return None
    if not instructions or not isinstance(instructions, str):
        logger.warning("Agent '%s' missing instructions in %s", name, source)
        return None

    disallowed = raw.get("disallowed_tools", [])
    if not isinstance(disallowed, list):
        disallowed = []
    disallowed = [str(t) for t in disallowed]

    model_config = None
    model_raw = raw.get("model")
    if isinstance(model_raw, dict) and "provider" in model_raw and "model_id" in model_raw:
        model_config = AgentModelConfig(
            provider=str(model_raw["provider"]),
            model_id=str(model_raw["model_id"]),
        )

    max_turns = int(raw.get("max_turns", 25))
    max_output_tokens = int(raw.get("max_output_tokens", 4000))

    requires_config = raw.get("requires_config", [])
    if not isinstance(requires_config, list):
        requires_config = []
    requires_config = [str(c) for c in requires_config]

    return AgentDef(
        name=name,
        description=description,
        instructions=instructions,
        disallowed_tools=disallowed,
        model=model_config,
        max_turns=max_turns,
        max_output_tokens=max_output_tokens,
        source=source,
        requires_config=requires_config,
    )


def load_agents_config(config: Any) -> dict[str, AgentDef]:
    """Load and merge agent definitions: builtin < global < project.

    Returns ``{agent_name: AgentDef}`` with later sources overriding earlier ones.
    """
    from hooty.config import AppConfig

    if not isinstance(config, AppConfig):
        return {}

    result: dict[str, AgentDef] = {}

    # 1. Builtin (source="builtin")
    builtin_path = _builtin_yaml_path()
    for name, raw in _load_yaml(builtin_path).items():
        if not isinstance(raw, dict):
            continue
        agent_def = _parse_agent_def(name, raw, "builtin")
        if agent_def:
            result[name] = agent_def
            logger.debug("[agents] loaded builtin: %s", name)

    # 2. Global (~/.hooty/agents.yaml, source="global")
    global_path = config.config_dir / "agents.yaml"
    for name, raw in _load_yaml(global_path).items():
        if not isinstance(raw, dict):
            continue
        agent_def = _parse_agent_def(name, raw, "global")
        if agent_def:
            overwrite = name in result
            result[name] = agent_def
            flag = " (overwrite)" if overwrite else ""
            logger.debug("[agents] loaded global: %s%s", name, flag)

    # 3. Project (.hooty/agents.yaml, source="project")
    project_path = Path(config.working_directory) / ".hooty" / "agents.yaml"
    for name, raw in _load_yaml(project_path).items():
        if not isinstance(raw, dict):
            continue
        agent_def = _parse_agent_def(name, raw, "project")
        if agent_def:
            overwrite = name in result
            result[name] = agent_def
            flag = " (overwrite)" if overwrite else ""
            logger.debug("[agents] loaded project: %s%s", name, flag)

    logger.debug("[agents] total: %d agent(s): %s", len(result), list(result.keys()))
    return result
