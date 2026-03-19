"""Integration tests for concurrent database access with WAL mode.

These tests verify that multiple threads/processes can safely access
the same SQLite database simultaneously.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from hooty.concurrency import create_wal_engine


@pytest.mark.integration
class TestConcurrentDb:
    """Test concurrent access to SQLite databases with WAL mode."""

    def test_concurrent_session_db_writes(self, tmp_path: Path):
        """Two threads writing to the same sessions.db simultaneously."""
        db_path = str(tmp_path / "sessions.db")

        # Create table
        engine_setup = create_wal_engine(db_path)
        with engine_setup.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)"
            )
            conn.commit()
        engine_setup.dispose()

        errors: list[Exception] = []
        rows_per_thread = 50

        def writer(thread_id: int) -> None:
            engine = create_wal_engine(db_path)
            try:
                for i in range(rows_per_thread):
                    with engine.connect() as conn:
                        conn.exec_driver_sql(
                            "INSERT INTO t (val) VALUES (?)",
                            (f"thread-{thread_id}-{i}",),
                        )
                        conn.commit()
            except Exception as e:
                errors.append(e)
            finally:
                engine.dispose()

        t1 = threading.Thread(target=writer, args=(1,))
        t2 = threading.Thread(target=writer, args=(2,))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not errors, f"Errors occurred: {errors}"

        # Verify all rows were written
        engine_check = create_wal_engine(db_path)
        with engine_check.connect() as conn:
            count = conn.exec_driver_sql("SELECT COUNT(*) FROM t").scalar()
            assert count == rows_per_thread * 2
        engine_check.dispose()

    def test_concurrent_read_write(self, tmp_path: Path):
        """One thread writing, another reading simultaneously."""
        db_path = str(tmp_path / "memory.db")

        engine_setup = create_wal_engine(db_path)
        with engine_setup.connect() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, val TEXT)"
            )
            conn.commit()
        engine_setup.dispose()

        errors: list[Exception] = []
        write_count = 100

        def writer() -> None:
            engine = create_wal_engine(db_path)
            try:
                for i in range(write_count):
                    with engine.connect() as conn:
                        conn.exec_driver_sql(
                            "INSERT INTO t (val) VALUES (?)", (f"row-{i}",)
                        )
                        conn.commit()
            except Exception as e:
                errors.append(e)
            finally:
                engine.dispose()

        def reader() -> None:
            engine = create_wal_engine(db_path)
            try:
                for _ in range(write_count):
                    with engine.connect() as conn:
                        conn.exec_driver_sql("SELECT COUNT(*) FROM t").scalar()
            except Exception as e:
                errors.append(e)
            finally:
                engine.dispose()

        tw = threading.Thread(target=writer)
        tr = threading.Thread(target=reader)
        tw.start()
        tr.start()
        tw.join(timeout=30)
        tr.join(timeout=30)

        assert not errors, f"Errors occurred: {errors}"
