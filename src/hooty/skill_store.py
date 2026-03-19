"""Skill state management — discovery, enable/disable persistence."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hooty.config import AppConfig

logger = logging.getLogger("hooty")


@dataclass
class SkillInfo:
    """Information about a discovered skill."""

    name: str
    description: str
    source: str  # "global" | "project (.claude)" | "project (.github)" | "project (.hooty)" | path
    source_path: str  # Full path to skill directory
    enabled: bool  # Not in disabled list
    disable_model_invocation: bool  # Frontmatter value
    user_invocable: bool  # Frontmatter value (default True)
    instructions: str  # SKILL.md body
    scripts: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Parse SKILL.md content into frontmatter dict and body."""
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if not match:
        return {}, content.strip()

    try:
        import yaml

        fm = yaml.safe_load(match.group(1)) or {}
    except Exception:
        fm = {}
    return fm, match.group(2).strip()


def _source_label(path: Path, config: AppConfig) -> str:
    """Derive a human-readable source label for a skill directory."""
    # Builtin check (before global)
    builtin_dir = Path(__file__).parent / "data" / "skills"
    try:
        path.relative_to(builtin_dir)
        return "builtin"
    except ValueError:
        pass

    global_dir = config.config_dir / "skills"
    try:
        path.relative_to(global_dir)
        return "global"
    except ValueError:
        pass

    project_root = Path(config.working_directory)
    for subdir, label in [
        (".claude/skills", "project (.claude)"),
        (".github/skills", "project (.github)"),
        (".hooty/skills", "project (.hooty)"),
    ]:
        try:
            path.relative_to(project_root / subdir)
            return label
        except ValueError:
            pass

    return str(path.parent)


def _discover_files(folder: Path, subdir: str) -> list[str]:
    """List non-hidden files in a subdirectory."""
    d = folder / subdir
    if not d.is_dir():
        return []
    return sorted(f.name for f in d.iterdir() if f.is_file() and not f.name.startswith("."))


def discover_skills(config: AppConfig) -> list[SkillInfo]:
    """Discover skills from global + project standard directories + extra_paths.

    Load order (last wins for same-name skills):
    ~/.hooty/skills/ → extra_paths → .github/skills/ → .claude/skills/ → .hooty/skills/

    Returns all discovered skills with enabled/disabled state applied.
    """
    disabled = load_disabled_skills(config)
    all_extra = get_all_extra_paths(config)
    seen: dict[str, SkillInfo] = {}

    # Directories in priority order (last wins)
    search_dirs: list[Path] = []

    # 0. Builtin skills (lowest priority — first in list, last wins)
    search_dirs.append(Path(__file__).parent / "data" / "skills")

    # 1. Global skills
    search_dirs.append(config.config_dir / "skills")

    # 2. Extra paths (global + per-project, merged)
    for p in all_extra:
        search_dirs.append(Path(p))

    # 3. Project skills (ascending priority)
    project_root = Path(config.working_directory)
    search_dirs.append(project_root / ".github" / "skills")
    search_dirs.append(project_root / ".claude" / "skills")
    search_dirs.append(project_root / ".hooty" / "skills")

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            logger.debug("[skills] scan skip (not found): %s", search_dir)
            continue
        logger.debug("[skills] scan: %s", search_dir)
        for item in sorted(search_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            skill_md = item / "SKILL.md"
            if not skill_md.exists():
                logger.debug("[skills]   skip (no SKILL.md): %s", item.name)
                continue
            try:
                content = skill_md.read_text(encoding="utf-8")
            except OSError:
                logger.debug("[skills]   skip (read error): %s", item.name)
                continue

            fm, instructions = _parse_frontmatter(content)
            name = fm.get("name", item.name)
            description = fm.get("description", "")
            disable_model = bool(fm.get("disable-model-invocation", False))
            user_invocable = bool(fm.get("user-invocable", True))

            overwrite = name in seen
            info = SkillInfo(
                name=name,
                description=description,
                source=_source_label(item, config),
                source_path=str(item),
                enabled=name not in disabled,
                disable_model_invocation=disable_model,
                user_invocable=user_invocable,
                instructions=instructions,
                scripts=_discover_files(item, "scripts"),
                references=_discover_files(item, "references"),
            )
            seen[name] = info  # Last wins
            flags = []
            if disable_model:
                flags.append("manual-only")
            if not user_invocable:
                flags.append("auto-only")
            if not info.enabled:
                flags.append("disabled")
            if overwrite:
                flags.append("overwrite")
            flag_str = f" [{', '.join(flags)}]" if flags else ""
            logger.debug("[skills]   found: %s (%s)%s", name, info.source, flag_str)

    return list(seen.values())


def _load_skills_state(config: AppConfig) -> dict:
    """Load the full .skills.json state."""
    path = config.skills_state_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_skills_state(config: AppConfig, state: dict) -> None:
    """Save the full .skills.json state."""
    from hooty.concurrency import atomic_write_text

    config.project_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config.skills_state_path, json.dumps(state, indent=2) + "\n")


def load_disabled_skills(config: AppConfig) -> set[str]:
    """Load disabled skill names from project .skills.json."""
    state = _load_skills_state(config)
    return set(state.get("disabled", []))


def save_disabled_skills(config: AppConfig, disabled: set[str]) -> None:
    """Save disabled skill names to project .skills.json (preserves other keys)."""
    state = _load_skills_state(config)
    state["disabled"] = sorted(disabled)
    _save_skills_state(config, state)


def load_extra_paths(config: AppConfig) -> list[str]:
    """Load extra skill paths from project .skills.json."""
    state = _load_skills_state(config)
    paths = state.get("extra_paths", [])
    return paths if isinstance(paths, list) else []


def save_extra_paths(config: AppConfig, paths: list[str]) -> None:
    """Save extra skill paths to project .skills.json (preserves other keys)."""
    state = _load_skills_state(config)
    state["extra_paths"] = paths
    _save_skills_state(config, state)


def _load_global_skills_state(config: AppConfig) -> dict:
    """Load the full global .skills.json state."""
    path = config.global_skills_state_path
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_global_skills_state(config: AppConfig, state: dict) -> None:
    """Save the full global .skills.json state."""
    from hooty.concurrency import atomic_write_text

    config.config_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(config.global_skills_state_path, json.dumps(state, indent=2) + "\n")


def load_global_extra_paths(config: AppConfig) -> list[str]:
    """Load extra skill paths from global .skills.json."""
    state = _load_global_skills_state(config)
    paths = state.get("extra_paths", [])
    return paths if isinstance(paths, list) else []


def save_global_extra_paths(config: AppConfig, paths: list[str]) -> None:
    """Save extra skill paths to global .skills.json (preserves other keys)."""
    state = _load_global_skills_state(config)
    state["extra_paths"] = paths
    _save_global_skills_state(config, state)


def get_all_extra_paths(config: AppConfig) -> list[str]:
    """Merge global + project extra_paths (deduplicated, order preserved)."""
    seen: set[str] = set()
    result: list[str] = []
    for p in load_global_extra_paths(config) + load_extra_paths(config):
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _skill_search_dirs(config: AppConfig) -> list[Path]:
    """Return skill search directories in priority order (same as discover_skills)."""
    dirs: list[Path] = []
    dirs.append(Path(__file__).parent / "data" / "skills")
    dirs.append(config.config_dir / "skills")
    for p in get_all_extra_paths(config):
        dirs.append(Path(p))
    project_root = Path(config.working_directory)
    dirs.append(project_root / ".github" / "skills")
    dirs.append(project_root / ".claude" / "skills")
    dirs.append(project_root / ".hooty" / "skills")
    return dirs


def skill_fingerprint(config: AppConfig) -> str:
    """Return a content-based fingerprint of all discoverable SKILL.md files.

    Scans the same directories as discover_skills() but only reads SKILL.md
    raw content (no frontmatter parsing, no scripts/references scan).
    Returns a hex digest that changes when any SKILL.md is added, removed,
    or modified.
    """
    h = hashlib.sha256()
    for search_dir in _skill_search_dirs(config):
        if not search_dir.is_dir():
            continue
        for item in sorted(search_dir.iterdir()):
            if not item.is_dir() or item.name.startswith("."):
                continue
            skill_md = item / "SKILL.md"
            try:
                data = skill_md.read_bytes()
            except OSError:
                continue
            # Include path to distinguish same-content skills in different dirs
            h.update(str(item).encode())
            h.update(data)
    return h.hexdigest()


def load_skill_instructions(skill: SkillInfo, args: str = "") -> str:
    """Load skill instructions and replace $ARGUMENTS placeholder.

    Used for manual invocation of disable-model-invocation skills.
    """
    instructions = skill.instructions
    if args:
        instructions = instructions.replace("$ARGUMENTS", args)
    logger.debug(
        "[skills] invoke: %s (args=%r, instructions=%d chars)",
        skill.name, args or "(none)", len(instructions),
    )
    return instructions
