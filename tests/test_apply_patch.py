"""Tests for apply_patch — parser and applicator."""

import pytest

from hooty.tools.apply_patch import (
    AddFile,
    Chunk,
    Change,
    DeleteFile,
    PatchApplyError,
    PatchParseError,
    UpdateFile,
    apply_operations,
    parse_patch,
)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParsePatch:
    """Test patch text parsing."""

    def test_empty_patch(self):
        ops = parse_patch("*** Begin Patch\n*** End Patch")
        assert ops == []

    def test_missing_begin_marker(self):
        with pytest.raises(PatchParseError, match="Begin Patch"):
            parse_patch("*** End Patch")

    def test_missing_end_marker(self):
        with pytest.raises(PatchParseError, match="End Patch"):
            parse_patch("*** Begin Patch\nstuff")

    def test_add_file(self):
        patch = """\
*** Begin Patch
*** Add File: src/new.py
+print("hello")
+print("world")
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 1
        assert isinstance(ops[0], AddFile)
        assert ops[0].path == "src/new.py"
        assert ops[0].content == 'print("hello")\nprint("world")'

    def test_delete_file(self):
        patch = """\
*** Begin Patch
*** Delete File: old.txt
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 1
        assert isinstance(ops[0], DeleteFile)
        assert ops[0].path == "old.txt"

    def test_update_file_simple(self):
        patch = """\
*** Begin Patch
*** Update File: main.py
@@ def hello():
-    print("old")
+    print("new")
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 1
        op = ops[0]
        assert isinstance(op, UpdateFile)
        assert op.path == "main.py"
        assert op.move_to is None
        assert len(op.chunks) == 1
        assert op.chunks[0].context == "def hello():"
        assert len(op.chunks[0].changes) == 2
        assert op.chunks[0].changes[0].type == "remove"
        assert op.chunks[0].changes[0].content == '    print("old")'
        assert op.chunks[0].changes[1].type == "add"
        assert op.chunks[0].changes[1].content == '    print("new")'

    def test_update_file_with_move(self):
        patch = """\
*** Begin Patch
*** Update File: old_name.py
*** Move to: new_name.py
@@ def foo():
-    return 1
+    return 2
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 1
        op = ops[0]
        assert isinstance(op, UpdateFile)
        assert op.path == "old_name.py"
        assert op.move_to == "new_name.py"

    def test_multiple_operations(self):
        patch = """\
*** Begin Patch
*** Add File: a.txt
+alpha
*** Delete File: b.txt
*** Update File: c.txt
@@ header
-old
+new
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 3
        assert isinstance(ops[0], AddFile)
        assert isinstance(ops[1], DeleteFile)
        assert isinstance(ops[2], UpdateFile)

    def test_multiple_chunks(self):
        patch = """\
*** Begin Patch
*** Update File: multi.py
@@ def first():
-    return 1
+    return 10
@@ def second():
-    return 2
+    return 20
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 1
        op = ops[0]
        assert isinstance(op, UpdateFile)
        assert len(op.chunks) == 2
        assert op.chunks[0].context == "def first():"
        assert op.chunks[1].context == "def second():"


# ---------------------------------------------------------------------------
# Applicator tests
# ---------------------------------------------------------------------------


class TestApplyOperations:
    """Test applying operations to files on disk."""

    def test_add_file(self, tmp_path):
        ops = [AddFile(path="new.txt", content="hello world")]
        result = apply_operations(ops, tmp_path)
        assert "Added: new.txt" in result
        assert (tmp_path / "new.txt").read_text().strip() == "hello world"

    def test_add_file_nested(self, tmp_path):
        ops = [AddFile(path="sub/dir/file.txt", content="nested")]
        result = apply_operations(ops, tmp_path)
        assert "Added: sub/dir/file.txt" in result
        assert (tmp_path / "sub/dir/file.txt").exists()

    def test_delete_file(self, tmp_path):
        (tmp_path / "doomed.txt").write_text("bye")
        ops = [DeleteFile(path="doomed.txt")]
        result = apply_operations(ops, tmp_path)
        assert "Deleted: doomed.txt" in result
        assert not (tmp_path / "doomed.txt").exists()

    def test_delete_nonexistent(self, tmp_path):
        ops = [DeleteFile(path="nope.txt")]
        result = apply_operations(ops, tmp_path)
        assert "Warning" in result

    def test_update_file_simple(self, tmp_path):
        (tmp_path / "main.py").write_text("def hello():\n    print('old')\n")
        ops = [
            UpdateFile(
                path="main.py",
                chunks=[
                    Chunk(
                        context="def hello():",
                        changes=[
                            Change(type="remove", content="    print('old')"),
                            Change(type="add", content="    print('new')"),
                        ],
                    )
                ],
            )
        ]
        result = apply_operations(ops, tmp_path)
        assert "Updated: main.py" in result
        content = (tmp_path / "main.py").read_text()
        assert "print('new')" in content
        assert "print('old')" not in content

    def test_update_file_with_move(self, tmp_path):
        (tmp_path / "old.py").write_text("def foo():\n    return 1\n")
        ops = [
            UpdateFile(
                path="old.py",
                move_to="new.py",
                chunks=[
                    Chunk(
                        context="def foo():",
                        changes=[
                            Change(type="remove", content="    return 1"),
                            Change(type="add", content="    return 2"),
                        ],
                    )
                ],
            )
        ]
        result = apply_operations(ops, tmp_path)
        assert "moved" in result.lower()
        assert not (tmp_path / "old.py").exists()
        assert "return 2" in (tmp_path / "new.py").read_text()

    def test_update_nonexistent_file(self, tmp_path):
        ops = [UpdateFile(path="nope.py", chunks=[])]
        with pytest.raises(PatchApplyError, match="not found"):
            apply_operations(ops, tmp_path)

    def test_multiple_operations(self, tmp_path):
        (tmp_path / "existing.txt").write_text("line1\nline2\n")
        ops = [
            AddFile(path="new.txt", content="created"),
            DeleteFile(path="existing.txt"),
        ]
        result = apply_operations(ops, tmp_path)
        assert "Added: new.txt" in result
        assert "Deleted: existing.txt" in result

    def test_empty_operations(self, tmp_path):
        result = apply_operations([], tmp_path)
        assert "No operations" in result

    def test_add_only_lines(self, tmp_path):
        (tmp_path / "app.py").write_text("import os\n\ndef main():\n    pass\n")
        ops = [
            UpdateFile(
                path="app.py",
                chunks=[
                    Chunk(
                        context="import os",
                        changes=[
                            Change(type="add", content="import sys"),
                        ],
                    )
                ],
            )
        ]
        result = apply_operations(ops, tmp_path)
        assert "Updated: app.py" in result
        content = (tmp_path / "app.py").read_text()
        assert "import sys" in content
        assert "import os" in content

    def test_consecutive_update_files(self, tmp_path):
        """Two consecutive Update File operations are parsed and applied correctly."""
        (tmp_path / "a.py").write_text("def a():\n    return 1\n")
        (tmp_path / "b.py").write_text("def b():\n    return 2\n")
        patch = """\
*** Begin Patch
*** Update File: a.py
@@ def a():
-    return 1
+    return 10
*** Update File: b.py
@@ def b():
-    return 2
+    return 20
*** End Patch"""
        ops = parse_patch(patch)
        assert len(ops) == 2
        assert isinstance(ops[0], UpdateFile)
        assert isinstance(ops[1], UpdateFile)
        assert ops[0].path == "a.py"
        assert ops[1].path == "b.py"

        result = apply_operations(ops, tmp_path)
        assert "Updated: a.py" in result
        assert "Updated: b.py" in result
        assert "return 10" in (tmp_path / "a.py").read_text()
        assert "return 20" in (tmp_path / "b.py").read_text()

    def test_fuzzy_whitespace_matching(self, tmp_path):
        (tmp_path / "test.py").write_text("  def hello():\n    print('hi')\n")
        ops = [
            UpdateFile(
                path="test.py",
                chunks=[
                    Chunk(
                        context="def hello():",  # no leading spaces in context
                        changes=[
                            Change(type="remove", content="    print('hi')"),
                            Change(type="add", content="    print('bye')"),
                        ],
                    )
                ],
            )
        ]
        result = apply_operations(ops, tmp_path)
        assert "Updated: test.py" in result
        assert "print('bye')" in (tmp_path / "test.py").read_text()
