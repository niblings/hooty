"""Session store for querying saved sessions."""

from __future__ import annotations

import re
import shutil
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from agno.db.base import SessionType
from agno.db.sqlite import SqliteDb

from hooty.config import AppConfig
from hooty.text_utils import truncate_display


@contextmanager
def _create_storage(config: AppConfig) -> Iterator[SqliteDb]:
    """Create a SqliteDb instance for session queries, ensuring proper cleanup."""
    from hooty.concurrency import create_wal_engine

    db = SqliteDb(
        session_table="agent_sessions",
        db_engine=create_wal_engine(config.session_db_path),
    )
    try:
        yield db
    finally:
        db.close()


def get_most_recent_session_id(config: AppConfig) -> Optional[str]:
    """Find the most recently updated session ID."""
    with _create_storage(config) as storage:
        result = storage.get_sessions(
            session_type=SessionType.AGENT,
            sort_by="updated_at",
            sort_order="desc",
            limit=1,
            deserialize=False,
        )
        sessions, _total = result
        if sessions:
            return sessions[0]["session_id"]
        return None


def list_sessions(
    config: AppConfig, limit: int = 20
) -> tuple[list[dict[str, Any]], int]:
    """List sessions sorted by most recently updated.

    Returns (sessions_list, total_count).
    """
    with _create_storage(config) as storage:
        return storage.get_sessions(
            session_type=SessionType.AGENT,
            sort_by="updated_at",
            sort_order="desc",
            limit=limit,
            deserialize=False,
        )


def session_exists(config: AppConfig, session_id: str) -> bool:
    """Check if a session with the given ID exists."""
    with _create_storage(config) as storage:
        session = storage.get_session(
            session_id=session_id,
            session_type=SessionType.AGENT,
            deserialize=False,
        )
        return session is not None


def format_session_for_display(session_raw: dict[str, Any]) -> dict[str, str]:
    """Extract display-friendly fields from a raw session dict."""
    session_id = session_raw.get("session_id", "")
    short_id = session_id[:8]

    # Format timestamp
    updated_at = session_raw.get("updated_at") or session_raw.get("created_at")
    if updated_at:
        dt = datetime.fromtimestamp(updated_at, tz=timezone.utc).astimezone()
        date_str = dt.strftime("%Y-%m-%d %H:%M")
    else:
        date_str = "unknown"

    # Extract first user message as preview
    runs = session_raw.get("runs") or []
    run_count = len(runs)
    preview = ""
    if runs:
        first_run = runs[0]
        # Try input.input_content from RunInput
        run_input = first_run.get("input")
        if isinstance(run_input, dict):
            content = run_input.get("input_content", "")
            if isinstance(content, str):
                preview = content
        # Fallback: scan messages for first user message
        if not preview:
            messages = first_run.get("messages") or []
            for msg in messages:
                if isinstance(msg, dict) and msg.get("role") == "user":
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        preview = content
                        break

    # Strip hook context injected by UserPromptSubmit hook
    preview = re.sub(r"\s*<hook_context>[\s\S]*?</hook_context>\s*", "", preview)
    # Collapse whitespace to single line
    preview = " ".join(preview.split())

    preview = truncate_display(preview, 50, " …")

    # Extract project info from session_state
    project = "\u2014"
    wd = ""
    session_data = session_raw.get("session_data") or {}
    session_state = session_data.get("session_state") if isinstance(session_data, dict) else None
    if isinstance(session_state, dict):
        wd = session_state.get("working_directory", "")
        if wd:
            from pathlib import PurePosixPath, PureWindowsPath

            # Handle both POSIX and Windows paths
            try:
                project = PurePosixPath(wd).name or PureWindowsPath(wd).name or "\u2014"
            except (TypeError, ValueError):
                project = "\u2014"

    # Detect fork origin
    metadata = session_raw.get("metadata") or {}
    forked_from = metadata.get("forked_from", "") if isinstance(metadata, dict) else ""

    return {
        "short_id": short_id,
        "session_id": session_id,
        "updated_at": date_str,
        "preview": preview,
        "run_count": str(run_count),
        "project": project,
        "forked_from": forked_from,
        "working_directory": wd,
    }


def find_purgeable_sessions(
    config: AppConfig,
    days: int = 90,
    exclude_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return sessions whose updated_at is older than *days* days.

    Sessions in *exclude_ids* (e.g. current session, locked sessions) are
    never included.
    """
    cutoff = time.time() - days * 86400
    exclude = exclude_ids or set()

    with _create_storage(config) as storage:
        sessions, _total = storage.get_sessions(
            session_type=SessionType.AGENT,
            sort_by="updated_at",
            sort_order="asc",
            limit=10000,
            deserialize=False,
        )

    purgeable: list[dict[str, Any]] = []
    for s in sessions:
        sid = s.get("session_id", "")
        if sid in exclude:
            continue
        updated = s.get("updated_at") or s.get("created_at") or 0
        if updated < cutoff:
            purgeable.append(s)

    return purgeable


def purge_sessions(config: AppConfig, session_ids: list[str]) -> int:
    """Delete DB records and session directories for the given IDs.

    Returns the number of sessions actually removed from the DB.
    """
    if not session_ids:
        return 0

    with _create_storage(config) as storage:
        removed = 0
        sessions_base = config.config_dir / "sessions"
        for sid in session_ids:
            try:
                storage.delete_session(session_id=sid)
                removed += 1
            except Exception:
                pass
            # Remove session directory if it exists
            session_dir = sessions_base / sid
            if session_dir.exists():
                shutil.rmtree(session_dir, ignore_errors=True)

        return removed


def cleanup_orphan_dirs(config: AppConfig) -> int:
    """Remove session directories that have no matching DB record.

    Returns the number of orphan directories removed.
    """
    sessions_base = config.config_dir / "sessions"
    if not sessions_base.exists():
        return 0

    with _create_storage(config) as storage:
        removed = 0

        for entry in sessions_base.iterdir():
            if not entry.is_dir():
                continue
            session_id = entry.name
            session = storage.get_session(
                session_id=session_id,
                session_type=SessionType.AGENT,
                deserialize=False,
            )
            if session is None:
                shutil.rmtree(entry, ignore_errors=True)
                removed += 1

        return removed
