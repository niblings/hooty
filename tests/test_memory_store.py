"""Tests for Hooty memory store operations."""

import time
from pathlib import Path

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import SqliteDb

from hooty.config import project_dir_name
from hooty.memory_store import (
    count_memories,
    delete_memories,
    format_memory_for_display,
    get_last_updated,
    list_memories,
    move_memories,
    search_memories,
)


def _seed_db(db_path: str, memories: list[UserMemory]) -> None:
    """Insert test memories into the database."""
    db = SqliteDb(memory_table="user_memories", db_file=db_path)
    for m in memories:
        db.upsert_user_memory(m)


class TestProjectDirName:
    """Test project directory name derivation."""

    def test_basic_derivation(self):
        name = project_dir_name(Path("/tmp/projects/myapp"))
        assert name.startswith("myapp-")
        assert len(name) == len("myapp-") + 8

    def test_different_paths_different_hashes(self):
        name1 = project_dir_name(Path("/tmp/projects/myapp"))
        name2 = project_dir_name(Path("/tmp/other/myapp"))
        # Same basename but different hash
        assert name1.startswith("myapp-")
        assert name2.startswith("myapp-")
        assert name1 != name2

    def test_same_path_same_hash(self):
        name1 = project_dir_name(Path("/tmp/projects/myapp"))
        name2 = project_dir_name(Path("/tmp/projects/myapp"))
        assert name1 == name2

    def test_deep_path(self):
        name = project_dir_name(Path("/home/user/projects/backend"))
        assert name.startswith("backend-")


class TestListMemoriesEmpty:
    """Test listing memories from empty database."""

    def test_empty_db(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        memories = list_memories(db_path)
        assert memories == []


class TestCountMemories:
    """Test memory counting."""

    def test_count_empty(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        assert count_memories(db_path) == 0

    def test_count_with_memories(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        now = int(time.time())
        _seed_db(db_path, [
            UserMemory(memory="Uses PostgreSQL", memory_id="mem-001", created_at=now),
            UserMemory(memory="Tests in __tests__/", memory_id="mem-002", created_at=now),
            UserMemory(memory="Use Conventional Commits", memory_id="mem-003", created_at=now),
        ])
        assert count_memories(db_path) == 3


class TestFormatMemoryForDisplay:
    """Test memory display formatting."""

    def test_basic_format(self):
        now = int(time.time())
        m = UserMemory(
            memory="Uses PostgreSQL + Prisma ORM",
            memory_id="a1b2c3d4e5f6g7h8",
            topics=["arch", "db"],
            created_at=now,
            updated_at=now,
        )
        info = format_memory_for_display(m)
        assert info["short_id"] == "m-a1b2c3"
        assert "arch" in info["topics"]
        assert "db" in info["topics"]
        assert "PostgreSQL" in info["memory_text"]
        assert info["updated_at"] == "just now"

    def test_long_memory_truncated(self):
        m = UserMemory(
            memory="A" * 100,
            memory_id="abc12345",
            created_at=int(time.time()),
        )
        info = format_memory_for_display(m)
        assert len(info["memory_text"]) <= 50
        assert info["memory_text"].endswith("...")

    def test_no_topics(self):
        m = UserMemory(
            memory="Simple memory",
            memory_id="def67890",
            created_at=int(time.time()),
        )
        info = format_memory_for_display(m)
        assert info["topics"] == ""

    def test_full_memory_text_preserved(self):
        long_text = "A" * 100
        m = UserMemory(
            memory=long_text,
            memory_id="xyz12345",
            created_at=int(time.time()),
        )
        info = format_memory_for_display(m)
        assert info["full_memory_text"] == long_text


class TestSearchMemories:
    """Test memory search functionality."""

    def test_search_by_text(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        now = int(time.time())
        _seed_db(db_path, [
            UserMemory(memory="Uses PostgreSQL for database", memory_id="mem-001", created_at=now),
            UserMemory(memory="Frontend uses React", memory_id="mem-002", created_at=now),
            UserMemory(memory="Deploy to Vercel", memory_id="mem-003", created_at=now),
        ])
        results = search_memories(db_path, "PostgreSQL")
        assert len(results) >= 1
        assert any("PostgreSQL" in m.memory for m in results)

    def test_search_by_topic(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        now = int(time.time())
        _seed_db(db_path, [
            UserMemory(
                memory="Uses JWT tokens",
                memory_id="mem-001",
                topics=["auth", "security"],
                created_at=now,
            ),
            UserMemory(
                memory="Frontend uses React",
                memory_id="mem-002",
                topics=["frontend"],
                created_at=now,
            ),
        ])
        results = search_memories(db_path, "auth")
        assert len(results) >= 1
        assert any("JWT" in m.memory for m in results)

    def test_search_no_results(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        now = int(time.time())
        _seed_db(db_path, [
            UserMemory(memory="Uses PostgreSQL", memory_id="mem-001", created_at=now),
        ])
        results = search_memories(db_path, "nonexistent-term")
        assert results == []


class TestDeleteMemories:
    """Test memory deletion."""

    def test_delete_specific(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        now = int(time.time())
        _seed_db(db_path, [
            UserMemory(memory="Memory A", memory_id="mem-001", created_at=now),
            UserMemory(memory="Memory B", memory_id="mem-002", created_at=now),
            UserMemory(memory="Memory C", memory_id="mem-003", created_at=now),
        ])
        deleted = delete_memories(db_path, ["mem-001", "mem-003"])
        assert deleted == 2
        remaining = list_memories(db_path)
        assert len(remaining) == 1
        assert remaining[0].memory_id == "mem-002"

    def test_delete_empty_list(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        assert delete_memories(db_path, []) == 0


class TestMoveMemories:
    """Test moving memories between databases."""

    def test_move_basic(self, tmp_path):
        src_path = str(tmp_path / "src.db")
        dst_path = str(tmp_path / "dst.db")
        now = int(time.time())
        _seed_db(src_path, [
            UserMemory(memory="Memory A", memory_id="mem-001", created_at=now),
            UserMemory(memory="Memory B", memory_id="mem-002", created_at=now),
            UserMemory(memory="Memory C", memory_id="mem-003", created_at=now),
        ])

        moved = move_memories(src_path, dst_path, ["mem-001", "mem-002", "mem-003"])
        assert moved == 3
        # Source should be empty
        assert count_memories(src_path) == 0
        # Destination should have all 3
        assert count_memories(dst_path) == 3

    def test_move_skips_missing(self, tmp_path):
        src_path = str(tmp_path / "src.db")
        dst_path = str(tmp_path / "dst.db")
        now = int(time.time())
        _seed_db(src_path, [
            UserMemory(memory="Memory A", memory_id="mem-001", created_at=now),
        ])

        moved = move_memories(src_path, dst_path, ["mem-001", "nonexistent"])
        assert moved == 1
        assert count_memories(dst_path) == 1

    def test_move_empty_list(self, tmp_path):
        src_path = str(tmp_path / "src.db")
        dst_path = str(tmp_path / "dst.db")
        assert move_memories(src_path, dst_path, []) == 0


class TestGetLastUpdated:
    """Test last updated timestamp retrieval."""

    def test_empty_db(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        assert get_last_updated(db_path) is None

    def test_with_memories(self, tmp_path):
        db_path = str(tmp_path / "memory.db")
        now = int(time.time())
        _seed_db(db_path, [
            UserMemory(memory="Old memory", memory_id="mem-001", created_at=now - 3600, updated_at=now - 3600),
            UserMemory(memory="New memory", memory_id="mem-002", created_at=now, updated_at=now),
        ])
        last = get_last_updated(db_path)
        assert last is not None
        assert abs(last.timestamp() - now) < 2
