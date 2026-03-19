"""Tests for coding tools — move_file, create_directory, apply_patch integration."""

from pathlib import Path

from hooty.tools.coding_tools import HootyCodingTools, PlanModeCodingTools


def _make_tools(tmp_path: Path) -> HootyCodingTools:
    """Create a minimal HootyCodingTools for testing."""
    return HootyCodingTools(
        base_dir=tmp_path,
        all=True,
        restrict_to_base_dir=True,
    )


class TestMoveFile:
    """Test move_file method."""

    def test_move_file_basic(self, tmp_path):
        (tmp_path / "a.txt").write_text("content")
        tools = _make_tools(tmp_path)
        result = tools.move_file("a.txt", "b.txt")
        assert "Moved" in result
        assert not (tmp_path / "a.txt").exists()
        assert (tmp_path / "b.txt").read_text() == "content"

    def test_move_file_to_subdirectory(self, tmp_path):
        (tmp_path / "file.txt").write_text("data")
        tools = _make_tools(tmp_path)
        result = tools.move_file("file.txt", "sub/dir/file.txt")
        assert "Moved" in result
        assert (tmp_path / "sub/dir/file.txt").read_text() == "data"

    def test_move_file_nonexistent_source(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.move_file("nope.txt", "dst.txt")
        assert "Error" in result

    def test_move_file_outside_base_dir(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        tools = _make_tools(tmp_path)
        result = tools.move_file("a.txt", "/tmp/escape.txt")
        assert "Error" in result

    def test_move_file_source_outside_base_dir(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.move_file("/etc/passwd", "stolen.txt")
        assert "Error" in result

    def test_move_directory(self, tmp_path):
        src = tmp_path / "src_dir"
        src.mkdir()
        (src / "a.txt").write_text("aaa")
        (src / "sub").mkdir()
        (src / "sub" / "b.txt").write_text("bbb")
        tools = _make_tools(tmp_path)
        result = tools.move_file("src_dir", "dst_dir")
        assert "Moved" in result
        assert not src.exists()
        assert (tmp_path / "dst_dir" / "a.txt").read_text() == "aaa"
        assert (tmp_path / "dst_dir" / "sub" / "b.txt").read_text() == "bbb"

    def test_move_directory_to_nested_destination(self, tmp_path):
        src = tmp_path / "mydir"
        src.mkdir()
        (src / "file.txt").write_text("content")
        tools = _make_tools(tmp_path)
        result = tools.move_file("mydir", "nested/path/mydir")
        assert "Moved" in result
        assert (tmp_path / "nested" / "path" / "mydir" / "file.txt").read_text() == "content"


class TestCreateDirectory:
    """Test create_directory method."""

    def test_create_directory_basic(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.create_directory("new_dir")
        assert "Created" in result
        assert (tmp_path / "new_dir").is_dir()

    def test_create_directory_nested(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.create_directory("a/b/c")
        assert "Created" in result
        assert (tmp_path / "a/b/c").is_dir()

    def test_create_directory_already_exists(self, tmp_path):
        (tmp_path / "existing").mkdir()
        tools = _make_tools(tmp_path)
        result = tools.create_directory("existing")
        assert "already exists" in result

    def test_create_directory_outside_base_dir(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.create_directory("/tmp/escape_dir")
        assert "Error" in result


class TestApplyPatchIntegration:
    """Test apply_patch method on HootyCodingTools."""

    def test_apply_patch_add_file(self, tmp_path):
        tools = _make_tools(tmp_path)
        patch = """\
*** Begin Patch
*** Add File: hello.py
+print("hello")
*** End Patch"""
        result = tools.apply_patch(patch)
        assert "Added" in result
        assert (tmp_path / "hello.py").exists()

    def test_apply_patch_path_outside_base(self, tmp_path):
        tools = _make_tools(tmp_path)
        patch = """\
*** Begin Patch
*** Add File: /etc/evil.py
+bad
*** End Patch"""
        result = tools.apply_patch(patch)
        assert "Error" in result

    def test_apply_patch_invalid_format(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.apply_patch("not a patch")
        assert "Error" in result


class TestToolRegistration:
    """Test that new tools are registered as LLM-callable functions."""

    def test_apply_patch_registered(self, tmp_path):
        tools = _make_tools(tmp_path)
        assert "apply_patch" in tools.functions

    def test_move_file_registered(self, tmp_path):
        tools = _make_tools(tmp_path)
        assert "move_file" in tools.functions

    def test_create_directory_registered(self, tmp_path):
        tools = _make_tools(tmp_path)
        assert "create_directory" in tools.functions

    def test_tree_registered(self, tmp_path):
        tools = _make_tools(tmp_path)
        assert "tree" in tools.functions

    def test_base_tools_still_registered(self, tmp_path):
        tools = _make_tools(tmp_path)
        for name in ("read_file", "write_file", "edit_file", "run_shell", "grep", "find", "ls"):
            assert name in tools.functions, f"{name} should be registered"


class TestPlanModeBlocking:
    """Test that PlanModeCodingTools blocks write operations."""

    def _make_plan_tools(self, tmp_path: Path) -> PlanModeCodingTools:
        return PlanModeCodingTools(
            base_dir=tmp_path,
            all=True,
            restrict_to_base_dir=True,
        )

    def test_apply_patch_blocked(self, tmp_path):
        tools = self._make_plan_tools(tmp_path)
        result = tools.apply_patch("patch text")
        assert "not available in planning mode" in result

    def test_move_file_blocked(self, tmp_path):
        tools = self._make_plan_tools(tmp_path)
        result = tools.move_file("a", "b")
        assert "not available in planning mode" in result

    def test_create_directory_allowed(self, tmp_path):
        """create_directory is non-destructive, allowed in plan mode."""
        tools = self._make_plan_tools(tmp_path)
        result = tools.create_directory("test_dir")
        assert "Created" in result


class TestTree:
    """Test tree method."""

    def test_tree_basic(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        (tmp_path / "a" / "b" / "c.txt").write_text("x")
        (tmp_path / "a" / "d.txt").write_text("x")
        (tmp_path / "e.txt").write_text("x")
        tools = _make_tools(tmp_path)
        result = tools.tree()
        assert "├── " in result or "└── " in result
        assert "a/" in result
        assert "b/" in result
        assert "c.txt" in result
        assert "d.txt" in result
        assert "e.txt" in result

    def test_tree_depth_limit(self, tmp_path):
        # Create depth=4 structure: a/b/c/d.txt
        d = tmp_path / "a" / "b" / "c"
        d.mkdir(parents=True)
        (d / "d.txt").write_text("x")
        tools = _make_tools(tmp_path)
        # depth=2 should show a/ and a/b/ but not c/ or d.txt
        result = tools.tree(depth=2)
        assert "a/" in result
        assert "b/" in result
        assert "d.txt" not in result

    def test_tree_entry_limit(self, tmp_path):
        # Create many files to exceed limit
        for i in range(10):
            (tmp_path / f"file{i:02d}.txt").write_text("x")
        tools = _make_tools(tmp_path)
        result = tools.tree(limit=5)
        assert "[Truncated:" in result
        assert "more entries not shown]" in result

    def test_tree_ignore_dirs(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "foo.pyc").write_text("x")
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.py").write_text("x")
        tools = _make_tools(tmp_path)
        result = tools.tree()
        assert "__pycache__" not in result
        assert "src/" in result
        assert "main.py" in result

    def test_tree_empty_directory(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.tree()
        # Only root line, no entries
        assert "/" in result
        assert "├── " not in result
        assert "└── " not in result

    def test_tree_nonexistent_path(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.tree(path="nonexistent")
        assert "Error" in result

    def test_tree_outside_base_dir(self, tmp_path):
        tools = _make_tools(tmp_path)
        result = tools.tree(path="/tmp")
        assert "Error" in result
