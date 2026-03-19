"""Project directory store for Hooty.

Manages project directory metadata (.meta.json) and orphan detection.
"""

from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

from hooty.config import AppConfig


@dataclass
class ProjectInfo:
    """Information about a project directory."""

    dir_name: str
    dir_path: Path
    working_directory: str | None
    created_at: int | None
    memory_count: int


def ensure_project_meta(project_dir: Path, working_directory: str) -> None:
    """Write .meta.json if it does not already exist (idempotent)."""
    meta_path = project_dir / ".meta.json"
    if meta_path.exists():
        return
    data = {
        "working_directory": working_directory,
        "created_at": int(time.time()),
    }
    from hooty.concurrency import atomic_write_text

    atomic_write_text(meta_path, json.dumps(data, indent=2))


def _read_meta(project_dir: Path) -> dict | None:
    """Read .meta.json from a project directory, or None if missing/invalid."""
    meta_path = project_dir / ".meta.json"
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _count_project_memories(project_dir: Path) -> int:
    """Count memories in a project's memory.db."""
    db_path = project_dir / "memory.db"
    if not db_path.exists():
        return 0
    try:
        from hooty.memory_store import count_memories

        return count_memories(str(db_path))
    except Exception:
        return 0


def list_projects(config: AppConfig) -> list[ProjectInfo]:
    """List all project directories."""
    projects_dir = config.config_dir / "projects"
    if not projects_dir.exists():
        return []

    result: list[ProjectInfo] = []
    for entry in sorted(projects_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta = _read_meta(entry)
        result.append(
            ProjectInfo(
                dir_name=entry.name,
                dir_path=entry,
                working_directory=meta.get("working_directory") if meta else None,
                created_at=meta.get("created_at") if meta else None,
                memory_count=_count_project_memories(entry),
            )
        )
    return result


def find_orphaned_projects(config: AppConfig) -> list[ProjectInfo]:
    """Find orphaned project directories.

    A project is orphaned if:
    - .meta.json exists but working_directory path does not exist
    - .meta.json is missing (unknown status)

    Projects with a valid working_directory are excluded.
    """
    all_projects = list_projects(config)
    orphaned: list[ProjectInfo] = []
    for p in all_projects:
        if p.working_directory is None:
            # No metadata — unknown status
            orphaned.append(p)
        elif not os.path.exists(p.working_directory):
            # Path no longer exists — orphaned
            orphaned.append(p)
        # else: valid project, skip
    return orphaned


def purge_projects(project_dirs: list[Path]) -> int:
    """Delete project directories. Returns the number removed."""
    removed = 0
    for d in project_dirs:
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            removed += 1
    return removed


def format_project_for_display(project: ProjectInfo) -> dict[str, str]:
    """Format a ProjectInfo for display in the picker."""
    if project.working_directory is None:
        status = "(metadata missing)"
        path_display = ""
    elif not os.path.exists(project.working_directory):
        status = "(not found)"
        path_display = project.working_directory
    else:
        status = ""
        path_display = project.working_directory

    mem_str = f"{project.memory_count} mem." if project.memory_count > 0 else ""

    return {
        "dir_name": project.dir_name,
        "path_display": path_display,
        "status": status,
        "memory_count": mem_str,
    }
