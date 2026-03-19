"""Tests for Hooty project store operations."""

import json
import time
from pathlib import Path

from agno.db.schemas.memory import UserMemory
from agno.db.sqlite import SqliteDb

from hooty.project_store import (
    ProjectInfo,
    ensure_project_meta,
    find_orphaned_projects,
    format_project_for_display,
    list_projects,
    purge_projects,
)


def _make_config(tmp_path: Path):
    """Create a minimal AppConfig with config_dir pointing to tmp_path."""
    from hooty.config import AppConfig

    config = AppConfig()
    # Override config_dir via a subclass to use tmp_path
    config.__class__ = type(
        "_TestConfig",
        (AppConfig,),
        {"config_dir": property(lambda self: tmp_path)},
    )
    return config


def _seed_project(
    projects_dir: Path,
    dir_name: str,
    *,
    working_directory: str | None = None,
    write_meta: bool = True,
    memory_count: int = 0,
) -> Path:
    """Create a project directory with optional .meta.json and memories."""
    project_dir = projects_dir / dir_name
    project_dir.mkdir(parents=True, exist_ok=True)

    if write_meta and working_directory is not None:
        meta = {
            "working_directory": working_directory,
            "created_at": int(time.time()),
        }
        (project_dir / ".meta.json").write_text(json.dumps(meta))

    if memory_count > 0:
        db = SqliteDb(
            memory_table="user_memories",
            db_file=str(project_dir / "memory.db"),
        )
        now = int(time.time())
        for i in range(memory_count):
            db.upsert_user_memory(
                UserMemory(
                    memory=f"Memory {i}",
                    memory_id=f"mem-{dir_name}-{i:03d}",
                    created_at=now,
                )
            )

    return project_dir


class TestEnsureProjectMeta:
    """Test .meta.json creation."""

    def test_creates_meta_file(self, tmp_path):
        project_dir = tmp_path / "myapp-a3f1b2c4"
        project_dir.mkdir()
        ensure_project_meta(project_dir, "/tmp/projects/myapp")

        meta_path = project_dir / ".meta.json"
        assert meta_path.exists()
        data = json.loads(meta_path.read_text())
        assert data["working_directory"] == "/tmp/projects/myapp"
        assert "created_at" in data

    def test_idempotent(self, tmp_path):
        project_dir = tmp_path / "myapp-a3f1b2c4"
        project_dir.mkdir()

        ensure_project_meta(project_dir, "/tmp/projects/myapp")
        first_content = (project_dir / ".meta.json").read_text()

        # Call again — should not overwrite
        ensure_project_meta(project_dir, "/tmp/other")
        second_content = (project_dir / ".meta.json").read_text()

        assert first_content == second_content
        data = json.loads(second_content)
        assert data["working_directory"] == "/tmp/projects/myapp"

    def test_content_format(self, tmp_path):
        project_dir = tmp_path / "test-12345678"
        project_dir.mkdir()
        ensure_project_meta(project_dir, "/home/user/test")

        data = json.loads((project_dir / ".meta.json").read_text())
        assert isinstance(data["working_directory"], str)
        assert isinstance(data["created_at"], int)
        assert data["created_at"] > 0


class TestListProjects:
    """Test listing all projects."""

    def test_empty_projects_dir(self, tmp_path):
        config = _make_config(tmp_path)
        assert list_projects(config) == []

    def test_no_projects_dir(self, tmp_path):
        config = _make_config(tmp_path)
        # projects/ does not exist
        assert list_projects(config) == []

    def test_with_meta(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"
        _seed_project(projects_dir, "myapp-a3f1b2c4", working_directory="/tmp/projects/myapp")

        result = list_projects(config)
        assert len(result) == 1
        assert result[0].dir_name == "myapp-a3f1b2c4"
        assert result[0].working_directory == "/tmp/projects/myapp"

    def test_without_meta(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"
        _seed_project(projects_dir, "old-00000000", write_meta=False)

        result = list_projects(config)
        assert len(result) == 1
        assert result[0].dir_name == "old-00000000"
        assert result[0].working_directory is None

    def test_with_memories(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"
        _seed_project(
            projects_dir, "myapp-a3f1b2c4",
            working_directory="/tmp/projects/myapp",
            memory_count=3,
        )

        result = list_projects(config)
        assert result[0].memory_count == 3


class TestFindOrphanedProjects:
    """Test orphan detection."""

    def test_path_not_found(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"
        # working_directory points to non-existent path
        _seed_project(
            projects_dir, "gone-a1b2c3d4",
            working_directory="/nonexistent/path/that/does/not/exist",
        )

        orphaned = find_orphaned_projects(config)
        assert len(orphaned) == 1
        assert orphaned[0].dir_name == "gone-a1b2c3d4"

    def test_metadata_missing(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"
        _seed_project(projects_dir, "unknown-00000000", write_meta=False)

        orphaned = find_orphaned_projects(config)
        assert len(orphaned) == 1
        assert orphaned[0].working_directory is None

    def test_valid_excluded(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"
        # Create a project pointing to tmp_path itself (which exists)
        _seed_project(
            projects_dir, "valid-12345678",
            working_directory=str(tmp_path),
        )

        orphaned = find_orphaned_projects(config)
        assert len(orphaned) == 0

    def test_mixed(self, tmp_path):
        config = _make_config(tmp_path)
        projects_dir = tmp_path / "projects"

        # Valid project (path exists)
        _seed_project(
            projects_dir, "alive-11111111",
            working_directory=str(tmp_path),
        )
        # Orphaned project (path not found)
        _seed_project(
            projects_dir, "gone-22222222",
            working_directory="/nonexistent/gone",
        )
        # Unknown project (no metadata)
        _seed_project(projects_dir, "unknown-33333333", write_meta=False)

        orphaned = find_orphaned_projects(config)
        assert len(orphaned) == 2
        names = {p.dir_name for p in orphaned}
        assert "gone-22222222" in names
        assert "unknown-33333333" in names
        assert "alive-11111111" not in names


class TestPurgeProjects:
    """Test project directory deletion."""

    def test_purge_removes_directories(self, tmp_path):
        d1 = tmp_path / "project1"
        d2 = tmp_path / "project2"
        d1.mkdir()
        d2.mkdir()
        (d1 / "memory.db").write_text("data")

        removed = purge_projects([d1, d2])
        assert removed == 2
        assert not d1.exists()
        assert not d2.exists()

    def test_purge_empty_list(self):
        removed = purge_projects([])
        assert removed == 0

    def test_purge_nonexistent_dir(self, tmp_path):
        nonexistent = tmp_path / "nonexistent"
        removed = purge_projects([nonexistent])
        assert removed == 0


class TestFormatProjectForDisplay:
    """Test display formatting."""

    def test_orphaned_project(self):
        info = ProjectInfo(
            dir_name="myapp-a3f1b2c4",
            dir_path=Path("/tmp/projects/myapp-a3f1b2c4"),
            working_directory="/nonexistent/path",
            created_at=int(time.time()),
            memory_count=5,
        )
        display = format_project_for_display(info)
        assert display["dir_name"] == "myapp-a3f1b2c4"
        assert display["status"] == "(not found)"
        assert display["path_display"] == "/nonexistent/path"
        assert "5 mem." in display["memory_count"]

    def test_metadata_missing(self):
        info = ProjectInfo(
            dir_name="old-00000000",
            dir_path=Path("/tmp/projects/old-00000000"),
            working_directory=None,
            created_at=None,
            memory_count=0,
        )
        display = format_project_for_display(info)
        assert display["status"] == "(metadata missing)"
        assert display["path_display"] == ""
        assert display["memory_count"] == ""
