"""Workspace binding — ties a session directory to a working directory."""

from __future__ import annotations

import os
from pathlib import Path


def save_workspace(session_dir: Path, working_directory: str) -> None:
    """Write workspace.yaml with the current working directory."""
    import yaml

    data = {"working_directory": working_directory}
    from hooty.concurrency import atomic_write_text

    ws_path = session_dir / "workspace.yaml"
    atomic_write_text(ws_path, yaml.dump(data, default_flow_style=False))


def load_workspace(session_dir: Path) -> str | None:
    """Read workspace.yaml and return the stored working_directory, or None."""
    import yaml

    ws_path = session_dir / "workspace.yaml"
    if not ws_path.exists():
        return None
    try:
        data = yaml.safe_load(ws_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("working_directory")
    except Exception:
        pass
    return None


def check_workspace_mismatch(session_dir: Path, current_wd: str) -> str | None:
    """Compare stored working directory against *current_wd*.

    Returns the stored path if they differ, or None if they match (or no file).
    Path comparison uses normcase+normpath for Windows/Linux compatibility.
    """
    stored = load_workspace(session_dir)
    if stored is None:
        return None
    norm_stored = os.path.normcase(os.path.normpath(stored))
    norm_current = os.path.normcase(os.path.normpath(current_wd))
    if norm_stored != norm_current:
        return stored
    return None
