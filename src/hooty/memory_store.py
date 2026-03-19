"""Memory store operations for Hooty.

Provides CRUD helpers over Agno's SqliteDb user-memory table.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from agno.db.schemas.memory import UserMemory

from hooty.text_utils import truncate_display
from agno.db.sqlite import SqliteDb

logger = logging.getLogger("hooty")


@contextmanager
def _create_memory_db(db_path: str) -> Iterator[SqliteDb]:
    """Create a SqliteDb instance for user memories, ensuring proper cleanup."""
    from hooty.concurrency import create_wal_engine

    db = SqliteDb(
        memory_table="user_memories",
        db_engine=create_wal_engine(db_path),
    )
    try:
        yield db
    finally:
        db.close()


def list_memories(db_path: str) -> list[UserMemory]:
    """Return all user memories from the given database."""
    with _create_memory_db(db_path) as db:
        return db.get_user_memories(sort_by="updated_at", sort_order="desc")


def search_memories(db_path: str, keyword: str) -> list[UserMemory]:
    """Search memories by keyword in memory text and topics."""
    with _create_memory_db(db_path) as db:
        kw_lower = keyword.lower()

        # Fetch all memories once and search in Python to handle non-ASCII
        # text reliably (SQLite LIKE/ilike may fail with CJK characters).
        all_memories: list[UserMemory] = db.get_user_memories(
            sort_by="updated_at",
            sort_order="desc",
        )

        merged: list[UserMemory] = []
        for m in all_memories:
            # Match memory text
            if m.memory and kw_lower in m.memory.lower():
                merged.append(m)
                continue
            # Match topics
            if m.topics:
                for topic in m.topics:
                    if kw_lower in topic.lower():
                        merged.append(m)
                        break

        return merged


def delete_memories(db_path: str, memory_ids: list[str]) -> int:
    """Delete memories by their IDs. Returns the count of IDs requested."""
    if not memory_ids:
        return 0
    with _create_memory_db(db_path) as db:
        db.delete_user_memories(memory_ids)
        return len(memory_ids)


def format_memory_for_display(memory: UserMemory) -> dict[str, str]:
    """Format a UserMemory record for display."""
    short_id = (memory.memory_id or "")[:8]
    if short_id:
        short_id = f"m-{short_id[:6]}"

    topics = ", ".join(memory.topics) if memory.topics else ""

    memory_text = memory.memory or ""
    memory_text = truncate_display(memory_text, 50)

    # Format timestamp
    ts = memory.updated_at or memory.created_at
    if ts:
        dt = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        updated_str = _relative_time(dt)
    else:
        updated_str = "unknown"

    return {
        "short_id": short_id,
        "memory_id": memory.memory_id or "",
        "topics": topics,
        "memory_text": memory_text,
        "full_memory_text": memory.memory or "",
        "updated_at": updated_str,
    }


def move_memories(
    src_db_path: str, dst_db_path: str, memory_ids: list[str],
) -> int:
    """Move memories from src to dst database. Returns count moved."""
    if not memory_ids:
        return 0

    with _create_memory_db(src_db_path) as src_db, _create_memory_db(dst_db_path) as dst_db:
        moved = 0

        for mid in memory_ids:
            mem = src_db.get_user_memory(memory_id=mid)
            if mem is None:
                continue
            try:
                dst_db.upsert_user_memory(mem)
            except Exception:
                logger.warning("Failed to upsert memory %s to destination, skipping", mid)
                continue
            try:
                src_db.delete_user_memory(mid)
            except Exception:
                # Worst case: duplicate exists in both DBs (safe, not data loss)
                logger.warning("Memory %s copied but not removed from source", mid)
            moved += 1

        return moved


def count_memories(db_path: str) -> int:
    """Count the number of memories in the database."""
    with _create_memory_db(db_path) as db:
        memories = db.get_user_memories()
        return len(memories)


def get_last_updated(db_path: str) -> datetime | None:
    """Return the most recent updated_at timestamp."""
    with _create_memory_db(db_path) as db:
        memories = db.get_user_memories(
            sort_by="updated_at",
            sort_order="desc",
            limit=1,
        )
        if not memories:
            return None
        ts = memories[0].updated_at or memories[0].created_at
        if ts:
            return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone()
        return None


def _relative_time(dt: datetime) -> str:
    """Format a datetime as a human-readable relative time string."""
    now = datetime.now(tz=timezone.utc).astimezone()
    diff = now - dt
    seconds = int(diff.total_seconds())

    if seconds < 60:
        return "just now"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} min ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''} ago"
    return dt.strftime("%Y-%m-%d")
