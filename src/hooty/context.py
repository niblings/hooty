"""Context management for Hooty.

Loads and merges global instructions (~/.hooty/hooty.md or instructions.md)
and project-specific instructions (AGENTS.md, CLAUDE.md, etc.)
into additional context for the Agno Agent.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hooty")

# Max file size: 64KB
MAX_FILE_SIZE = 64 * 1024

# Global instruction files in priority order
GLOBAL_INSTRUCTION_FILES = [
    "hooty.md",
    "instructions.md",
]

# Project instruction files in priority order
PROJECT_INSTRUCTION_FILES = [
    "AGENTS.md",
    "CLAUDE.md",
    ".github/copilot-instructions.md",
]


@dataclass
class ContextInfo:
    """Information about loaded context files."""

    global_path: Path | None = None
    global_size: int = 0
    global_lines: int = 0
    project_path: Path | None = None
    project_size: int = 0
    project_lines: int = 0


def _read_file_safe(path: Path) -> str | None:
    """Read a file with size and encoding validation.

    Returns file content or None if the file cannot be read.
    """
    if not path.is_file():
        return None

    size = path.stat().st_size
    if size > MAX_FILE_SIZE:
        logger.warning("Context file exceeds 64KB limit, skipping: %s", path)
        return None

    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        logger.warning("Context file is not valid UTF-8, skipping: %s", path)
        return None
    except OSError:
        logger.warning("Cannot read context file, skipping: %s", path)
        return None


def find_global_instructions(config_dir: Path) -> Path | None:
    """Search for a global instruction file and return its path.

    Searches for hooty.md and instructions.md in the config directory.
    If multiple exist, selects the largest file.
    If sizes are equal, selects by priority order.

    Returns None if no instruction file is found.
    """
    found: list[tuple[Path, int]] = []

    for filename in GLOBAL_INSTRUCTION_FILES:
        path = config_dir / filename
        if path.is_file():
            found.append((path, path.stat().st_size))

    if not found:
        return None

    if len(found) == 1:
        return found[0][0]

    # Multiple files: pick largest; ties broken by priority order (first in list)
    found.sort(key=lambda item: item[1], reverse=True)
    return found[0][0]


def find_project_instructions(project_root: Path) -> Path | None:
    """Search for a project instruction file and return its path.

    Searches for AGENTS.md, CLAUDE.md, .github/copilot-instructions.md
    in the project root. If multiple exist, selects the largest file.
    If sizes are equal, selects by priority order.

    Returns None if no instruction file is found.
    """
    found: list[tuple[Path, int]] = []

    for filename in PROJECT_INSTRUCTION_FILES:
        path = project_root / filename
        if path.is_file():
            found.append((path, path.stat().st_size))

    if not found:
        return None

    if len(found) == 1:
        return found[0][0]

    # Multiple files: pick largest; ties broken by priority order (first in list)
    found.sort(key=lambda item: item[1], reverse=True)
    return found[0][0]


def _content_hash(path: Path) -> str:
    """Return a short hex digest of a file's content.

    Content-based hashing is filesystem-agnostic — no reliance on mtime
    which can be unstable on WSL2/NTFS mounts.
    """
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest()


def context_fingerprint(
    config_dir: Path, project_root: Path,
) -> tuple[str | None, str | None]:
    """Return a content-based fingerprint of instruction files.

    Returns (global_hash, project_hash) where each is a hex digest
    or None if the file does not exist.
    """
    global_path = find_global_instructions(config_dir)
    global_hash: str | None = None
    if global_path:
        try:
            global_hash = _content_hash(global_path)
        except OSError:
            pass

    project_path = find_project_instructions(project_root)
    project_hash: str | None = None
    if project_path:
        try:
            project_hash = _content_hash(project_path)
        except OSError:
            pass

    return (global_hash, project_hash)


def load_context(
    config_dir: Path,
    project_root: Path,
) -> tuple[str | None, ContextInfo]:
    """Load and merge context from global and project instruction files.

    Returns a tuple of (merged context string or None, ContextInfo).
    """
    info = ContextInfo()
    sections: list[tuple[str, str]] = []

    # Global instructions
    global_path = find_global_instructions(config_dir)
    global_content = _read_file_safe(global_path) if global_path else None
    if global_content and global_content.strip():
        info.global_path = global_path
        info.global_size = global_path.stat().st_size
        info.global_lines = global_content.count("\n") + 1
        sections.append(("global_instructions", global_content.strip()))

    # Project instructions
    project_path = find_project_instructions(project_root)
    if project_path:
        project_content = _read_file_safe(project_path)
        if project_content and project_content.strip():
            info.project_path = project_path
            info.project_size = project_path.stat().st_size
            info.project_lines = project_content.count("\n") + 1
            sections.append(("project_instructions", project_content.strip()))

    if not sections:
        return None, info

    # Wrap each section in XML tags for clear LLM boundaries
    parts = []
    for tag, content in sections:
        parts.append(f"<{tag}>\n{content}\n</{tag}>")

    return "\n\n".join(parts), info
