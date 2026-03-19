"""Tests for concurrency utilities."""

from __future__ import annotations

from pathlib import Path

import pytest

from hooty.concurrency import atomic_write_bytes, atomic_write_text, create_wal_engine


class TestCreateWalEngine:
    """Test WAL-mode SQLite engine creation."""

    def test_wal_mode_enabled(self, tmp_path: Path):
        db_path = str(tmp_path / "test.db")
        engine = create_wal_engine(db_path)
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA journal_mode").scalar()
            assert result == "wal"

    def test_busy_timeout_set(self, tmp_path: Path):
        db_path = str(tmp_path / "test.db")
        engine = create_wal_engine(db_path)
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA busy_timeout").scalar()
            assert result == 10000

    def test_synchronous_normal(self, tmp_path: Path):
        db_path = str(tmp_path / "test.db")
        engine = create_wal_engine(db_path)
        with engine.connect() as conn:
            # NORMAL = 1
            result = conn.exec_driver_sql("PRAGMA synchronous").scalar()
            assert result == 1

    def test_two_engines_concurrent_access(self, tmp_path: Path):
        db_path = str(tmp_path / "test.db")
        engine1 = create_wal_engine(db_path)
        engine2 = create_wal_engine(db_path)

        # Create table with engine1
        with engine1.connect() as conn:
            conn.exec_driver_sql("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY, val TEXT)")
            conn.exec_driver_sql("INSERT INTO t (val) VALUES ('from_e1')")
            conn.commit()

        # Write from engine2
        with engine2.connect() as conn:
            conn.exec_driver_sql("INSERT INTO t (val) VALUES ('from_e2')")
            conn.commit()

        # Read back from engine1
        with engine1.connect() as conn:
            rows = conn.exec_driver_sql("SELECT val FROM t ORDER BY id").fetchall()
            assert len(rows) == 2
            assert rows[0][0] == "from_e1"
            assert rows[1][0] == "from_e2"

        engine1.dispose()
        engine2.dispose()


class TestAtomicWriteText:
    """Test atomic text file writing."""

    def test_basic_write(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        atomic_write_text(target, "hello world")
        assert target.read_text() == "hello world"

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        target.write_text("old content")
        atomic_write_text(target, "new content")
        assert target.read_text() == "new content"

    def test_no_temp_files_left(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        atomic_write_text(target, "content")
        files = list(tmp_path.iterdir())
        assert len(files) == 1
        assert files[0].name == "test.txt"

    def test_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "a" / "b" / "test.txt"
        atomic_write_text(target, "nested")
        assert target.read_text() == "nested"

    def test_original_survives_on_error(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        target.write_text("original")

        # Simulate error during write by using a bad encoding
        with pytest.raises(Exception):
            atomic_write_text(target, "\udcff", encoding="ascii")

        assert target.read_text() == "original"

    def test_no_temp_files_on_error(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        with pytest.raises(Exception):
            atomic_write_text(target, "\udcff", encoding="ascii")
        # Only check for files starting with dot (temp pattern)
        temp_files = [f for f in tmp_path.iterdir() if f.name.startswith(".")]
        assert len(temp_files) == 0

    def test_encoding_utf8(self, tmp_path: Path):
        target = tmp_path / "test.txt"
        atomic_write_text(target, "日本語テスト")
        assert target.read_text(encoding="utf-8") == "日本語テスト"


class TestAtomicWriteBytes:
    """Test atomic bytes file writing."""

    def test_basic_write(self, tmp_path: Path):
        target = tmp_path / "test.bin"
        data = b"\x00\x01\x02\xff"
        atomic_write_bytes(target, data)
        assert target.read_bytes() == data

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "test.bin"
        target.write_bytes(b"old")
        atomic_write_bytes(target, b"new")
        assert target.read_bytes() == b"new"

    def test_no_temp_files_left(self, tmp_path: Path):
        target = tmp_path / "test.bin"
        atomic_write_bytes(target, b"data")
        files = list(tmp_path.iterdir())
        assert len(files) == 1
