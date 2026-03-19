"""Tests for FileSnapshotStore."""

from __future__ import annotations

from pathlib import Path

import pytest

from hooty.file_snapshot import FileSnapshotStore


@pytest.fixture
def session_dir(tmp_path: Path) -> Path:
    sd = tmp_path / "session"
    sd.mkdir()
    return sd


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    wd = tmp_path / "work"
    wd.mkdir()
    return wd


class TestCaptureAndChanges:
    def test_new_file_created(self, session_dir: Path, work_dir: Path) -> None:
        """New file → status='created', original=None."""
        store = FileSnapshotStore(session_dir)
        fp = work_dir / "new.txt"

        store.capture_before_write(fp)
        fp.write_text("hello")
        store.record_after_write(fp)

        changes = store.get_changes()
        assert len(changes) == 1
        c = changes[0]
        assert c.status == "created"
        assert c.original is None
        assert c.current == "hello"
        assert not c.externally_modified

    def test_existing_file_modified(self, session_dir: Path, work_dir: Path) -> None:
        """Existing file → status='modified', original preserved."""
        fp = work_dir / "exist.txt"
        fp.write_text("original content")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("modified content")
        store.record_after_write(fp)

        changes = store.get_changes()
        assert len(changes) == 1
        c = changes[0]
        assert c.status == "modified"
        assert c.original == "original content"
        assert c.current == "modified content"

    def test_multiple_edits_keep_first_snapshot(self, session_dir: Path, work_dir: Path) -> None:
        """Multiple edits to the same file only snapshot the original."""
        fp = work_dir / "multi.txt"
        fp.write_text("v1")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("v2")
        store.record_after_write(fp)

        store.capture_before_write(fp)  # should be no-op
        fp.write_text("v3")
        store.record_after_write(fp)

        changes = store.get_changes()
        assert len(changes) == 1
        assert changes[0].original == "v1"
        assert changes[0].current == "v3"

    def test_file_deleted(self, session_dir: Path, work_dir: Path) -> None:
        """File deleted after modification → status='deleted'."""
        fp = work_dir / "del.txt"
        fp.write_text("content")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("modified")
        store.record_after_write(fp)

        fp.unlink()
        changes = store.get_changes()
        assert len(changes) == 1
        assert changes[0].status == "deleted"
        assert changes[0].original == "content"
        assert changes[0].current is None

    def test_unchanged_file_excluded(self, session_dir: Path, work_dir: Path) -> None:
        """File modified then reverted to original → no changes reported."""
        fp = work_dir / "same.txt"
        fp.write_text("original")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("changed")
        store.record_after_write(fp)

        # Revert manually
        fp.write_text("original")
        changes = store.get_changes()
        assert len(changes) == 0


class TestExternalModification:
    def test_external_change_detected(self, session_dir: Path, work_dir: Path) -> None:
        """File changed outside session → externally_modified=True."""
        fp = work_dir / "ext.txt"
        fp.write_text("original")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("by_llm")
        store.record_after_write(fp)

        # External change after record
        fp.write_text("by_user")

        changes = store.get_changes()
        assert len(changes) == 1
        assert changes[0].externally_modified is True


class TestSessionResume:
    def test_index_persists_across_instances(self, session_dir: Path, work_dir: Path) -> None:
        """New instance loads existing index from disk."""
        fp = work_dir / "persist.txt"
        fp.write_text("original")

        store1 = FileSnapshotStore(session_dir)
        store1.capture_before_write(fp)
        fp.write_text("modified")
        store1.record_after_write(fp)

        # New instance
        store2 = FileSnapshotStore(session_dir)
        changes = store2.get_changes()
        assert len(changes) == 1
        assert changes[0].original == "original"
        assert changes[0].current == "modified"


class TestRestore:
    def test_restore_modified_file(self, session_dir: Path, work_dir: Path) -> None:
        """restore() reverts file content and removes entry."""
        fp = work_dir / "restore.txt"
        fp.write_text("original")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("modified")
        store.record_after_write(fp)

        assert store.restore(str(fp))
        assert fp.read_text() == "original"
        assert store.get_changes() == []

    def test_restore_created_file_deletes_it(self, session_dir: Path, work_dir: Path) -> None:
        """restore() for a newly created file deletes it."""
        fp = work_dir / "created.txt"

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("new content")
        store.record_after_write(fp)

        assert store.restore(str(fp))
        assert not fp.exists()

    def test_restore_externally_modified(self, session_dir: Path, work_dir: Path) -> None:
        """restore() works even for externally modified files."""
        fp = work_dir / "ext_restore.txt"
        fp.write_text("original")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_text("by_llm")
        store.record_after_write(fp)

        fp.write_text("by_user")  # external
        assert store.restore(str(fp))
        assert fp.read_text() == "original"

    def test_restore_nonexistent_entry(self, session_dir: Path) -> None:
        """restore() returns False for unknown path."""
        store = FileSnapshotStore(session_dir)
        assert not store.restore("/nonexistent")


class TestBinaryFiles:
    def test_binary_file_shows_none_content(self, session_dir: Path, work_dir: Path) -> None:
        """Binary file content is reported as None."""
        fp = work_dir / "bin.dat"
        fp.write_bytes(b"\x00\x01\x02\xff")

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_bytes(b"\x00\x01\x02\xfe")
        store.record_after_write(fp)

        changes = store.get_changes()
        assert len(changes) == 1
        assert changes[0].original is None
        assert changes[0].current is None
        assert changes[0].status == "modified"

    def test_restore_binary_file(self, session_dir: Path, work_dir: Path) -> None:
        """Binary files can be restored byte-for-byte."""
        fp = work_dir / "bin_restore.dat"
        original = b"\x00\x01\x02\xff"
        fp.write_bytes(original)

        store = FileSnapshotStore(session_dir)
        store.capture_before_write(fp)
        fp.write_bytes(b"\xaa\xbb")
        store.record_after_write(fp)

        assert store.restore(str(fp))
        assert fp.read_bytes() == original
